from __future__ import annotations

import pytest

from nanobot.cloud.skills_cache import InMemorySkillBundleStore


@pytest.mark.asyncio
async def test_in_memory_skill_bundle_store_round_trip():
    store = InMemorySkillBundleStore()
    payload = {"SKILL.md": b"# hi", "helper.sh": b"echo hi"}

    await store.put("bundle-1", payload)
    loaded = await store.get("bundle-1")

    assert loaded == payload
