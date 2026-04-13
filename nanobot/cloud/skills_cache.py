"""Skill bundle manifests, small-content cache, and staging budgets."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from loguru import logger
from pydantic import BaseModel, Field

try:
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - redis is optional at import time
    RedisError = Exception


class SkillBundleManifest(BaseModel):
    """Immutable descriptor for a materializable skill bundle."""

    skill_name: str
    source_kind: Literal["builtin", "workspace", "agent"]
    relative_target: str | None = None
    bundle_revision: str
    bundle_hash: str
    total_bytes: int
    object_list: list[str] = Field(default_factory=list)
    source: str
    hotness: int = 0
    small_content_eligible: bool = False


@dataclass(slots=True)
class PreparedSkillBundle:
    """Resolved skill bundle with local source directory."""

    manifest: SkillBundleManifest
    source_dir: Path


class SkillStageBudgetExceededError(RuntimeError):
    """Raised when skill materialization would exceed local staging budgets."""

    def __init__(
        self,
        *,
        requested_bytes: int,
        request_budget_bytes: int,
        instance_budget_bytes: int,
        current_instance_bytes: int,
    ) -> None:
        super().__init__("skill_stage_budget_exceeded")
        self.requested_bytes = requested_bytes
        self.request_budget_bytes = request_budget_bytes
        self.instance_budget_bytes = instance_budget_bytes
        self.current_instance_bytes = current_instance_bytes


class SkillBundleContentStore(Protocol):
    """Small-skill content cache abstraction."""

    async def get(self, bundle_hash: str) -> dict[str, bytes] | None: ...

    async def put(self, bundle_hash: str, files: dict[str, bytes]) -> None: ...


class InMemorySkillBundleStore:
    """In-memory content store used in tests."""

    def __init__(self):
        self._data: dict[str, dict[str, bytes]] = {}

    async def get(self, bundle_hash: str) -> dict[str, bytes] | None:
        payload = self._data.get(bundle_hash)
        if payload is None:
            return None
        return {name: bytes(content) for name, content in payload.items()}

    async def put(self, bundle_hash: str, files: dict[str, bytes]) -> None:
        self._data[bundle_hash] = {name: bytes(content) for name, content in files.items()}


class RedisSkillBundleStore:
    """Redis-backed content store for small skill bundles."""

    def __init__(self, client, *, key_prefix: str, ttl_s: int) -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")
        self._ttl_s = ttl_s
        self._fallback = InMemorySkillBundleStore()
        self._degraded = False

    def _key(self, bundle_hash: str) -> str:
        return f"{self._key_prefix}:skill-bundle:{bundle_hash}"

    def _mark_degraded(self, exc: Exception) -> None:
        if self._degraded:
            return
        self._degraded = True
        logger.warning(
            "Redis skill bundle cache unavailable; falling back to in-memory cache for this process: {}",
            exc,
        )

    async def get(self, bundle_hash: str) -> dict[str, bytes] | None:
        try:
            payload = await self._client.get(self._key(bundle_hash))
            if payload is None:
                return None
            raw = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            data = json.loads(raw)
            return {
                path: base64.b64decode(content.encode("ascii"))
                for path, content in data.items()
            }
        except (RedisError, OSError) as exc:
            self._mark_degraded(exc)
            return await self._fallback.get(bundle_hash)

    async def put(self, bundle_hash: str, files: dict[str, bytes]) -> None:
        try:
            data = {
                path: base64.b64encode(content).decode("ascii")
                for path, content in files.items()
            }
            await self._client.set(
                self._key(bundle_hash),
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                ex=self._ttl_s,
            )
        except (RedisError, OSError) as exc:
            self._mark_degraded(exc)
            await self._fallback.put(bundle_hash, files)


class SkillStageBudgetManager:
    """Per-instance skill staging budget manager."""

    def __init__(self, *, request_budget_bytes: int, instance_budget_bytes: int) -> None:
        self.request_budget_bytes = request_budget_bytes
        self.instance_budget_bytes = instance_budget_bytes
        self._current_instance_bytes = 0
        self._lock = asyncio.Lock()

    async def acquire(self, requested_bytes: int) -> None:
        async with self._lock:
            if requested_bytes > self.request_budget_bytes:
                raise SkillStageBudgetExceededError(
                    requested_bytes=requested_bytes,
                    request_budget_bytes=self.request_budget_bytes,
                    instance_budget_bytes=self.instance_budget_bytes,
                    current_instance_bytes=self._current_instance_bytes,
                )
            if self._current_instance_bytes + requested_bytes > self.instance_budget_bytes:
                raise SkillStageBudgetExceededError(
                    requested_bytes=requested_bytes,
                    request_budget_bytes=self.request_budget_bytes,
                    instance_budget_bytes=self.instance_budget_bytes,
                    current_instance_bytes=self._current_instance_bytes,
                )
            self._current_instance_bytes += requested_bytes

    async def release(self, released_bytes: int) -> None:
        async with self._lock:
            self._current_instance_bytes = max(0, self._current_instance_bytes - released_bytes)

    @property
    def current_instance_bytes(self) -> int:
        return self._current_instance_bytes


def collect_bundle_files(source_dir: Path) -> dict[str, bytes]:
    """Read all files in a skill directory into a relative-path map."""
    files: dict[str, bytes] = {}
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        files[path.relative_to(source_dir).as_posix()] = path.read_bytes()
    return files


def build_skill_bundle(
    *,
    skill_name: str,
    source_dir: Path,
    source_kind: Literal["builtin", "workspace", "agent"],
    source: str,
    relative_target: str | None,
    small_skill_max_bytes: int,
) -> PreparedSkillBundle:
    """Build an immutable bundle manifest from a local skill directory."""
    files = collect_bundle_files(source_dir)
    hasher = hashlib.sha256()
    total_bytes = 0
    object_list: list[str] = []
    for rel_path, content in files.items():
        object_list.append(rel_path)
        total_bytes += len(content)
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content)
        hasher.update(b"\0")
    bundle_hash = hasher.hexdigest()
    manifest = SkillBundleManifest(
        skill_name=skill_name,
        source_kind=source_kind,
        relative_target=relative_target,
        bundle_revision=bundle_hash,
        bundle_hash=bundle_hash,
        total_bytes=total_bytes,
        object_list=object_list,
        source=source,
        small_content_eligible=total_bytes <= small_skill_max_bytes,
    )
    return PreparedSkillBundle(manifest=manifest, source_dir=source_dir)


async def load_or_populate_bundle_content(
    bundle: PreparedSkillBundle,
    store: SkillBundleContentStore,
) -> dict[str, bytes] | None:
    """Return cached bundle content for small bundles, populating cache on miss."""
    if not bundle.manifest.small_content_eligible:
        return None
    payload = await store.get(bundle.manifest.bundle_hash)
    if payload is not None:
        return payload
    payload = collect_bundle_files(bundle.source_dir)
    await store.put(bundle.manifest.bundle_hash, payload)
    return payload
