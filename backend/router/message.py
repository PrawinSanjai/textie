from uuid import UUID

from fastapi import APIRouter

from schema import ChatHistoryRequest, ChatHistoryResponse
from services.conversation import ConversationService

router = APIRouter(prefix="/message", tags=["Messages"])
conversation_service = ConversationService()


@router.post("/{conversation_id}/messages", response_model=ChatHistoryResponse)
def get_messages(conversation_id: UUID, request: ChatHistoryRequest):
    return conversation_service.get_chat_history(conversation_id, request)
