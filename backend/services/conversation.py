from uuid import UUID
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from database import db_session
from models import (
    Conversation, Participant, ConversationStatus, Message
)
from schema import (
    ConversationJoinRequest, ConversationLeaveRequest,
    ConversationCreateResponse, ConversationJoinResponse,
    ConversationLeaveResponse,
    ChatHistoryRequest, ChatHistoryResponse, MessageResponse
)
from config import Configuration
from .utils import (
    generate_code, generate_token, generate_token_hash
)
from services.crypto import _decrypt

config = Configuration()

class ConversationService:

    def _generate_unique_code(self, db) -> str:
        while True:
            code = generate_code()
            conversation = (
                db.query(Conversation)
                .filter(
                    Conversation.code == code,
                    Conversation.status != ConversationStatus.DELETED,
                )
                .first()
            )
            if conversation is None:
                return code

    def create_conversation(self):
        token = generate_token()
        token_hash = generate_token_hash(token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with db_session() as db:
            code = self._generate_unique_code(db=db)
            conversation = Conversation(
                code=code,
                owner_token_hash=token_hash,
                expires_at=expires_at
            )
            db.add(conversation)
            db.flush()

            participant = Participant(
                conversation_id=conversation.id,
                participant_token=token_hash,
                is_owner=True
            )
            db.add(participant)

            return ConversationCreateResponse(
                conversation_id=conversation.id,
                code=code,
                participant_token=token,
                participant_id=participant.id,
                expires_at=expires_at
            )

    def join_conversation(self, request: ConversationJoinRequest):
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.code == request.code
                ).first()
            )

            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status == ConversationStatus.DELETED:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status == ConversationStatus.ENDED:
                raise HTTPException(status_code=410, detail="Conversation has ended.")
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                raise HTTPException(status_code=410, detail="Conversation has expired.")

            if conversation.status == ConversationStatus.INACTIVE:
                conversation.status = ConversationStatus.ACTIVE
                conversation.inactive_at = None

            token = generate_token()
            token_hash = generate_token_hash(token)

            participant = Participant(
                conversation_id=conversation.id,
                participant_token=token_hash,
                is_owner=False,
            )
            db.add(participant)

            if conversation.status == ConversationStatus.WAITING:
                conversation.status = ConversationStatus.ACTIVE

            return ConversationJoinResponse(
                conversation_id=conversation.id,
                code=conversation.code,
                participant_id=participant.id,
                participant_token=token,
                expires_at=conversation.expires_at,
            )

    def leave_conversation(self, conversation_id: UUID, request: ConversationLeaveRequest):
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            )
            if conversation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Conversation not found."
                )

            participant = (
                db.query(Participant).filter(
                    Participant.id == request.participant_id,
                    Participant.conversation_id == conversation_id,
                    Participant.left_at.is_(None)
                ).first()
            )
            if participant is None:
                raise HTTPException(
                    status_code=404, detail="Participant not found."
                )

            participant.left_at = datetime.now(timezone.utc)

            active_participants = (
                db.query(Participant).filter(
                    Participant.conversation_id == conversation_id,
                    Participant.left_at.is_(None)
                ).count()
            )

            if active_participants == 0:
                conversation.status = ConversationStatus.INACTIVE
                conversation.inactive_at = datetime.now(timezone.utc)
            elif conversation.status == ConversationStatus.INACTIVE:
                conversation.status = ConversationStatus.ACTIVE
                conversation.inactive_at = None

            return ConversationLeaveResponse(
                conversation_id=conversation_id,
                participant_id=participant.id,
                status=str(conversation.status),
            )

    def cleanup_inactive_conversations(self):
        now = datetime.now(timezone.utc)
        grace_seconds = int(config.CONVERSATION_GRACE_PERIOD or 120)
        cutoff = now - timedelta(seconds=grace_seconds)

        deleted_count = 0
        with db_session() as db:
            conversations = (
                db.query(Conversation).filter(
                    Conversation.status == ConversationStatus.INACTIVE,
                    Conversation.inactive_at.is_not(None),
                    Conversation.inactive_at <= cutoff
                )
            )

            for conversation in conversations:
                active_participants = (
                    db.query(Participant).filter(
                        Participant.conversation_id == conversation.id,
                        Participant.left_at.is_(None)
                    ).count()
                )
                if active_participants > 0:
                    conversation.status = ConversationStatus.ACTIVE
                    conversation.inactive_at = None
                    continue

                db.delete(conversation)
                deleted_count += 1

        expired_count = self.cleanup_expired_conversations()
        deleted_count += expired_count
        return deleted_count

    def cleanup_expired_conversations(self):
        now = datetime.now(timezone.utc)
        deleted_count = 0
        with db_session() as db:
            expired = (
                db.query(Conversation).filter(
                    Conversation.expires_at.is_not(None),
                    Conversation.expires_at < now,
                    Conversation.status != ConversationStatus.DELETED,
                )
            )
            for conversation in expired:
                db.delete(conversation)
                deleted_count += 1
        return deleted_count

    def _authenticate_participant(self, db, conversation_id: UUID, token: str):
        token_hash = generate_token_hash(token=token)
        participant = db.query(Participant).filter(
            Participant.conversation_id == conversation_id,
            Participant.participant_token == token_hash,
            Participant.left_at.is_(None)
        ).first()

        if participant is None:
            raise HTTPException(status_code=401, detail="Invalid participant token")

    def get_chat_history(self, conversation_id: UUID, request: ChatHistoryRequest):
        with db_session() as db:
            conversation = db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).first()

            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")

            if conversation.status == ConversationStatus.DELETED:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status == ConversationStatus.ENDED:
                raise HTTPException(status_code=410, detail="Conversation has ended.")
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                raise HTTPException(status_code=410, detail="Conversation has expired.")

            self._authenticate_participant(
                db=db,
                conversation_id=conversation_id,
                token=request.participant_token
            )

            messages = db.query(Message).filter(
                Message.conversation_id == conversation_id
            ).order_by(Message.sent_at.asc()).all()

            chat_messages = []

            for msg in messages:
                message = _decrypt(msg.ciphertext)
                chat_messages.append(MessageResponse(
                    id=msg.id,
                    participant_id=msg.participant_id,
                    message=message,
                    sent_at=msg.sent_at
                ))

            return ChatHistoryResponse(messages=chat_messages)