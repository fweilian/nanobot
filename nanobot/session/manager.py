"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.providers.cloud_storage import create_storage
from nanobot.utils.helpers import find_legal_message_start, safe_filename

if TYPE_CHECKING:
    from nanobot.config.schema import CloudStorageConfig


@dataclass
class Session:
    """A conversation session."""

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a legal tool-call boundary."""
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # Avoid starting mid-turn when possible.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                sliced = sliced[i:]
                break

        # Drop orphan tool results at the front.
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            entry: dict[str, Any] = {"role": message["role"], "content": message.get("content", "")}
            for key in ("tool_calls", "tool_call_id", "name", "reasoning_content"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        """Keep a legal recent suffix, mirroring get_history boundary rules."""
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        start_idx = max(0, len(self.messages) - max_messages)

        # If the cutoff lands mid-turn, extend backward to the nearest user turn.
        while start_idx > 0 and self.messages[start_idx].get("role") != "user":
            start_idx -= 1

        retained = self.messages[start_idx:]

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored via CloudStorage.
    """

    def __init__(
        self,
        workspace: Path,
        cloud_config: "CloudStorageConfig | None" = None,
    ):
        self.workspace = workspace
        self._storage = create_storage(cloud_config, workspace)
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    def _get_session_key(self, key: str) -> str:
        """Get the storage key for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return f"sessions/{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def _read_session_bytes(self, key: str) -> bytes | None:
        """Read session bytes from storage, return None if not found."""
        try:
            return self._storage.read(self._get_session_key(key))
        except FileNotFoundError:
            return None

    def _write_session_bytes(self, key: str, data: bytes) -> None:
        """Write session bytes to storage."""
        self._storage.write(self._get_session_key(key), data)

    def _session_exists(self, key: str) -> bool:
        """Check if session exists in storage."""
        return self._storage.exists(self._get_session_key(key))

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from storage."""
        # Check legacy path first (local migration only)
        legacy_path = self._get_legacy_session_path(key)
        if legacy_path.exists():
            try:
                shutil.move(str(legacy_path), str(self.workspace / self._get_session_key(key)))
                logger.info("Migrated session {} from legacy path", key)
            except Exception:
                logger.exception("Failed to migrate session {}", key)

        data = self._read_session_bytes(key)
        if data is None:
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            lines = data.decode("utf-8").split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                obj = json.loads(line)

                if obj.get("_type") == "metadata":
                    metadata = obj.get("metadata", {})
                    created_at = datetime.fromisoformat(obj["created_at"]) if obj.get("created_at") else None
                    last_consolidated = obj.get("last_consolidated", 0)
                else:
                    messages.append(obj)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to storage."""
        metadata_line = {
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "last_consolidated": session.last_consolidated
        }
        lines = [json.dumps(metadata_line, ensure_ascii=False) + "\n"]
        for msg in session.messages:
            lines.append(json.dumps(msg, ensure_ascii=False) + "\n")
        data = "".join(lines).encode("utf-8")
        self._write_session_bytes(session.key, data)
        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []
        try:
            keys = self._storage.list("sessions/")
        except Exception:
            return []

        for key in keys:
            if not key.endswith(".jsonl"):
                continue
            try:
                data = self._storage.read(f"sessions/{key}")
                if not data:
                    continue
                lines = data.decode("utf-8").split("\n")
                first_line = lines[0].strip() if lines else ""
                if first_line:
                    obj = json.loads(first_line)
                    if obj.get("_type") == "metadata":
                        safe_key = key.replace(".jsonl", "")
                        sessions.append({
                            "key": obj.get("key") or safe_key.replace("_", ":", 1),
                            "created_at": obj.get("created_at"),
                            "updated_at": obj.get("updated_at"),
                            "path": key
                        })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
