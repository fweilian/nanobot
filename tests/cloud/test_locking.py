from __future__ import annotations

import pytest

from nanobot.cloud.lock import InMemoryDistributedLockManager


@pytest.mark.asyncio
async def test_in_memory_lock_manager_fast_fails_second_acquire():
    locks = InMemoryDistributedLockManager()

    first = await locks.acquire("scope", 30)
    second = await locks.acquire("scope", 30)

    assert first is not None
    assert second is None

    await locks.release("scope", first)
    third = await locks.acquire("scope", 30)
    assert third is not None
