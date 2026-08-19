from uuid import UUID
from fastapi import APIRouter, Query

from schema import MessageResponse
from services.message import MessageService

router = APIRouter(prefix="/message", tags=["Messages"])
message_service = MessageService()

@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
def get_messages(conversation_id: UUID, participant_id: UUID, token: str):
    return message_service.get_message(
        conversation_id=conversation_id,
        participant_id=participant_id,
        token=token
    )