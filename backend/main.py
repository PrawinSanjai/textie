from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone


from config import Configuration
from router import (
    conversation,
    websocket,
    message
)
from services.cleanup import chat_cleanup_lifespan

config = Configuration()

api = FastAPI(title="Textie Backend", docs_url="/docs", lifespan=chat_cleanup_lifespan)

# FastAPI CORS
api.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173"
    ],
    allow_methods=["*"]
)

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
        "time": datetime.now(timezone.utc).isoformat()
    }


