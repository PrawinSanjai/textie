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
    ChatHistoryRequest, ChatHistoryResponse, MessageResponse
)
from .utils import (
    generate_code, generate_token, generate_token_hash
)
from services.crypto import _decrypt

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
            db.commit()

            return ConversationCreateResponse(
                conversation_id=conversation.id,
                code=code,
                participant_token=token,
                participant_id=participant.id,
                expires_at=expires_at
            )
    
    def join_conversation(self, request: ConversationJoinRequest):
        with db_session() as db:
            conversation = (db.query(Conversation).filter(
                    Conversation.code == request.code).first()
                )
            
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status == ConversationStatus.DELETED:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if conversation.status == ConversationStatus.ENDED:
                raise HTTPException(status_code=410, detail="Conversation has ended.")
            if conversation.status == ConversationStatus.INACTIVE:
                conversation.status = ConversationStatus.ACTIVE
                conversation.inactive_at = None
            if (
                conversation.expires_at is not None
                and conversation.expires_at < datetime.now(timezone.utc)
            ):
                print("Expiry:", conversation.expires_at)
                print("Now   :", datetime.now(timezone.utc))
                print("Expired:", conversation.expires_at < datetime.now(timezone.utc))
                raise HTTPException(status_code=410, detail="Conversation has expired.")
            
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
            db.commit()

            return ConversationJoinResponse(
                conversation_id=conversation.id,
                participant_id=participant.id,
                participant_token=token,
                expires_at=conversation.expires_at,
            )

    def leave_conversation(self, request: ConversationLeaveRequest):
        participant_id = request.participant_id
        conversation_id = request.conversation_id
        
        with db_session() as db:
            participant = (
                db.query(Participant).filter(
                    Participant.id == participant_id,
                    Participant.conversation_id == conversation_id,
                    Participant.left_at.is_(None)
                ).first()
            )
            if participant is None:
                raise HTTPException(
                    status_code=404, detail="Participant not found."
                )

            participant.left_at = datetime.now(timezone.utc)
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
            
            active_participants = (
                db.query(Participant).filter(
                    Participant.conversation_id == conversation_id,
                    Participant.left_at.is_(None)
                ).count()
            )

            if active_participants == 0:
                conversation.status = ConversationStatus.INACTIVE
                conversation.inactive_at = datetime.now(timezone.utc)

                db.commit()

                return {
                    "conversation_id": conversation.id,
                    "participant_id": participant.id,
                    "status": conversation.status
                }

    def get_chat_history(self, conversation_id: UUID, request: ChatHistoryRequest):
        with db_session() as db:
            conversation = (
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).first()
            )

            if conversation is None:
                raise HTTPException(
                    status_code=404, detail= "Conversation not found."
                )

            if conversation.status == ConversationStatus.DELETED:
                raise HTTPException(
                    status_code=404, detail="Conversation not found."
                )

            token_hash = generate_token_hash(request.participant_token)

            participant = (
                db.query(Participant).filter(
                    Participant.conversation_id == conversation_id,
                    Participant.participant_token == token_hash
                ).first()
            )

            if participant is None:
                raise HTTPException(
                    status_code=401, detail="Invalid participant token."
                )

            messages = (
                db.query(Message).filter(
                    Message.conversation_id == conversation_id
                ).order_by(Message.sent_at.asc()).all()
            )

            result = []

            for msg in messages:
                decrypted_msg = _decrypt(msg.ciphertext)
                result.append(
                    MessageResponse(
                        id=msg.id,
                        participant_id=msg.participant_id,
                        message=decrypted_msg,
                        sent_at=msg.sent_at
                    )
                )

            return ChatHistoryResponse(messages=result)

    def cleanup_inactive_conversations(self):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=120)

        with db_session() as db:
            conversations = (
                db.query(Conversation).filter(
                    Conversation.status == ConversationStatus.INACTIVE,
                    Conversation.inactive_at.is_not(None),
                    Conversation.inactive_at <= cutoff
                )
            )

            deleted_count = 0

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

                conversation.status = ConversationStatus.ENDED
                db.delete(conversation)
                deleted_count += 1

            db.commit()
            return deleted_count