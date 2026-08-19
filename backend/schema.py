from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

# Conversation operation
class ConversationJoinRequest(BaseModel):
    code: str

class ConversationLeaveRequest(BaseModel):
    conversation_id: UUID
    participant_id: UUID  

class ConversationCreateResponse(BaseModel):
    conversation_id: UUID
    code: str
    participant_id: UUID
    participant_token: str
    expires_at: datetime

class ConversationJoinResponse(BaseModel):
    conversation_id: UUID
    participant_id: UUID
    participant_token: str
    expires_at: datetime

# Message operation
class ChatHistoryRequest(BaseModel):
    participant_token: str

class MessageResponse(BaseModel):
    id: UUID
    participant_id: UUID
    message: str
    sent_at: datetime

class ChatHistoryResponse(BaseModel):
    messages: list[MessageResponse]