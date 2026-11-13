import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from clients.redis import redis_client
from clients.websocket import websocket_manager
from services.conversation import ConversationService

logger = logging.getLogger(__name__)
conversation_service = ConversationService()


async def chat_cleanup():
    while True:
        try:
            deleted = await run_in_threadpool(
                conversation_service.cleanup_inactive_conversations
            )
            if deleted:
                logger.info("Deleted %s expired conversations", deleted)

        except Exception:
            logger.error("Conversation cleanup failed")

        await asyncio.sleep(30)

@asynccontextmanager
async def chat_cleanup_lifespan(_app: FastAPI):
    await redis_client.connect()
    pubsub = await redis_client.subscribe_to_conversation_events()
    pubsub_task = asyncio.create_task(
        redis_client.listen_for_conversation_events(
            pubsub,
            websocket_manager.broadcast_local,
        )
    )
    cleanup_task = asyncio.create_task(chat_cleanup())
    logger.info("Conversation cleanup and Redis event listener started")
    try:
        yield
    finally:
        cleanup_task.cancel()
        pubsub_task.cancel()
        await asyncio.gather(cleanup_task, pubsub_task, return_exceptions=True)
        await redis_client.close_pubsub(pubsub)
        await redis_client.close()
        logger.info("Conversation cleanup and Redis event listener stopped")
