"""FastAPI server for the cloud runtime."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from nanobot.cloud.auth import (
    AuthenticatedUser,
    JwtTokenVerifier,
    TokenVerifier,
    resolve_bearer_token,
)
from nanobot.cloud.config import CloudServiceSettings, ManagedProviderView
from nanobot.cloud.runtime import CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.storage import S3ObjectStore
from nanobot.config.loader import load_config, resolve_config_env_vars


class ChatMessage(BaseModel):
    """OpenAI-compatible message payload."""

    role: str
    content: str | list[dict[str, Any]]


class ChatCompletionsRequest(BaseModel):
    """OpenAI-compatible chat completion request with a cloud-specific agent field."""

    model: str | None = None
    agent: str = "default"
    session_id: str = "default"
    stream: bool = False
    messages: list[ChatMessage] = Field(default_factory=list)


def _last_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        if isinstance(message.content, str):
            return message.content
        return " ".join(
            str(block.get("text", ""))
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one user message is required")


def _completion_response(content: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _chunk(content: str | None, model: str, *, finish_reason: str | None = None, include_role: bool = False) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": (
                    {"role": "assistant", "content": content or ""}
                    if include_role
                    else ({} if content is None else {"content": content})
                ),
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_runtime_service(settings: CloudServiceSettings) -> CloudRuntimeService:
    """Build the main cloud runtime service from settings."""
    platform_config = resolve_config_env_vars(load_config(settings.nanobot_config_path))
    provider_name = platform_config.get_provider_name(platform_config.agents.defaults.model) or "managed"
    provider_view = ManagedProviderView(
        provider=provider_name,
        model=platform_config.agents.defaults.model,
    )
    workspace_manager = CloudWorkspaceManager(
        store=S3ObjectStore(
            bucket=settings.s3.bucket,
            prefix=settings.s3.prefix,
            endpoint_url=settings.s3.endpoint_url,
            region_name=settings.s3.region_name,
            access_key_id=settings.s3.access_key_id,
            secret_access_key=settings.s3.secret_access_key,
        ),
        cache_root=settings.cache_root,
        workspace_prefix=settings.workspace_prefix,
        platform_provider=provider_view,
    )
    return CloudRuntimeService(
        settings=settings,
        workspace_manager=workspace_manager,
        platform_config_path=settings.nanobot_config_path,
    )


def build_token_verifier(settings: CloudServiceSettings) -> TokenVerifier:
    """Build the auth verifier from settings."""
    return JwtTokenVerifier(
        algorithms=settings.auth.algorithms,
        user_id_claim=settings.auth.user_id_claim,
        audience=settings.auth.audience,
        issuer=settings.auth.issuer,
        jwks_url=settings.auth.jwks_url,
        shared_secret=settings.auth.shared_secret,
    )


def create_app(
    runtime_service: CloudRuntimeService | None = None,
    token_verifier: TokenVerifier | None = None,
    settings: CloudServiceSettings | None = None,
) -> FastAPI:
    """Create the FastAPI application."""
    resolved_settings = settings or CloudServiceSettings()
    service = runtime_service or build_runtime_service(resolved_settings)
    verifier = token_verifier or build_token_verifier(resolved_settings)
    app = FastAPI(title="nanobot cloud", version="0.1.5")
    app.state.runtime_service = service
    app.state.token_verifier = verifier
    app.state.settings = resolved_settings

    async def current_user(
        request: Request,
        token: str = Depends(resolve_bearer_token),
    ) -> AuthenticatedUser:
        return request.app.state.token_verifier.verify(token)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models(request: Request) -> dict[str, Any]:
        model_name = request.app.state.runtime_service.platform_model
        return {
            "object": "list",
            "data": [
                {
                    "id": model_name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "nanobot-cloud",
                }
            ],
        }

    @app.get("/v1/agents")
    async def agents(
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ) -> dict[str, Any]:
        entries = await request.app.state.runtime_service.list_agents(user)
        return {
            "object": "list",
            "data": [
                {
                    "id": agent.name,
                    "object": "agent",
                    "description": agent.description,
                    "skills": agent.skills,
                }
                for agent in entries
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        body: ChatCompletionsRequest,
        request: Request,
        user: AuthenticatedUser = Depends(current_user),
    ):
        service: CloudRuntimeService = request.app.state.runtime_service
        if body.model and body.model != service.platform_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only configured model '{service.platform_model}' is available",
            )
        content = _last_user_text(body.messages)

        if not body.stream:
            try:
                result = await service.run_chat(
                    user=user,
                    agent_name=body.agent,
                    session_id=body.session_id,
                    content=content,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            return JSONResponse(_completion_response(result.content, result.model))

        try:
            await service.ensure_agent(user, body.agent)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        async def event_stream():
            queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()

            async def _on_stream(delta: str) -> None:
                await queue.put(("delta", delta))

            async def _on_stream_end(*, resuming: bool = False) -> None:
                if not resuming:
                    await queue.put(("end", None))

            task = asyncio.create_task(
                service.run_chat(
                    user=user,
                    agent_name=body.agent,
                    session_id=body.session_id,
                    content=content,
                    on_stream=_on_stream,
                    on_stream_end=_on_stream_end,
                )
            )
            model_name = service.platform_model
            started = False
            try:
                while True:
                    if task.done() and queue.empty():
                        result = await task
                        if not started:
                            yield _chunk("", model_name, include_role=True)
                            started = True
                        model_name = result.model
                        yield _chunk(None, model_name, finish_reason="stop")
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        kind, payload = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if not started:
                        yield _chunk("", model_name, include_role=True)
                        started = True
                    if kind == "delta":
                        yield _chunk(payload or "", model_name)
                        continue
                    result = await task
                    model_name = result.model
                    yield _chunk(None, model_name, finish_reason="stop")
                    yield "data: [DONE]\n\n"
                    break
            except FileNotFoundError as exc:
                task.cancel()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app
