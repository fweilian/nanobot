"""Durable session catalog helpers for cloud WebUI sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.cloud.config import utc_now_iso
from nanobot.cloud.session_store import session_filename
from nanobot.session.manager import SessionManager


MANIFEST_RELATIVE_PATH = Path("sessions") / "index.json"
DEFAULT_SESSION_TITLE = "新对话"


@dataclass(slots=True)
class SessionSummary:
    id: str
    agent_id: str
    title: str
    created_at: str
    updated_at: str

    def to_dto(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agentId": self.agent_id,
            "title": self.title,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(slots=True)
class SessionDetail(SessionSummary):
    messages: list[dict[str, Any]]

    def to_dto(self) -> dict[str, Any]:
        payload = SessionSummary.to_dto(self)
        payload["messages"] = self.messages
        return payload


def session_key(user_id: str, agent_name: str, session_id: str) -> str:
    return f"cloud:{user_id}:{agent_name}:{session_id}"


def session_file_relative_path(user_id: str, agent_name: str, session_id: str) -> Path:
    return Path("sessions") / session_filename(session_key(user_id, agent_name, session_id))


def _now_ms_from_iso(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return 0


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif "text" in block:
                parts.append(str(block["text"]))
        return "\n".join(part for part in parts if part).strip()
    return ""


def _truncate_title(text: str) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return DEFAULT_SESSION_TITLE
    return text[:20] + ("..." if len(text) > 20 else "")


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    function_payload = tool_call.get("function")
    if isinstance(function_payload, dict):
        name = function_payload.get("name")
        if isinstance(name, str) and name:
            return name
    name = tool_call.get("name")
    return str(name or "tool")


def _tool_call_args(tool_call: dict[str, Any]) -> str | None:
    function_payload = tool_call.get("function")
    if isinstance(function_payload, dict):
        arguments = function_payload.get("arguments")
        if isinstance(arguments, str):
            return arguments
        if arguments is not None:
            return json.dumps(arguments, ensure_ascii=False)
    arguments = tool_call.get("arguments")
    if isinstance(arguments, str):
        return arguments
    if arguments is not None:
        return json.dumps(arguments, ensure_ascii=False)
    return None


def session_messages_to_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    assistant_blocks_by_tool_id: dict[str, dict[str, Any]] = {}

    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        created_at = _now_ms_from_iso(str(message.get("timestamp") or ""))
        message_id = f"hist-{index}"

        if role == "user":
            rendered.append(
                {
                    "id": message_id,
                    "role": "user",
                    "blocks": [
                        {
                            "id": f"{message_id}:markdown",
                            "type": "markdown",
                            "content": _message_text(message),
                            "sequence": 0,
                        }
                    ],
                    "createdAt": created_at,
                }
            )
            continue

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = _message_text(message)
            if text:
                blocks.append(
                    {
                        "id": f"{message_id}:markdown",
                        "type": "markdown",
                        "content": text,
                        "sequence": 0,
                    }
                )
            tool_calls = message.get("tool_calls") or []
            for sequence, tool_call in enumerate(tool_calls, start=len(blocks)):
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = str(tool_call.get("id") or f"{message_id}:tool:{sequence}")
                block = {
                    "id": f"{message_id}:{tool_call_id}",
                    "type": "tool_call",
                    "toolCallId": tool_call_id,
                    "toolName": _tool_call_name(tool_call),
                    "status": "started",
                    "argsText": _tool_call_args(tool_call),
                    "resultText": None,
                    "sequence": sequence,
                }
                assistant_blocks_by_tool_id[tool_call_id] = block
                blocks.append(block)
            if blocks:
                rendered.append(
                    {
                        "id": message_id,
                        "role": "assistant",
                        "blocks": blocks,
                        "createdAt": created_at,
                    }
                )
            continue

        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            block = assistant_blocks_by_tool_id.get(tool_call_id)
            result_text = _message_text(message)
            if block is not None:
                block["status"] = "completed"
                block["resultText"] = result_text
                continue
            rendered.append(
                {
                    "id": message_id,
                    "role": "assistant",
                    "blocks": [
                        {
                            "id": f"{message_id}:{tool_call_id or 'tool'}",
                            "type": "tool_call",
                            "toolCallId": tool_call_id or f"{message_id}:tool",
                            "toolName": str(message.get("name") or "tool"),
                            "status": "completed",
                            "resultText": result_text,
                            "sequence": 0,
                        }
                    ],
                    "createdAt": created_at,
                }
            )

    for item in rendered:
        for block in item["blocks"]:
            if block["type"] == "tool_call" and block["status"] == "started":
                block["status"] = "completed"
    return rendered


class CloudSessionCatalog:
    """Manage durable session metadata and detail payloads."""

    def __init__(self, workspace_manager, session_store) -> None:
        self.workspace_manager = workspace_manager
        self.session_store = session_store

    def _manifest_path(self, root: Path) -> Path:
        return root / MANIFEST_RELATIVE_PATH

    def _manifest_key(self, user_id: str) -> str:
        return f"{self.workspace_manager.user_prefix(user_id)}/{MANIFEST_RELATIVE_PATH.as_posix()}"

    def _session_remote_key(self, user_id: str, agent_name: str, session_id: str) -> str:
        relative = session_file_relative_path(user_id, agent_name, session_id)
        return f"{self.workspace_manager.user_prefix(user_id)}/{relative.as_posix()}"

    def _load_manifest_root(self, root: Path) -> dict[str, Any]:
        path = self._manifest_path(root)
        if not path.exists():
            return {"version": 1, "sessions": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_manifest_root(self, root: Path, manifest: dict[str, Any]) -> None:
        path = self._manifest_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_manifest_remote(self, user_id: str) -> dict[str, Any]:
        key = self._manifest_key(user_id)
        store = self.workspace_manager.store
        if not store.exists(key):
            return {"version": 1, "sessions": {}}
        return json.loads(store.get_bytes(key).decode("utf-8"))

    def _load_session_payload(self, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        metadata: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []
        if not path.exists():
            raise FileNotFoundError(path.name)
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("_type") == "metadata":
                    metadata = data
                else:
                    messages.append(data)
        return metadata, messages

    def _load_session_payload_bytes(self, data: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        metadata: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []
        for raw_line in data.decode("utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if parsed.get("_type") == "metadata":
                metadata = parsed
            else:
                messages.append(parsed)
        return metadata, messages

    def _manifest_summary(self, entry: dict[str, Any]) -> SessionSummary:
        return SessionSummary(
            id=str(entry["session_id"]),
            agent_id=str(entry["agent_id"]),
            title=str(entry.get("title") or DEFAULT_SESSION_TITLE),
            created_at=str(entry.get("created_at") or utc_now_iso()),
            updated_at=str(entry.get("updated_at") or utc_now_iso()),
        )

    def _upsert_manifest_entry(
        self,
        manifest: dict[str, Any],
        *,
        session_id: str,
        agent_name: str,
        title: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        sessions = manifest.setdefault("sessions", {})
        sessions[session_id] = {
            "session_id": session_id,
            "agent_id": agent_name,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        return manifest

    def list_sessions_remote(self, user_id: str, agent_name: str) -> list[SessionSummary]:
        manifest = self._load_manifest_remote(user_id)
        sessions = manifest.get("sessions", {})
        items = [
            self._manifest_summary(entry)
            for entry in sessions.values()
            if entry.get("agent_id") == agent_name
        ]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def create_session(self, root: Path, user_id: str, agent_name: str, session_id: str) -> SessionSummary:
        manager = SessionManager(root)
        key = session_key(user_id, agent_name, session_id)
        session = manager.get_or_create(key)
        session.metadata["agent_id"] = agent_name
        session.metadata["session_id"] = session_id
        session.metadata["title"] = session.metadata.get("title") or DEFAULT_SESSION_TITLE
        manager.save(session)

        created_at = session.created_at.isoformat()
        updated_at = session.updated_at.isoformat()
        manifest = self._load_manifest_root(root)
        self._upsert_manifest_entry(
            manifest,
            session_id=session_id,
            agent_name=agent_name,
            title=str(session.metadata["title"]),
            created_at=created_at,
            updated_at=updated_at,
        )
        self._save_manifest_root(root, manifest)
        return SessionSummary(
            id=session_id,
            agent_id=agent_name,
            title=str(session.metadata["title"]),
            created_at=created_at,
            updated_at=updated_at,
        )

    def sync_session_from_root(self, root: Path, user_id: str, agent_name: str, session_id: str) -> SessionSummary:
        manager = SessionManager(root)
        key = session_key(user_id, agent_name, session_id)
        session = manager.get_or_create(key)
        first_user_text = next(
            (_message_text(message) for message in session.messages if message.get("role") == "user" and _message_text(message)),
            "",
        )
        title = str(session.metadata.get("title") or DEFAULT_SESSION_TITLE)
        if title == DEFAULT_SESSION_TITLE and first_user_text:
            title = _truncate_title(first_user_text)
        session.metadata["title"] = title
        session.metadata["agent_id"] = agent_name
        session.metadata["session_id"] = session_id
        manager.save(session)

        manifest = self._load_manifest_root(root)
        self._upsert_manifest_entry(
            manifest,
            session_id=session_id,
            agent_name=agent_name,
            title=title,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )
        self._save_manifest_root(root, manifest)
        return SessionSummary(
            id=session_id,
            agent_id=agent_name,
            title=title,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        )

    def get_session_detail_remote(self, user_id: str, agent_name: str, session_id: str) -> SessionDetail:
        manifest = self._load_manifest_remote(user_id)
        entry = (manifest.get("sessions") or {}).get(session_id)
        if not isinstance(entry, dict) or entry.get("agent_id") != agent_name:
            raise FileNotFoundError(session_id)
        key = self._session_remote_key(user_id, agent_name, session_id)
        store = self.workspace_manager.store
        if not store.exists(key):
            raise FileNotFoundError(session_id)
        metadata, messages = self._load_session_payload_bytes(store.get_bytes(key))
        title = str((metadata.get("metadata") or {}).get("title") or entry.get("title") or DEFAULT_SESSION_TITLE)
        return SessionDetail(
            id=session_id,
            agent_id=agent_name,
            title=title,
            created_at=str(entry.get("created_at") or metadata.get("created_at") or utc_now_iso()),
            updated_at=str(entry.get("updated_at") or metadata.get("updated_at") or utc_now_iso()),
            messages=session_messages_to_blocks(messages),
        )

    def rename_session(self, root: Path, user_id: str, agent_name: str, session_id: str, title: str) -> SessionSummary:
        manifest = self._load_manifest_root(root)
        entry = (manifest.get("sessions") or {}).get(session_id)
        if not isinstance(entry, dict) or entry.get("agent_id") != agent_name:
            raise FileNotFoundError(session_id)
        manager = SessionManager(root)
        key = session_key(user_id, agent_name, session_id)
        session = manager.get_or_create(key)
        session.metadata["title"] = title
        session.metadata["agent_id"] = agent_name
        session.metadata["session_id"] = session_id
        manager.save(session)
        updated_at = session.updated_at.isoformat()
        self._upsert_manifest_entry(
            manifest,
            session_id=session_id,
            agent_name=agent_name,
            title=title,
            created_at=str(entry.get("created_at") or session.created_at.isoformat()),
            updated_at=updated_at,
        )
        self._save_manifest_root(root, manifest)
        return SessionSummary(
            id=session_id,
            agent_id=agent_name,
            title=title,
            created_at=str(entry.get("created_at") or session.created_at.isoformat()),
            updated_at=updated_at,
        )

    def delete_session(self, root: Path, user_id: str, agent_name: str, session_id: str) -> None:
        manifest = self._load_manifest_root(root)
        sessions = manifest.setdefault("sessions", {})
        entry = sessions.get(session_id)
        if not isinstance(entry, dict) or entry.get("agent_id") != agent_name:
            raise FileNotFoundError(session_id)
        session_path = root / session_file_relative_path(user_id, agent_name, session_id)
        if session_path.exists():
            session_path.unlink()
        sessions.pop(session_id, None)
        self._save_manifest_root(root, manifest)

    def session_has_durable_user_turn(self, user_id: str, agent_name: str, session_id: str) -> bool:
        key = self._session_remote_key(user_id, agent_name, session_id)
        store = self.workspace_manager.store
        if not store.exists(key):
            return False
        _, messages = self._load_session_payload_bytes(store.get_bytes(key))
        return any(message.get("role") == "user" and _message_text(message) for message in messages)
