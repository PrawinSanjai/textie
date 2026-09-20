from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException

from database import db_session
from schema import (
    MessageResponse
)
from models import (
    Message, Participant, Conversation, ConversationStatus
)
from services.utils import generate_token_hash
from services.crypto import _decrypt


class MessageService:

    def get_message(self, conversation_id: UUID, participant_id: UUID, token: str):
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            )
            if conversation is None or conversation.status == ConversationStatus.DELETED:
                raise HTTPException(
                    status_code=404, detail="Conversation not found."
                )
            if conversation.status == ConversationStatus.ENDED:
                raise HTTPException(
                    status_code=410, detail="Conversation has ended."
                )
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                raise HTTPException(
                    status_code=410, detail="Conversation has expired."
                )

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

            if participant.left_at is not None:
                raise HTTPException(
                    status_code=410, detail="You have left this conversation."
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
                    id=message.id, participant_id=message.participant_id,
                    message=plain_text, sent_at=message.sent_at
                ))

            return result