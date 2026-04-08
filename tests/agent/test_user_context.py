"""Tests for user_context ContextVar."""

from nanobot.utils.user_context import (
    clear_current_user_id,
    get_current_user_id,
    set_current_user_id,
)


def test_default_is_none():
    """No user set by default."""
    clear_current_user_id()
    assert get_current_user_id() is None


def test_set_and_get():
    """Can set and retrieve user ID."""
    set_current_user_id("alice")
    try:
        assert get_current_user_id() == "alice"
    finally:
        clear_current_user_id()


def test_clear_resets_to_none():
    """Clearing resets to None."""
    set_current_user_id("alice")
    clear_current_user_id()
    assert get_current_user_id() is None


def test_isolation_across_contexts():
    """Setting user in one context does not affect another."""
    import contextvars

    # Test isolation with synchronous context.copy().run()
    # This verifies that ContextVars are truly isolated across contexts
    ctx = contextvars.copy_context()
    results: list[str | None] = []

    def get_in_main():
        return get_current_user_id()

    def get_in_copied():
        return ctx.run(get_current_user_id)

    set_current_user_id("alice")
    try:
        results.append(get_in_main())  # Should be "alice"
        results.append(get_in_copied())  # Copied context should NOT have "alice"
    finally:
        clear_current_user_id()

    # Main context has alice
    assert results[0] == "alice"
    # Copied context should NOT have alice (it's a copy of state BEFORE we set alice)
    assert results[1] is None
