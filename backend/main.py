from fastapi import FastAPI
from datetime import datetime


from config import Configuration
from router import (
    conversation,
    websocket,
    message
)
from services.cleanup import chat_cleanup_lifespan

config = Configuration()

api = FastAPI(title="Textie Backend", docs_url="/docs", lifespan=chat_cleanup_lifespan)

# Router initialisations
api.include_router(router=conversation.router)
api.include_router(router=websocket.router)
api.include_router(router=message.router)


@api.get("/")
def home():
    return {
        "result": "success",
        "message": "Please Go To /Docs"
    }

@api.get("/health-check")
def healthcheck():
    return {
        "result": "success",
        "time": datetime.now()
    }



# Expired conversation cleanup
cleanup_task = None


