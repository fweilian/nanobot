"""Normalize cloud session payloads before persisting online sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PATH_KEYS = {"path", "working_dir", "workingDir", "cwd"}


def sanitize_session_payload_for_persist(payload: bytes, runtime_dir: Path) -> bytes:
    """Rewrite runtime-scoped absolute paths in a session payload to relative paths."""
    runtime_root = runtime_dir.resolve()
    sanitized_lines: list[str] = []

    for raw_line in payload.decode("utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError:
            return payload
        sanitized = _sanitize_value(data, runtime_root=runtime_root)
        sanitized_lines.append(json.dumps(sanitized, ensure_ascii=False))

    suffix = b"\n" if payload.endswith(b"\n") and sanitized_lines else b""
    return ("\n".join(sanitized_lines)).encode("utf-8") + suffix


def _sanitize_value(value: Any, *, runtime_root: Path, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            name: _sanitize_value(item, runtime_root=runtime_root, key=name)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, runtime_root=runtime_root, key=key) for item in value]
    if not isinstance(value, str):
        return value

    if key in _PATH_KEYS:
        rewritten_path = _rewrite_path_value(value, runtime_root)
        if rewritten_path is not None:
            return rewritten_path

    if key == "arguments":
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _replace_runtime_prefixes(value, runtime_root)
        sanitized = _sanitize_value(parsed, runtime_root=runtime_root)
        return json.dumps(sanitized, ensure_ascii=False)

    return _replace_runtime_prefixes(value, runtime_root)


def _rewrite_path_value(value: str, runtime_root: Path) -> str | None:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        relative = resolved.relative_to(runtime_root)
    except ValueError:
        return None
    return "." if not relative.parts else relative.as_posix()


def _replace_runtime_prefixes(text: str, runtime_root: Path) -> str:
    replacements: list[tuple[str, str]] = []
    runtime_native = str(runtime_root)
    replacements.append((runtime_native, "."))
    runtime_posix = runtime_root.as_posix()
    if runtime_posix != runtime_native:
        replacements.append((runtime_posix, "."))

    updated = text
    for prefix, root_token in replacements:
        updated = updated.replace(prefix + "/", "")
        updated = updated.replace(prefix + "\\", "")
        updated = updated.replace(prefix, root_token)
    return updated
