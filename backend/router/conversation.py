from fastapi import APIRouter
from uuid import UUID

from schema import (
    ConversationJoinRequest, ConversationLeaveRequest,
    ConversationJoinResponse, ConversationCreateResponse,
    ChatHistoryResponse
)
from services.conversation import ConversationService

router = APIRouter(prefix="/conversation", tags=["Conversation"])
conversation_service = ConversationService()


@router.post("/create",response_model=ConversationCreateResponse)
def create_conversation():
    return conversation_service.create_conversation()

@router.post("/join", response_model=ConversationJoinResponse)
def join_conversation(request: ConversationJoinRequest):
    return conversation_service.join_conversation(request=request)

@router.post("/{conversation_id}/leave")
def leave_conversation(request: ConversationLeaveRequest):
    return conversation_service.leave_conversation(request=request)

@router.post("/{conversation_id}/chat", response_model=ChatHistoryResponse)
def get_chat_history(conversation_id:UUID, request: ChatHistoryResponse):
    return conversation_service.get_chat_history(
        conversation_id=conversation_id, request=request
    )