from uuid import UUID
from fastapi import APIRouter, WebSocket

from services.websocket import WebsocketService

router = APIRouter(prefix="/ws", tags=["Websocket Connection"])
websocket_service = WebsocketService()

@router.websocket("/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: UUID):
   await websocket_service.handle_ws_connection(
      websocket=websocket,
      conversation_id=conversation_id
   )