from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from sqlalchemy import (
    BigInteger, DateTime, Enum as SqlEnum, String, UUID, Column,
    ForeignKey, LargeBinary, Boolean, UniqueConstraint
)
from sqlalchemy.orm import (
    relationship
)

from database import Base


class ConversationStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ENDED = "ENDED"
    DELETED = "DELETED"

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(6), unique=True, index=True, nullable=False)
    owner_token_hash = Column(String(64), nullable=False)
    status = Column(SqlEnum(ConversationStatus), default=ConversationStatus.WAITING, nullable=False)
    inactive_at = Column(DateTime(timezone=True), nullable=True)
    last_message_sequence = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    participants = relationship("Participant", back_populates="conversation", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"

    id  = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False
    )
    participant_token = Column(String(255), nullable=False, unique=True)
    is_owner = Column(Boolean, nullable=False, default=False)
    left_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="participants")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        UniqueConstraint("participant_id", "client_message_id", name="uq_messages_participant_client_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ciphertext = Column(LargeBinary, nullable=False)
    sequence = Column(BigInteger, nullable=False)
    client_message_id = Column(UUID(as_uuid=True), nullable=True)
    # nonce = Column(LargeBinary, nullable=False)
    sent_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    conversation = relationship("Conversation",back_populates="messages",)
    participant = relationship("Participant")
