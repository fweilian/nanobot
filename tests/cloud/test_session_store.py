from __future__ import annotations

import pytest

from nanobot.cloud.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_in_memory_session_store_round_trip():
    store = InMemorySessionStore()

    await store.save("s1", b"hello")
    assert await store.load("s1") == b"hello"

    await store.delete("s1")
    assert await store.load("s1") is None
