"""Pytest configuration and fixtures for nanobot tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_storage():
    """Reset the global _storage to None after each test to ensure test isolation."""
    import nanobot.utils.helpers as helpers

    original = helpers._storage
    helpers._storage = None
    yield
    helpers._storage = original
