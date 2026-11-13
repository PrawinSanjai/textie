from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

# Conversation operation
class ConversationJoinRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")

class ConversationLeaveRequest(BaseModel):
    participant_id: UUID
    participant_token: str = Field(min_length=1, max_length=255)

class ConversationCreateResponse(BaseModel):
    conversation_id: UUID
    code: str
    participant_id: UUID
    participant_token: str
    expires_at: datetime

class ConversationJoinResponse(BaseModel):
    conversation_id: UUID
    code: str
    participant_id: UUID
    participant_token: str
    expires_at: datetime

class ConversationLeaveResponse(BaseModel):
    conversation_id: UUID
    participant_id: UUID
    status: str

# Message operation
class ChatHistoryRequest(BaseModel):
    participant_token: str = Field(min_length=1, max_length=255)
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=500)

class MessageResponse(BaseModel):
    id: UUID
    participant_id: UUID
    sequence: int
    message: str
    sent_at: datetime

class ChatHistoryResponse(BaseModel):
    messages: list[MessageResponse]
    next_after_sequence: int
