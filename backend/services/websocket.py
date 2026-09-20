import traceback
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from database import db_session
from models import Participant, Message, Conversation, ConversationStatus

from clients.websocket import WebsocketManager
from services.utils import generate_token_hash
from services.crypto import _encrypt


WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_NOT_FOUND = 4404
WS_CLOSE_EXPIRED = 4100
MAX_MESSAGE_LENGTH = 4000


class WebsocketService:

    def __init__(self):
        self.ws_manager = WebsocketManager()

    async def _reject(self, websocket: WebSocket, code: int):
        # Accept first so the client actually receives the close code.
        # Closing before accept sends an HTTP 403, which surfaces as an
        # opaque 1006 "abnormal closure" on the browser.
        await websocket.accept()
        await websocket.close(code=code)

    def ws_authenticate(self, conversation_id, participant_id, token):
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status in (
                ConversationStatus.DELETED,
                ConversationStatus.ENDED,
            ):
                raise HTTPException(status_code=410, detail="Conversation has ended.")
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                raise HTTPException(status_code=410, detail="Conversation has expired.")

            participant = (
                db.query(Participant).filter(Participant.id == participant_id).first()
            )
            if (
                participant is None
                or participant.conversation_id != conversation_id
                or participant.left_at is not None
            ):
                raise HTTPException(status_code=401, detail="Invalid participant.")

            token_hash = generate_token_hash(token)
            if participant.participant_token != token_hash:
                raise HTTPException(status_code=401, detail="Invalid token.")

            return participant

    def _close_code_for(self, status_code: int) -> int:
        if status_code == 401:
            return WS_CLOSE_UNAUTHORIZED
        if status_code == 410:
            return WS_CLOSE_EXPIRED
        return WS_CLOSE_NOT_FOUND

    async def handle_ws_connection(self, websocket: WebSocket, conversation_id: UUID):
        participant_id = websocket.query_params.get("participant_id")
        token = websocket.query_params.get("token")

        if not participant_id or not token:
            await self._reject(websocket, WS_CLOSE_UNAUTHORIZED)
            return

        try:
            participant_id = UUID(participant_id)
        except ValueError:
            await self._reject(websocket, WS_CLOSE_UNAUTHORIZED)
            return

        try:
            participant = self.ws_authenticate(
                conversation_id=conversation_id,
                participant_id=participant_id,
                token=token
            )
        except HTTPException as e:
            await self._reject(websocket, self._close_code_for(e.status_code))
            return

        await self.ws_manager.connect(
            conversation_id=conversation_id,
            participant_id=participant.id,
            websocket=websocket
        )
        print(
            f"Participant connected: "
            f"{participant.id}"
        )

        await self.ws_manager.broadcast(
            conversation_id=conversation_id,
            payload={
                "type": "participant_joined",
                "participant_id": str(participant.id),
            }
        )

        try:
            await self.ws_receive_loop(
                websocket=websocket,
                conversation_id=conversation_id,
                participant=participant
            )
        except WebSocketDisconnect:
            print(
                f"Participant disconnected: "
                f"{participant.id}"
            )
        except Exception as e:
            print(
                f"WebSocket error: "
                f"{type(e).__name__}: {e}"
            )
            traceback.print_exc()
        finally:
            self.ws_manager.disconnect(
                conversation_id=conversation_id,
                participant_id=participant.id
            )
            await self.ws_manager.broadcast(
                conversation_id=conversation_id,
                payload={
                    "type": "participant_left",
                    "participant_id": str(participant.id),
                }
            )

    async def ws_receive_loop(self, websocket: WebSocket, conversation_id: UUID, participant: Participant):
        while True:
            message = await websocket.receive_text()
            text = (message or "").strip()
            if not text:
                continue
            if len(text) > MAX_MESSAGE_LENGTH:
                text = text[:MAX_MESSAGE_LENGTH]

            print(f"Received from {participant.id}: {text}")

            ended = await self.ws_process_message(
                websocket=websocket,
                conversation_id=conversation_id,
                participant=participant,
                message=text,
            )
            if ended:
                break

    async def ws_process_message(
        self,
        websocket: WebSocket,
        conversation_id: UUID,
        participant: Participant,
        message: str,
    ) -> bool:
        """Persist and broadcast a message.

        Returns True when the conversation is gone or expired, in which
        case the socket has already received a close frame.
        """
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            )
            if conversation is None or conversation.status in (
                ConversationStatus.DELETED,
                ConversationStatus.ENDED,
            ):
                await websocket.close(code=WS_CLOSE_NOT_FOUND)
                return True
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                await websocket.close(code=WS_CLOSE_EXPIRED)
                return True

            encrypted_message = _encrypt(message)
            db_message = Message(
                conversation_id=conversation_id,
                participant_id=participant.id,
                ciphertext=encrypted_message
            )
            db.add(db_message)
            db.refresh(db_message)

        print(f"Message saved: {db_message.id}")

        payload = {
            "participant_id": str(participant.id),
            "message": message,
            "type": "message",
            "message_id": str(db_message.id),
            "sent_at": db_message.sent_at.isoformat()
        }
        await self.ws_manager.broadcast(
            conversation_id=conversation_id,
            payload=payload
        )
        print("Broadcast complete")
        return False