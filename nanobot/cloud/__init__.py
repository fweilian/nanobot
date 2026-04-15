"""Cloud multi-user multi-agent runtime for nanobot."""

from nanobot.cloud.config import CloudAgentConfig, CloudServiceSettings, UserWorkspaceConfig

__all__ = ["CloudAgentConfig", "CloudServiceSettings", "UserWorkspaceConfig", "create_app"]


def create_app(*args, **kwargs):
    """Lazily import the FastAPI app factory to avoid circular imports."""
    from nanobot.cloud.server import create_app as _create_app

    return _create_app(*args, **kwargs)
