import asyncio
import base64
import hmac
import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from clients.redis import redis_client
from clients.websocket import websocket_manager
from config import Configuration
from database import db_session
from models import Conversation, ConversationStatus, Message, Participant
from services.crypto import _encrypt
from services.utils import generate_token_hash

WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_NOT_FOUND = 4404
WS_CLOSE_EXPIRED = 4100
MAX_MESSAGE_LENGTH = 4000
AUTH_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)
config = Configuration()


class WebsocketService:
    def __init__(self):
        self.ws_manager = websocket_manager

    async def _publish_event(self, conversation_id, payload):
        try:
            await redis_client.publish_conversation_event(conversation_id, payload)
        except Exception:
            redis_client.record_local_failure()
            logger.error("Could not publish conversation event")
            if payload.get("type") == "message" and "ciphertext" in payload:
                ciphertext = base64.b64decode(payload.pop("ciphertext"))
                from services.crypto import _decrypt
                payload["message"] = _decrypt(ciphertext)
            await self.ws_manager.broadcast_local(conversation_id, payload)

    def ws_authenticate(self, conversation_id, participant_id, token):
        with db_session() as db:
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            if conversation.status in (ConversationStatus.DELETED, ConversationStatus.ENDED):
                raise HTTPException(410, "Conversation has ended.")
            if conversation.expires_at and conversation.expires_at < datetime.now(timezone.utc):
                raise HTTPException(410, "Conversation has expired.")
            participant = db.query(Participant).filter(Participant.id == participant_id).first()
            if participant is None or participant.conversation_id != conversation_id or participant.left_at is not None:
                raise HTTPException(401, "Invalid participant.")
            if not hmac.compare_digest(participant.participant_token, generate_token_hash(token)):
                raise HTTPException(401, "Invalid token.")
            return participant.id

    async def handle_ws_connection(self, websocket: WebSocket, conversation_id: UUID):
        await websocket.accept()
        try:
            auth = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS))
            if auth.get("type") != "authenticate":
                raise ValueError("Missing authentication frame")
            participant_id = UUID(auth["participant_id"])
            token = auth["participant_token"]
            if not isinstance(token, str) or not token:
                raise ValueError("Missing participant token")
        except Exception:
            await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        try:
            participant_id = await run_in_threadpool(self.ws_authenticate, conversation_id, participant_id, token)
        except HTTPException as exc:
            code = WS_CLOSE_UNAUTHORIZED if exc.status_code == 401 else WS_CLOSE_EXPIRED if exc.status_code == 410 else WS_CLOSE_NOT_FOUND
            await websocket.close(code=code)
            return

        connection_id = str(uuid4())
        await self.ws_manager.connect(conversation_id, participant_id, websocket)
        try:
            first_online = await redis_client.register_presence(
                conversation_id, participant_id, connection_id, config.PRESENCE_TTL_SECONDS
            )
            await self.ws_manager.send_to(websocket, {"type": "authenticated"})
            peers = await redis_client.list_presence(conversation_id)
            await self.ws_manager.send_to(websocket, {"type": "presence_snapshot", "participants": peers})
            if first_online:
                await redis_client.increment_metric("websocket_connections_total")
                await self._publish_event(conversation_id, {"type": "participant_joined", "participant_id": str(participant_id)})
            await self.ws_receive_loop(websocket, conversation_id, participant_id, connection_id)
        except WebSocketDisconnect:
            logger.info("Participant disconnected")
        except Exception:
            logger.error("WebSocket connection failed")
            try:
                await websocket.close(code=1013, reason="Temporary service failure")
            except Exception:
                pass
        finally:
            try:
                was_current = await redis_client.remove_presence(conversation_id, participant_id, connection_id)
                if was_current:
                    await redis_client.increment_metric("websocket_disconnects_total")
                    await self._publish_event(conversation_id, {"type": "participant_left", "participant_id": str(participant_id)})
            except Exception:
                redis_client.record_local_failure()
                logger.error("Could not release participant presence")
            await self.ws_manager.disconnect(conversation_id, participant_id, websocket)

    async def ws_receive_loop(self, websocket, conversation_id, participant_id, connection_id):
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), config.PRESENCE_TTL_SECONDS)
            except asyncio.TimeoutError:
                await websocket.close(code=1013, reason="Heartbeat timeout")
                return
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                frame = {"type": "message", "message": raw}
            if frame.get("type") == "ping":
                refreshed = await redis_client.refresh_presence(conversation_id, participant_id, connection_id, config.PRESENCE_TTL_SECONDS)
                if not refreshed:
                    await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Presence lease lost")
                    return
                await self.ws_manager.send_to(websocket, {"type": "pong"})
                continue
            if frame.get("type") != "message":
                await self.ws_manager.send_to(websocket, {"type": "message_error", "detail": "Unsupported message frame."})
                continue
            text = frame.get("message", "")
            if not isinstance(text, str) or not text.strip():
                continue
            if len(text) > MAX_MESSAGE_LENGTH:
                await websocket.close(code=1009, reason="Message is too long.")
                return
            try:
                client_message_id = UUID(frame["client_message_id"])
            except (KeyError, ValueError, TypeError):
                client_message_id = uuid4()
            allowed, retry_ms = await redis_client.consume_rate_limit(
                f"textie:rate:message:{participant_id}", config.MESSAGE_RATE_LIMIT,
                config.MESSAGE_RATE_WINDOW_SECONDS,
            )
            if not allowed:
                await redis_client.increment_metric("message_rate_limit_rejections_total")
                await self.ws_manager.send_to(websocket, {"type": "message_error", "client_message_id": str(client_message_id), "detail": "You are sending messages too quickly.", "retry_after_ms": retry_ms})
                continue
            try:
                saved = await run_in_threadpool(self._persist_message, conversation_id, participant_id, text.strip(), client_message_id)
            except HTTPException as exc:
                await websocket.close(code=WS_CLOSE_EXPIRED if exc.status_code == 410 else WS_CLOSE_NOT_FOUND)
                return
            await self._publish_event(conversation_id, {
                "type": "message", "participant_id": str(participant_id),
                "message_id": saved["id"], "sequence": saved["sequence"],
                "client_message_id": str(client_message_id), "sent_at": saved["sent_at"],
                "ciphertext": base64.b64encode(saved["ciphertext"]).decode("ascii"),
            })
            if saved["created"]:
                await redis_client.increment_metric("messages_persisted_total")
            await self.ws_manager.send_to(websocket, {
                "type": "message_ack", "client_message_id": str(client_message_id),
                "message_id": saved["id"], "sequence": saved["sequence"], "sent_at": saved["sent_at"],
            })

    def _persist_message(self, conversation_id, participant_id, message, client_message_id):
        with db_session() as db:
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).with_for_update().first()
            if conversation is None or conversation.status in (ConversationStatus.DELETED, ConversationStatus.ENDED):
                raise HTTPException(404, "Conversation not found.")
            if conversation.expires_at and conversation.expires_at < datetime.now(timezone.utc):
                raise HTTPException(410, "Conversation has expired.")
            prior = db.query(Message).filter(
                Message.participant_id == participant_id,
                Message.client_message_id == client_message_id,
            ).first()
            if prior:
                return {"id": str(prior.id), "sequence": prior.sequence, "sent_at": prior.sent_at.isoformat(), "ciphertext": prior.ciphertext, "created": False}
            conversation.last_message_sequence += 1
            row = Message(
                conversation_id=conversation_id, participant_id=participant_id,
                ciphertext=_encrypt(message), sequence=conversation.last_message_sequence,
                client_message_id=client_message_id,
            )
            db.add(row)
            db.flush()
            return {"id": str(row.id), "sequence": row.sequence, "sent_at": row.sent_at.isoformat(), "ciphertext": row.ciphertext, "created": True}
