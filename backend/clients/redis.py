import json
import redis.asyncio as redis

from config import Configuration

config = Configuration()
config.validate()


class RedisClient:

    def __init__(self):
        self.client = redis.from_url(config.REDIS_URL, decode_responses=True)

    async def redis_publish(self, channel: str, payload: dict):
        await self.client.publish(channel=channel, message=json.dumps(payload))

    async def redis_subscribe(self, channel: str):
        pub_sub = self.client.pubsub()
        await pub_sub.subscribe(channel)
        return pub_sub

    async def redis_close(self):
        await self.client.close()