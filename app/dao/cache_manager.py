from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=True)
        await self._redis.ping()
        logger.info("Connected to Redis at %s", self._url)

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()

    @property
    def redis(self) -> aioredis.Redis:
        assert self._redis is not None, "CacheManager not connected"
        return self._redis

    async def get(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        await self.redis.set(key, json.dumps(value, default=str), ex=ttl)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def flush_simulation(self, sim_id: str) -> None:
        keys = []
        async for key in self.redis.scan_iter(f"sim:{sim_id}:*"):
            keys.append(key)
        if keys:
            await self.redis.delete(*keys)
