from __future__ import annotations

import pytest

from nanobot.cloud.browser_protocol import AuthRealmMeta
from nanobot.cloud.browser_store import InMemoryBrowserStore, find_reusable_auth_realm


@pytest.mark.asyncio
async def test_in_memory_browser_store_auth_state_round_trip():
    store = InMemoryBrowserStore()

    await store.save_auth_state("u1:corp-sso", b"secret", ttl_s=60)

    assert await store.load_auth_state("u1:corp-sso") == b"secret"


@pytest.mark.asyncio
async def test_find_reusable_auth_realm_prefers_direct_realm_id():
    store = InMemoryBrowserStore()
    meta = AuthRealmMeta(
        user_id="u1",
        auth_realm_id="u1:corp-sso",
        realm_key="corp-sso",
        domain_patterns=["*.example.com"],
    )
    await store.save_auth_realm(meta)

    found = await find_reusable_auth_realm(
        store,
        user_id="u1",
        url="https://docs.example.com",
        configured_realm="corp-sso",
    )

    assert found == meta


@pytest.mark.asyncio
async def test_find_reusable_auth_realm_matches_domain_patterns_across_sessions():
    store = InMemoryBrowserStore()
    meta = AuthRealmMeta(
        user_id="u1",
        auth_realm_id="u1:accounts.example.com",
        realm_key="accounts.example.com",
        issuer="https://accounts.example.com",
        domain_patterns=["app.example.com", "docs.example.com"],
        last_used_at="2026-04-15T01:00:00+00:00",
    )
    await store.save_auth_realm(meta)

    found = await find_reusable_auth_realm(
        store,
        user_id="u1",
        url="https://app.example.com/dashboard",
    )

    assert found == meta
