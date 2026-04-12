"""CLI entrypoint for the cloud server."""

from __future__ import annotations


def main() -> None:
    """Run the FastAPI cloud server with uvicorn."""
    import uvicorn

    from nanobot.cloud.config import CloudServiceSettings

    settings = CloudServiceSettings()
    uvicorn.run(
        "nanobot.cloud.server:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
    )
