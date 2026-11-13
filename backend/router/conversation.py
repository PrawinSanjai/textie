from fastapi import APIRouter, Depends
from uuid import UUID

from schema import (
    ConversationJoinRequest, ConversationLeaveRequest,
    ConversationJoinResponse, ConversationCreateResponse,
    ConversationLeaveResponse, ChatHistoryRequest, ChatHistoryResponse
)
from services.conversation import ConversationService
from dependencies.rate_limit import limit_conversation_creation, limit_conversation_join

router = APIRouter(prefix="/conversation", tags=["Conversation"])
conversation_service = ConversationService()


@router.post(
    "/create",
    response_model=ConversationCreateResponse,
    dependencies=[Depends(limit_conversation_creation)],
)
def create_conversation():
    return conversation_service.create_conversation()

@router.post("/join", response_model=ConversationJoinResponse, dependencies=[Depends(limit_conversation_join)])
def join_conversation(request: ConversationJoinRequest):
    return conversation_service.join_conversation(request=request)

@router.post("/{conversation_id}/leave", response_model=ConversationLeaveResponse)
def leave_conversation(conversation_id: UUID, request: ConversationLeaveRequest):
    return conversation_service.leave_conversation(
        conversation_id=conversation_id,
        request=request
    )

@router.post("/{conversation_id}/chat", response_model=ChatHistoryResponse)
def get_chat_history(conversation_id: UUID, request: ChatHistoryRequest):
    return conversation_service.get_chat_history(
        conversation_id=conversation_id,
        request=request
    )
