"""User context — carries the current user ID through the async call stack."""

from contextvars import ContextVar

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: str | None) -> None:
    """Set the current user ID for this async context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> str | None:
    """Get the current user ID for this async context, or None if not set."""
    return _current_user_id.get()


def clear_current_user_id() -> None:
    """Clear the current user ID (used in finally blocks)."""
    _current_user_id.set(None)
