from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import desc

from database import db_session
from schema import (
    MessageResponse
)
from models import (
    Message, Participant
)
from services.utils import generate_token_hash
from services.crypto import _decrypt


class MessageService:

    def get_message(self, conversation_id: UUID, participant_id: UUID, token: str):
        with db_session() as db:
            participant = (
                db.query(Participant).filter(
                    Participant.id == participant_id,
                    Participant.conversation_id == conversation_id
                ).first()
            )

            if participant is None:
                raise HTTPException(
                    status_code=403, detail="Invalid participant."
                )

            token_hash = generate_token_hash(token=token)

            if participant.participant_token != token_hash:
                raise HTTPException(
                    status_code=403, detail="Invalid participant token."
                )

            messages = (
                db.query(Message).filter(
                    Message.conversation_id == conversation_id
                ).order_by(Message.sent_at.asc()).all()
            )
            result = []
            for message in messages:
                plain_text = _decrypt(text=message.ciphertext)
                result.append(MessageResponse(
                    id = message.id, participant_id=message.participant_id,
                    message=plain_text, sent_at=message.sent_at
                ))

            return result