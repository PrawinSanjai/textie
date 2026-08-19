import traceback
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from uuid import UUID

from database import db_session
from models import Participant, Message

from clients.websocket import WebsocketManager
from services.utils import generate_token_hash
from services.crypto import _encrypt
from services.conversation import ConversationService


class WebsocketService:

    def __init__(self):
        self.ws_manager = WebsocketManager()
        self.connection_service = ConversationService()

    def ws_authenticate(self, conversation_id, participant_id, token):
        with db_session() as db:
            participant = (db.query(Participant).filter(Participant.id==participant_id).first())

            if participant  is None:
                raise HTTPException(status_code=401, detail="Invalid participant.")
            if participant.conversation_id != conversation_id:
                raise HTTPException(status_code=401, detail="Invalid participant.")

            token_hash = generate_token_hash(token)
            if participant.participant_token != token_hash:
                raise HTTPException(status_code=401, detail="Invalid token.")

            return participant

    async def handle_ws_connection(self, websocket: WebSocket, conversation_id: UUID):
        participant_id = websocket.query_params.get("participant_id")
        token = websocket.query_params.get("token")

        if not participant_id or not token:
            await websocket.close(code=1000)
            return

        try:
            participant_id = UUID(participant_id)
        except ValueError:
            await websocket.close(code=1000)
            return

        participant = self.ws_authenticate(
            conversation_id=conversation_id,
            participant_id=participant_id,
            token=token
        )

        if participant is None:
            await websocket.close(code=1000)
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
            self.conversation_service.leave_conversation(
                conversation_id=conversation_id,
                participant_id=participant.id
            )

    async def ws_receive_loop(self, websocket: WebSocket, conversation_id: UUID, participant: Participant):
        while True:
            message = await websocket.receive_text()
            print(
                        f"Received from {participant.id}: {message}"
                    )

            await self.ws_process_message(
                conversation_id=conversation_id,
                participant=participant,
                message=message,
            )

            print("MESSAGE PROCESSING FINISHED")

    
    async def ws_process_message(self, conversation_id: UUID, participant: Participant, message: str):
        encrypted_message = _encrypt(message)

        with db_session() as db:
            db_message = Message(
                conversation_id=conversation_id,
                participant_id=participant.id,
                ciphertext=encrypted_message
            )
            db.add(db_message)
            db.commit()
            db.refresh(db_message)

        print(
        f"Message saved: {db_message.id}"
    )

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