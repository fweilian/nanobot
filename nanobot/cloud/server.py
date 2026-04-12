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
from nanobot.cloud.lock import CloudSessionLockedError, RedisDistributedLockManager
from nanobot.cloud.runtime import CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.session_store import RedisSessionStore
from nanobot.cloud.skills_cache import (
    RedisSkillBundleStore,
    SkillStageBudgetExceededError,
    SkillStageBudgetManager,
)
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


def _chunk(
    content: str | None,
    model: str,
    *,
    finish_reason: str | None = None,
    include_role: bool = False,
    message_id: str | None = None,
    block_id: str | None = None,
    sequence: int | None = None,
) -> str:
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
    if message_id is not None:
        payload["event"] = "assistant_text_delta"
        payload["message_id"] = message_id
        payload["block_id"] = block_id
        payload["sequence"] = sequence
        payload["content"] = content or ""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error(code: str, message: str, *, retryable: bool) -> str:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        }
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _tool_event_chunk(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _reduce_tool_events(message_id: str, content: str, tool_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append(
            {
                "id": f"{message_id}:markdown",
                "type": "markdown",
                "content": content,
                "sequence": 0,
            }
        )

    by_tool_id: dict[str, dict[str, Any]] = {}
    for event in tool_events:
        tool_call_id = str(event.get("tool_call_id") or "")
        if not tool_call_id:
            continue
        block = by_tool_id.get(tool_call_id)
        if block is None:
            block = {
                "id": str(event.get("block_id") or f"{message_id}:{tool_call_id}"),
                "type": "tool_call",
                "toolCallId": tool_call_id,
                "toolName": str(event.get("tool_name") or "tool"),
                "status": "started",
                "argsText": None,
                "resultText": None,
                "sequence": int(event.get("sequence") or 0),
            }
            by_tool_id[tool_call_id] = block
        block["toolName"] = str(event.get("tool_name") or block["toolName"])
        if event.get("args_text") is not None:
            block["argsText"] = str(event["args_text"])
        if event.get("result_text") is not None:
            block["resultText"] = str(event["result_text"])
        block["sequence"] = int(event.get("sequence") or block["sequence"])
        event_name = str(event.get("event") or "")
        block["status"] = (
            "started"
            if event_name == "tool_call_started"
            else "streaming"
            if event_name == "tool_call_updated"
            else "completed"
            if event_name == "tool_call_completed"
            else "failed"
            if event_name == "tool_call_failed"
            else block["status"]
        )

    blocks.extend(sorted(by_tool_id.values(), key=lambda item: item["sequence"]))
    return blocks


def _reduce_blocks_from_events(
    message_id: str,
    text_events: list[dict[str, Any]],
    tool_events: list[dict[str, Any]],
    fallback_content: str,
) -> list[dict[str, Any]]:
    markdown_blocks: dict[str, dict[str, Any]] = {}
    for event in text_events:
      block_id = str(event.get("block_id") or f"{message_id}:markdown")
      block = markdown_blocks.get(block_id)
      if block is None:
          block = {
              "id": block_id,
              "type": "markdown",
              "content": "",
              "sequence": int(event.get("sequence") or 0),
          }
          markdown_blocks[block_id] = block
      block["content"] += str(event.get("content") or "")
      block["sequence"] = int(event.get("sequence") or block["sequence"])

    blocks = sorted(markdown_blocks.values(), key=lambda item: item["sequence"])
    if not blocks and fallback_content:
        blocks.append(
            {
                "id": f"{message_id}:markdown",
                "type": "markdown",
                "content": fallback_content,
                "sequence": 0,
            }
        )
    blocks.extend(_reduce_tool_events(message_id, "", tool_events))
    return sorted(blocks, key=lambda item: item["sequence"])


def build_runtime_service(settings: CloudServiceSettings) -> CloudRuntimeService:
    """Build the main cloud runtime service from settings."""
    from redis.asyncio import Redis

    platform_config = resolve_config_env_vars(load_config(settings.nanobot_config_path))
    provider_name = platform_config.get_provider_name(platform_config.agents.defaults.model) or "managed"
    provider_view = ManagedProviderView(
        provider=provider_name,
        model=platform_config.agents.defaults.model,
    )
    redis_client = Redis.from_url(settings.redis.url, encoding="utf-8", decode_responses=False)
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
        session_store=RedisSessionStore(
            redis_client,
            key_prefix=settings.redis.key_prefix,
            ttl_s=settings.redis.session_ttl_s,
        ),
        lock_manager=RedisDistributedLockManager(
            redis_client,
            key_prefix=settings.redis.key_prefix,
        ),
        skill_bundle_store=RedisSkillBundleStore(
            redis_client,
            key_prefix=settings.redis.key_prefix,
            ttl_s=settings.skill_cache.redis_content_ttl_s,
        ),
        skill_stage_budget=SkillStageBudgetManager(
            request_budget_bytes=settings.skill_cache.request_stage_budget_bytes,
            instance_budget_bytes=settings.skill_cache.instance_stage_budget_bytes,
        ),
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

    def _session_locked_response() -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "message": "Another write request is already in progress for this session.",
                    "type": "conflict_error",
                    "code": "session_locked",
                    "retryable": True,
                }
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    def _skill_stage_budget_response(exc: SkillStageBudgetExceededError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "message": "Skill staging exceeds local cache budget for this instance.",
                    "type": "capacity_error",
                    "code": "skill_stage_budget_exceeded",
                    "retryable": True,
                    "requestedBytes": exc.requested_bytes,
                    "requestBudgetBytes": exc.request_budget_bytes,
                    "instanceBudgetBytes": exc.instance_budget_bytes,
                    "currentInstanceBytes": exc.current_instance_bytes,
                }
            },
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        )

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
        try:
            reservation = await service.reserve_chat_execution(user.user_id, body.agent, body.session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except CloudSessionLockedError:
            return _session_locked_response()
        except SkillStageBudgetExceededError as exc:
            return _skill_stage_budget_response(exc)

        if not body.stream:
            message_id = f"asst-{uuid.uuid4().hex[:12]}"
            tool_events: list[dict[str, Any]] = []
            text_events: list[dict[str, Any]] = []
            sequence = 0
            current_text_block_id: str | None = None

            async def _on_stream(delta: str) -> None:
                nonlocal sequence
                nonlocal current_text_block_id
                sequence += 1
                if current_text_block_id is None:
                    current_text_block_id = f"{message_id}:markdown:{sequence}"
                text_events.append(
                    {
                        "event": "assistant_text_delta",
                        "message_id": message_id,
                        "block_id": current_text_block_id,
                        "sequence": sequence,
                        "content": delta,
                    }
                )

            async def _on_tool_event(event: dict[str, Any]) -> None:
                nonlocal sequence
                nonlocal current_text_block_id
                sequence += 1
                current_text_block_id = None
                tool_events.append(
                    {
                        **event,
                        "message_id": message_id,
                        "block_id": event.get("block_id") or f"{message_id}:{event.get('tool_call_id')}",
                        "sequence": sequence,
                    }
                )

            try:
                result = await service.run_chat(
                    user=user,
                    agent_name=body.agent,
                    session_id=body.session_id,
                    content=content,
                    reservation=reservation,
                    message_id=message_id,
                    on_stream=_on_stream,
                    on_tool_event=_on_tool_event,
                )
            except CloudSessionLockedError:
                return _session_locked_response()
            except SkillStageBudgetExceededError as exc:
                return _skill_stage_budget_response(exc)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            payload = _completion_response(result.content, result.model)
            payload["message"] = {
                "id": message_id,
                "role": "assistant",
                "blocks": _reduce_blocks_from_events(message_id, text_events, tool_events, result.content),
            }
            return JSONResponse(payload)

        async def event_stream():
            queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
            message_id = f"asst-{uuid.uuid4().hex[:12]}"
            sequence = 0
            current_text_block_id: str | None = None

            async def _on_stream(delta: str) -> None:
                nonlocal sequence
                nonlocal current_text_block_id
                sequence += 1
                if current_text_block_id is None:
                    current_text_block_id = f"{message_id}:markdown:{sequence}"
                await queue.put((
                    "delta",
                    json.dumps(
                        {
                            "content": delta,
                            "sequence": sequence,
                            "block_id": current_text_block_id,
                        }
                    ),
                ))

            async def _on_stream_end(*, resuming: bool = False) -> None:
                if not resuming:
                    await queue.put(("end", None))

            async def _on_tool_event(event: dict[str, Any]) -> None:
                nonlocal sequence
                nonlocal current_text_block_id
                sequence += 1
                current_text_block_id = None
                payload = {
                    **event,
                    "message_id": message_id,
                    "block_id": event.get("block_id") or f"{message_id}:{event.get('tool_call_id')}",
                    "sequence": sequence,
                }
                await queue.put(("tool", json.dumps(payload, ensure_ascii=False)))

            task = asyncio.create_task(
                service.run_chat(
                    user=user,
                    agent_name=body.agent,
                    session_id=body.session_id,
                    content=content,
                    reservation=reservation,
                    message_id=message_id,
                    on_stream=_on_stream,
                    on_stream_end=_on_stream_end,
                    on_tool_event=_on_tool_event,
                )
            )
            model_name = service.platform_model
            started = False
            try:
                while True:
                    if task.done() and queue.empty():
                        try:
                            result = await task
                        except FileNotFoundError as exc:
                            yield _sse_error("not_found", str(exc), retryable=False)
                            yield "data: [DONE]\n\n"
                            break
                        except Exception:
                            yield _sse_error("server_error", "Streaming execution failed.", retryable=False)
                            yield "data: [DONE]\n\n"
                            break
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
                        parsed = json.loads(payload or "{}")
                        yield _chunk(
                            parsed.get("content") or "",
                            model_name,
                            message_id=message_id,
                            block_id=parsed.get("block_id"),
                            sequence=parsed.get("sequence"),
                        )
                        continue
                    if kind == "tool":
                        yield _tool_event_chunk(json.loads(payload or "{}"))
                        continue
                    try:
                        result = await task
                    except FileNotFoundError as exc:
                        yield _sse_error("not_found", str(exc), retryable=False)
                        yield "data: [DONE]\n\n"
                        break
                    except Exception:
                        yield _sse_error("server_error", "Streaming execution failed.", retryable=False)
                        yield "data: [DONE]\n\n"
                        break
                    model_name = result.model
                    yield _chunk(None, model_name, finish_reason="stop")
                    yield "data: [DONE]\n\n"
                    break
            except (CloudSessionLockedError, SkillStageBudgetExceededError, FileNotFoundError):
                task.cancel()
                raise
            except Exception:
                task.cancel()
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app
