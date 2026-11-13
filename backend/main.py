from datetime import datetime, timezone
import logging
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from clients.redis import redis_client
from config import Configuration
from database import database_pool_metrics, db_session
from router import (
    conversation,
    message,
    websocket,
)
from services.cleanup import chat_cleanup_lifespan
from services.observability import JsonLogFormatter

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonLogFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

config = Configuration()

api = FastAPI(title="Textie Backend", docs_url="/docs", lifespan=chat_cleanup_lifespan)

api.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_methods=["*"]
)


api.include_router(conversation.router)
api.include_router(websocket.router)
api.include_router(message.router)


@api.get("/")
def home():
    return {"result": "success", "message": "Please Go To /Docs"}


@api.get("/health-check")
def healthcheck():
    return {
        "result": "success",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@api.get("/health/live")
def liveness():
    return {"status": "ok"}


@api.get("/health/ready")
async def readiness():
    try:
        with db_session() as db:
            db.execute(text("SELECT 1"))
        await redis_client.ping()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="A required service is unavailable.",
        ) from exc


@api.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    counters = await redis_client.metrics_snapshot()
    active = await redis_client.active_connection_count()
    db_metrics = database_pool_metrics()
    lines = [
        "# HELP textie_websocket_active_connections Active WebSocket connection leases.",
        "# TYPE textie_websocket_active_connections gauge",
        f"textie_websocket_active_connections {active}",
    ]
    lines.extend(f"textie_{name} {value}" for name, value in counters.items())
    lines.extend([
        (
            "textie_database_pool_checked_out"
            f"{{process_id=\"{db_metrics['process_id']}\"}} "
            f"{db_metrics['checked_out']}"
        ),
        (
            "textie_database_pool_wait_seconds_total"
            f"{{process_id=\"{db_metrics['process_id']}\"}} "
            f"{db_metrics['wait_seconds_total']}"
        ),
        (
            "textie_database_pool_wait_seconds_max"
            f"{{process_id=\"{db_metrics['process_id']}\"}} "
            f"{db_metrics['wait_seconds_max']}"
        ),
        (
            "textie_redis_failures_total"
            f"{{process_id=\"{db_metrics['process_id']}\"}} "
            f"{redis_client.local_failures}"
        ),
    ])
    return "\n".join(lines) + "\n"


