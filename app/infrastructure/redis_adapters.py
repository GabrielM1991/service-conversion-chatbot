from __future__ import annotations

import hashlib

from redis.asyncio import Redis


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RedisDeduplicationStore:
    def __init__(self, client: Redis, ttl_seconds: int = 86400) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def mark_if_new(self, tenant_id: str, message_id: str) -> bool:
        key = f"dedupe:{tenant_id}:{_digest(message_id)}"
        created = await self._client.set(key, "1", ex=self._ttl_seconds, nx=True)
        return bool(created)


class RedisOptOutStore:
    def __init__(self, client: Redis) -> None:
        self._client = client

    def _key(self, tenant_id: str, phone: str) -> str:
        return f"optout:{tenant_id}:{_digest(phone)}"

    async def is_opted_out(self, tenant_id: str, phone: str) -> bool:
        return bool(await self._client.exists(self._key(tenant_id, phone)))

    async def opt_out(self, tenant_id: str, phone: str) -> None:
        await self._client.set(self._key(tenant_id, phone), "1")
