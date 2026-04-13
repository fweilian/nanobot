from __future__ import annotations

import pytest

from nanobot.cloud.lock import RedisDistributedLockManager
from nanobot.cloud.session_store import RedisSessionStore
from nanobot.cloud.skills_cache import RedisSkillBundleStore


class FailingRedisClient:
    async def get(self, *args, **kwargs):
        raise ConnectionRefusedError("redis down")

    async def set(self, *args, **kwargs):
        raise ConnectionRefusedError("redis down")

    async def delete(self, *args, **kwargs):
        raise ConnectionRefusedError("redis down")

    async def eval(self, *args, **kwargs):
        raise ConnectionRefusedError("redis down")


@pytest.mark.asyncio
async def test_redis_session_store_falls_back_to_memory():
    store = RedisSessionStore(FailingRedisClient(), key_prefix="test", ttl_s=60)

    await store.save("session-1", b"hello")
    assert await store.load("session-1") == b"hello"
    await store.delete("session-1")
    assert await store.load("session-1") is None


@pytest.mark.asyncio
async def test_redis_lock_manager_falls_back_to_memory():
    manager = RedisDistributedLockManager(FailingRedisClient(), key_prefix="test")

    token = await manager.acquire("scope-1", 30)
    assert token is not None
    assert await manager.acquire("scope-1", 30) is None
    await manager.release("scope-1", token)
    assert await manager.acquire("scope-1", 30) is not None


@pytest.mark.asyncio
async def test_redis_skill_bundle_store_falls_back_to_memory():
    store = RedisSkillBundleStore(FailingRedisClient(), key_prefix="test", ttl_s=60)

    await store.put("bundle-1", {"SKILL.md": b"# skill"})
    payload = await store.get("bundle-1")
    assert payload == {"SKILL.md": b"# skill"}
