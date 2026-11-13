import asyncio
from collections import defaultdict
import logging
from uuid import UUID

from fastapi import WebSocket

from config import Configuration

logger = logging.getLogger(__name__)
config = Configuration()


class WebsocketManager:
    def __init__(self):
        self.connections = defaultdict(dict)

    async def connect(
        self,
        conversation_id: UUID,
        participant_id: UUID,
        websocket: WebSocket,
    ):
        room = str(conversation_id)
        participant = str(participant_id)
        message_queue = asyncio.Queue(maxsize=config.WS_SEND_QUEUE_SIZE)
        sender_task = asyncio.create_task(self._sender(websocket, message_queue))
        previous = self.connections[room].get(participant)
        if previous:
            previous[2].cancel()
            try:
                await previous[0].close(code=4409, reason="Connection replaced")
            except Exception:
                pass
        self.connections[room][participant] = (
            websocket,
            message_queue,
            sender_task,
        )

    async def _sender(self, websocket, queue):
        try:
            while True:
                payload = await queue.get()
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=config.WS_SEND_TIMEOUT_SECONDS,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await websocket.close(code=1013)
            except Exception:
                pass

    async def send_to(self, websocket, payload):
        for room in self.connections.values():
            for current, queue, _ in room.values():
                if current is websocket:
                    try:
                        queue.put_nowait(payload)
                        return True
                    except asyncio.QueueFull:
                        await websocket.close(code=1013, reason="Client cannot keep up.")
                        return False
        return False

    async def disconnect(
        self,
        conversation_id: UUID,
        participant_id: UUID,
        websocket=None,
    ):
        conversation_id = str(conversation_id)
        participant_id = str(participant_id)

        room = self.connections.get(conversation_id)
        if room is None:
            return
        current = room.get(participant_id)
        if current is None or (websocket is not None and current[0] is not websocket):
            return
        room.pop(participant_id, None)
        current[2].cancel()
        if len(room) == 0:
            self.connections.pop(conversation_id, None)

    async def broadcast_local(self, conversation_id, payload):
        room = self.connections.get(str(conversation_id), {})
        disconnected = []

        for participant_id, connection in list(room.items()):
            websocket, message_queue, _ = connection
            try:
                message_queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("WebSocket outbound queue full")
                try:
                    from clients.redis import redis_client
                    await redis_client.increment_metric("websocket_send_queue_overflow_total")
                except Exception:
                    logger.error("Could not record outbound queue overflow")
                await websocket.close(code=1013, reason="Client cannot keep up.")
                disconnected.append(participant_id)

        for participant_id in disconnected:
            current = room.pop(participant_id, None)
            if current:
                current[2].cancel()


websocket_manager = WebsocketManager()
