import hashlib
import math

from fastapi import HTTPException, Request

from clients.redis import redis_client
from config import Configuration

config = Configuration()


async def limit_conversation_creation(request: Request):
    client_host = request.client.host if request.client else "unknown"
    client_key = hashlib.sha256(client_host.encode("utf-8")).hexdigest()
    key = f"textie:rate:create:{client_key}"

    allowed, retry_after_ms = await redis_client.allow_request(
        key=key,
        limit=config.CREATE_CHAT_RATE_LIMIT,
        window_seconds=config.CREATE_CHAT_RATE_WINDOW_SECONDS,
    )

    if not allowed:
        retry_after = max(1, math.ceil(retry_after_ms / 1000))
        await redis_client.increment_metric("room_create_rate_limit_rejections_total")
        raise HTTPException(
            status_code=429,
            detail="Too many rooms created. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def limit_conversation_join(request: Request):
    client_host = request.client.host if request.client else "unknown"
    client_key = hashlib.sha256(client_host.encode("utf-8")).hexdigest()
    allowed, retry_after_ms = await redis_client.allow_request(
        f"textie:rate:join:{client_key}",
        config.JOIN_RATE_LIMIT,
        config.JOIN_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        retry_after = max(1, math.ceil(retry_after_ms / 1000))
        await redis_client.increment_metric("join_rate_limit_rejections_total")
        raise HTTPException(
            status_code=429,
            detail="Too many join attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
