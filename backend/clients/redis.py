import asyncio
import base64
import json
import logging
import time

import redis.asyncio as redis
from redis.exceptions import WatchError

from config import Configuration
from services.crypto import _decrypt

config = Configuration()
config.validate()
logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        self.local_failures = 0
        self._client = redis.from_url(
            config.REDIS_URL,
            decode_responses=True,
            max_connections=config.REDIS_MAX_CONNECTIONS,
            health_check_interval=30,
        )

    def record_local_failure(self):
        self.local_failures += 1

    async def connect(self):
        await self._client.ping()

    async def allow_request(self, key, limit, window_seconds):
        count = await self._client.incr(key)
        if count == 1:
            await self._client.expire(key, window_seconds)
        ttl = await self._client.ttl(key)
        return count <= limit, max(0, ttl) * 1000

    async def ping(self):
        return await self._client.ping()

    def _presence_keys(self, conversation_id, participant_id):
        participant_key = f"textie:presence:conversation:{conversation_id}:participant:{participant_id}"
        room_key = f"textie:presence:conversation:{conversation_id}:participants"
        active_key = "textie:presence:active_connections"
        return participant_key, room_key, active_key

    async def register_presence(self, conversation_id, participant_id, connection_id, ttl):
        participant_key, room_key, active_key = self._presence_keys(conversation_id, participant_id)
        while True:
            try:
                # WATCH prevents a stale socket from replacing a newer lease.
                async with self._client.pipeline(transaction=True) as pipe:
                    await pipe.watch(participant_key)
                    was_online = await pipe.get(participant_key) is not None
                    pipe.multi()
                    pipe.set(participant_key, connection_id, ex=ttl)
                    pipe.sadd(room_key, participant_id)
                    pipe.zadd(active_key, {connection_id: time.time() + ttl})
                    pipe.expire(active_key, ttl * 2)
                    await pipe.execute()
                return not was_online
            except WatchError:
                continue

    async def refresh_presence(self, conversation_id, participant_id, connection_id, ttl):
        participant_key, _, active_key = self._presence_keys(conversation_id, participant_id)
        while True:
            try:
                async with self._client.pipeline(transaction=True) as pipe:
                    await pipe.watch(participant_key)
                    if await pipe.get(participant_key) != connection_id:
                        return False
                    pipe.multi()
                    pipe.expire(participant_key, ttl)
                    pipe.zadd(active_key, {connection_id: time.time() + ttl})
                    pipe.expire(active_key, ttl * 2)
                    await pipe.execute()
                return True
            except WatchError:
                continue

    async def remove_presence(self, conversation_id, participant_id, connection_id):
        participant_key, room_key, active_key = self._presence_keys(conversation_id, participant_id)
        while True:
            try:
                async with self._client.pipeline(transaction=True) as pipe:
                    await pipe.watch(participant_key)
                    if await pipe.get(participant_key) != connection_id:
                        return False
                    pipe.multi()
                    pipe.delete(participant_key)
                    pipe.srem(room_key, participant_id)
                    pipe.zrem(active_key, connection_id)
                    await pipe.execute()
                return True
            except WatchError:
                continue

    async def list_presence(self, conversation_id):
        room_key = f"textie:presence:conversation:{conversation_id}:participants"
        members = await self._client.smembers(room_key)
        online = []
        for participant_id in members:
            participant_key = f"textie:presence:conversation:{conversation_id}:participant:{participant_id}"
            if await self._client.exists(participant_key):
                online.append(participant_id)
            else:
                await self._client.srem(room_key, participant_id)
        return online

    async def active_connection_count(self):
        key = "textie:presence:active_connections"
        await self._client.zremrangebyscore(key, "-inf", time.time())
        return await self._client.zcard(key)

    async def increment_metric(self, name, amount=1):
        await self._client.hincrby("textie:metrics", name, amount)

    async def metrics_snapshot(self):
        return await self._client.hgetall("textie:metrics")

    async def publish_conversation_event(self, conversation_id, payload):
        channel = f"textie:conversation:{conversation_id}"
        await self._client.publish(channel, json.dumps(payload))

    async def subscribe_to_conversation_events(self):
        pubsub = self._client.pubsub()
        await pubsub.psubscribe("textie:conversation:*")
        return pubsub

    async def listen_for_conversation_events(self, pubsub, callback):
        retry_delay = 1
        while True:
            try:
                async for event in pubsub.listen():
                    if event.get("type") != "pmessage":
                        continue
                    try:
                        conversation_id = event["channel"].rsplit(":", 1)[1]
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
    def restore_event_payload(payload):
        if payload.get("type") == "message":
            ciphertext = base64.b64decode(payload.pop("ciphertext"), validate=True)
            payload["message"] = _decrypt(ciphertext)

    async def close_pubsub(self, pubsub):
        await pubsub.aclose()

    async def close(self):
        await self._client.aclose()


redis_client = RedisClient()
