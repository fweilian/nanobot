from __future__ import annotations

from nanobot.cloud.config import RedisSettings
from nanobot.cloud.redis_client import create_redis_client, normalize_redis_url, resolve_redis_mode


def test_normalize_redis_url_percent_encodes_raw_password_at_sign() -> None:
    assert normalize_redis_url("redis://:pa@ss@redis.example:6379/0") == "redis://:pa%40ss@redis.example:6379/0"


def test_normalize_redis_url_keeps_encoded_password_and_strips_cluster_query() -> None:
    url = "rediss://user:pa%40ss@redis.example:6379/0?ssl_cert_reqs=none&cluster=true"
    assert normalize_redis_url(url) == "rediss://user:pa%40ss@redis.example:6379/0?ssl_cert_reqs=none"


def test_resolve_redis_mode_uses_explicit_setting() -> None:
    settings = RedisSettings(url="redis://redis.example:6379/0?cluster=true", mode="single")
    assert resolve_redis_mode(settings) == "single"


def test_resolve_redis_mode_detects_cluster_from_scheme_and_query() -> None:
    assert resolve_redis_mode(RedisSettings(url="redis+cluster://redis.example:6379/0", mode="auto")) == "cluster"
    assert resolve_redis_mode(RedisSettings(url="redis://redis.example:6379/0?cluster=yes", mode="auto")) == "cluster"


def test_create_redis_client_uses_single_client_with_normalized_url(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str, **kwargs):
            calls.append((url, kwargs))
            return {"kind": "single", "url": url, "kwargs": kwargs}

    class FakeRedisCluster:
        @classmethod
        def from_url(cls, url: str, **kwargs):
            raise AssertionError("cluster client should not be used")

    monkeypatch.setattr(
        "nanobot.cloud.redis_client._load_redis_classes",
        lambda: (FakeRedis, FakeRedisCluster),
    )

    client = create_redis_client(RedisSettings(url="redis://:pa@ss@redis.example:6379/0"))

    assert client["kind"] == "single"
    assert calls == [("redis://:pa%40ss@redis.example:6379/0", {"encoding": "utf-8", "decode_responses": False})]


def test_create_redis_client_uses_cluster_client_with_normalized_url(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str, **kwargs):
            raise AssertionError("single client should not be used")

    class FakeRedisCluster:
        @classmethod
        def from_url(cls, url: str, **kwargs):
            calls.append((url, kwargs))
            return {"kind": "cluster", "url": url, "kwargs": kwargs}

    monkeypatch.setattr(
        "nanobot.cloud.redis_client._load_redis_classes",
        lambda: (FakeRedis, FakeRedisCluster),
    )

    client = create_redis_client(
        RedisSettings(
            url="redis://user:pa@ss@redis.example:6379/0?cluster=true",
            mode="auto",
        )
    )

    assert client["kind"] == "cluster"
    assert calls == [("redis://user:pa%40ss@redis.example:6379/0", {"encoding": "utf-8", "decode_responses": False})]
