import asyncio
import base64
import json
import logging

import redis.asyncio as redis

from config import Configuration
from services.crypto import _decrypt

config = Configuration()
config.validate()
logger = logging.getLogger(__name__)

RATE_LIMIT_SCRIPT = """
local redis_time = redis.call('TIME')
local now = redis_time[1] * 1000 + math.floor(redis_time[2] / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(1, tonumber(oldest[2]) + window - now)}
end
local sequence = redis.call('INCR', KEYS[2])
redis.call('ZADD', KEYS[1], now, tostring(now) .. ':' .. tostring(sequence))
redis.call('PEXPIRE', KEYS[1], window)
redis.call('PEXPIRE', KEYS[2], window)
return {1, 0}
"""


class RedisClient:
    def __init__(self):
        self.local_failures = 0
        self.client = redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
            max_connections=config.REDIS_MAX_CONNECTIONS,
            health_check_interval=30,
        )

    def record_local_failure(self):
        self.local_failures += 1

    async def connect(self):
        await self.client.ping()

    async def consume_creation_token(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        allowed, retry_after_ms = await self.client.eval(
            RATE_LIMIT_SCRIPT,
            2,
            key,
            f"{key}:sequence",
            window_seconds * 1000,
            limit,
        )
        return bool(allowed), int(retry_after_ms)

    async def consume_rate_limit(self, key: str, limit: int, window_seconds: int):
        return await self.consume_creation_token(key, limit, window_seconds)

    async def register_presence(self, conversation_id, participant_id, connection_id, ttl):
        key = f"textie:presence:conversation:{conversation_id}:participant:{participant_id}"
        room = f"textie:presence:conversation:{conversation_id}:participants"
        active = "textie:presence:active_connections"
        script = """
        local prior = redis.call('GET', KEYS[1])
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        redis.call('SADD', KEYS[2], ARGV[3])
        redis.call('ZADD', KEYS[3], ARGV[4], ARGV[1])
        redis.call('EXPIRE', KEYS[3], ARGV[2] * 2)
        if prior then return 0 else return 1 end
        """
        return bool(await self.client.eval(script, 3, key, room, active, connection_id, ttl, participant_id, __import__('time').time() + ttl))

    async def refresh_presence(self, conversation_id, participant_id, connection_id, ttl):
        key = f"textie:presence:conversation:{conversation_id}:participant:{participant_id}"
        active = "textie:presence:active_connections"
        script = """
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        redis.call('ZADD', KEYS[2], ARGV[3], ARGV[1])
        redis.call('EXPIRE', KEYS[2], ARGV[2] * 2)
        return 1
        """
        return bool(await self.client.eval(script, 2, key, active, connection_id, ttl, __import__('time').time() + ttl))

    async def remove_presence(self, conversation_id, participant_id, connection_id):
        key = f"textie:presence:conversation:{conversation_id}:participant:{participant_id}"
        room = f"textie:presence:conversation:{conversation_id}:participants"
        active = "textie:presence:active_connections"
        script = """
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
        redis.call('DEL', KEYS[1]); redis.call('SREM', KEYS[2], ARGV[2]); redis.call('ZREM', KEYS[3], ARGV[1])
        return 1
        """
        return bool(await self.client.eval(script, 3, key, room, active, connection_id, participant_id))

    async def list_presence(self, conversation_id):
        room = f"textie:presence:conversation:{conversation_id}:participants"
        script = "local out={}; for _,p in ipairs(redis.call('SMEMBERS',KEYS[1])) do if redis.call('EXISTS',ARGV[1]..p)==1 then table.insert(out,p) else redis.call('SREM',KEYS[1],p) end end; return out"
        return await self.client.eval(script, 1, room, f"textie:presence:conversation:{conversation_id}:participant:")

    async def active_connection_count(self):
        key = "textie:presence:active_connections"
        now = __import__('time').time()
        await self.client.zremrangebyscore(key, "-inf", now)
        return await self.client.zcard(key)

    async def increment_metric(self, name: str, amount: int = 1):
        await self.client.hincrby("textie:metrics", name, amount)

    async def metrics_snapshot(self):
        return await self.client.hgetall("textie:metrics")

    async def publish_conversation_event(self, conversation_id, payload: dict):
        channel = f"textie:conversation:{conversation_id}"
        await self.client.publish(channel, json.dumps(payload))

    async def subscribe_to_conversation_events(self):
        pubsub = self.client.pubsub()
        await pubsub.psubscribe("textie:conversation:*")
        return pubsub

    async def listen_for_conversation_events(self, pubsub, callback):
        retry_delay = 1
        while True:
            try:
                async for event in pubsub.listen():
                    if event.get("type") != "pmessage":
                        continue

                    channel = event.get("channel", "")
                    try:
                        conversation_id = channel.rsplit(":", 1)[1]
                        payload = json.loads(event["data"])
                        self.restore_event_payload(payload)
                        await callback(conversation_id, payload)
                    except (IndexError, KeyError, TypeError, ValueError):
                        logger.warning("Ignoring malformed conversation event")
                raise ConnectionError("Redis Pub/Sub stream ended")
            except asyncio.CancelledError:
                raise
            except Exception:
                self.record_local_failure()
                logger.error("Redis Pub/Sub listener failed; reconnecting")
                try:
                    await self.increment_metric("redis_pubsub_reconnects_total")
                except Exception:
                    logger.error("Could not record Redis listener reconnect")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 15)
                try:
                    await pubsub.punsubscribe("textie:conversation:*")
                    await pubsub.psubscribe("textie:conversation:*")
                except Exception:
                    logger.error("Redis Pub/Sub resubscribe failed")

    @staticmethod
    def restore_event_payload(payload: dict):
        if payload.get("type") == "message":
            encrypted = base64.b64decode(payload.pop("ciphertext"), validate=True)
            payload["message"] = _decrypt(encrypted)

    async def close_pubsub(self, pubsub):
        await pubsub.aclose()

    async def close(self):
        await self.client.aclose()


redis_client = RedisClient()
