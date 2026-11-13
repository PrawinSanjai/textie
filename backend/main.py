import logging
import sys
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone


from config import Configuration
from router import (
    conversation,
    websocket,
    message
)
from services.cleanup import chat_cleanup_lifespan
from clients.redis import redis_client
from database import db_session, database_pool_metrics
from sqlalchemy import text
from services.observability import JsonLogFormatter

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonLogFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

config = Configuration()

api = FastAPI(title="Textie Backend", docs_url="/docs", lifespan=chat_cleanup_lifespan)

# FastAPI CORS
api.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_headers=["*"],
    allow_origins=config.CORS_ALLOWED_ORIGINS,
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

@api.get("/health/live")
def liveness():
    return {"status": "ok"}

@api.get("/health/ready")
async def readiness():
    try:
        with db_session() as db:
            db.execute(text("SELECT 1"))
        await redis_client.client.ping()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="A required service is unavailable.") from exc

@api.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    counters = await redis_client.metrics_snapshot()
    active = await redis_client.active_connection_count()
    db_metrics = database_pool_metrics()
    lines = ["# HELP textie_websocket_active_connections Active WebSocket connection leases.", "# TYPE textie_websocket_active_connections gauge", f"textie_websocket_active_connections {active}"]
    lines.extend(f"textie_{name} {value}" for name, value in counters.items())
    lines.extend([
        f"textie_database_pool_checked_out{{process_id=\"{db_metrics['process_id']}\"}} {db_metrics['checked_out']}",
        f"textie_database_pool_wait_seconds_total{{process_id=\"{db_metrics['process_id']}\"}} {db_metrics['wait_seconds_total']}",
        f"textie_database_pool_wait_seconds_max{{process_id=\"{db_metrics['process_id']}\"}} {db_metrics['wait_seconds_max']}",
        f"textie_redis_failures_total{{process_id=\"{db_metrics['process_id']}\"}} {redis_client.local_failures}",
    ])
    return "\n".join(lines) + "\n"


