import asyncio
from contextlib import asynccontextmanager

from services.conversation import ConversationService

conversation_service = ConversationService()


async def chat_cleanup():
    while True:
        try:
            deleted = conversation_service.cleanup_inactive_conversations()
            if deleted:
                print(f"Deleted {deleted} expired connections.")

        except Exception as e:
            print(f"Chat cleanup failed {type(e).__name__}: {str(e)}")

        await asyncio.sleep(30)

@asynccontextmanager
async def chat_cleanup_lifespan(app: any):
    cleanup_task = asyncio.create_task(chat_cleanup())
    print("Running conversation cleanup...")
    try:
        yield
    finally:
        print("Stopping conversation cleanup...")
    cleanup_task.cancel()

    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    print("Stopped conversation cleanup...")