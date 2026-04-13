"""Redis client construction helpers for cloud mode."""

from __future__ import annotations

import importlib
from typing import Literal
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from nanobot.cloud.config import RedisSettings

RedisMode = Literal["single", "cluster"]
_CLUSTER_QUERY_VALUES = {"1", "true", "yes", "on"}
_CLUSTER_SCHEME_MAP = {
    "redis+cluster": "redis",
    "rediss+cluster": "rediss",
}


def _format_hostname(hostname: str) -> str:
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]"
    return hostname


def normalize_redis_url(url: str) -> str:
    """Return a Redis URL with safely encoded credentials and normalized scheme."""
    parts = urlsplit(url)
    scheme = _CLUSTER_SCHEME_MAP.get(parts.scheme, parts.scheme)
    query_items = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "cluster"]
    query = urlencode(query_items, doseq=True)

    if parts.scheme == "unix" or parts.hostname is None:
        return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))

    username = parts.username
    password = parts.password
    auth = ""
    if username is not None:
        auth = quote(unquote(username), safe="")
        if password is not None:
            auth += f":{quote(unquote(password), safe='')}"
        auth += "@"
    elif password is not None:
        auth = f":{quote(unquote(password), safe='')}@"

    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{auth}{_format_hostname(parts.hostname)}{port}"
    return urlunsplit((scheme, netloc, parts.path, query, parts.fragment))


def resolve_redis_mode(settings: RedisSettings) -> RedisMode:
    """Resolve the effective Redis client mode for the current settings."""
    if settings.mode != "auto":
        return settings.mode

    parts = urlsplit(settings.url)
    if parts.scheme in _CLUSTER_SCHEME_MAP:
        return "cluster"

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == "cluster" and value.lower() in _CLUSTER_QUERY_VALUES:
            return "cluster"
    return "single"


def _load_redis_classes():
    redis_asyncio = importlib.import_module("redis.asyncio")
    redis_cls = getattr(redis_asyncio, "Redis")

    try:
        redis_cluster_module = importlib.import_module("redis.asyncio.cluster")
        redis_cluster_cls = getattr(redis_cluster_module, "RedisCluster")
    except Exception:  # pragma: no cover - exercised in environments without cluster support
        redis_cluster_cls = None
    return redis_cls, redis_cluster_cls


def create_redis_client(settings: RedisSettings):
    """Create a single-node or cluster Redis client from cloud settings."""
    mode = resolve_redis_mode(settings)
    url = normalize_redis_url(settings.url)
    redis_cls, redis_cluster_cls = _load_redis_classes()

    if mode == "cluster":
        if redis_cluster_cls is None:
            raise RuntimeError("Redis cluster mode requires redis-py cluster support")
        return redis_cluster_cls.from_url(url, encoding="utf-8", decode_responses=False)
    return redis_cls.from_url(url, encoding="utf-8", decode_responses=False)
