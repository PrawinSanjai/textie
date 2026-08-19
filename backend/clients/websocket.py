from collections import defaultdict
from uuid import UUID
from fastapi import WebSocket


class WebsocketManager:

    def __init__(self):
        self.connections = defaultdict(dict)

    async def connect(self, conversation_id: UUID, participant_id: UUID, websocket: WebSocket):
        await websocket.accept()
        self.connections[str(conversation_id)][str(participant_id)] = websocket
        print(
            f"WebSocket registered: "
            f"{participant_id}"
        )

    def disconnect(self, conversation_id: UUID, participant_id: UUID):
        conversation_id = str(conversation_id)
        participant_id = str(participant_id)

        room = self.connections.get(str(conversation_id))
        if room is None:
            return
        room.pop(participant_id, None)
        if len(room) == 0:
            self.connections.pop(conversation_id, None)
    
    async def broadcast(self, conversation_id: UUID, payload: dict):
        room = self.connections.get(str(conversation_id), {})
        disconnected = []
        print(
            f"Broadcasting to "
            f"{len(room)} participant(s)"
        )

        for participant_id, websocket in room.items():
            try:
                await websocket.send_json(payload)
                print(
                    f"Sent to {participant_id}"
                )
            except Exception as e:
                print(
                    f"Failed to send to "
                    f"{participant_id}: "
                    f"{e}"
                )
                disconnected.append(participant_id)
        
        for participant_id in disconnected:
            room.pop(participant_id, None)