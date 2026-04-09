"""OpenAI-compatible HTTP API server for a fixed nanobot session.

Provides /v1/chat/completions and /v1/models endpoints.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.api.middleware import JWTAuthMiddleware
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


def _chat_completion_response(content: str, model: str) -> dict[str, Any]:
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


def _sse_chunk(content: str, id: str, model: str, created: int, role_sent: bool = False, finish_reason: str | None = None) -> bytes:
    """Build an OpenAI-compatible SSE chunk."""
    delta = {}
    if not role_sent:
        delta["role"] = "assistant"
    if content:
        delta["content"] = content
    choice = {"index": 0, "delta": delta, "finish_reason": finish_reason}
    chunk = {"id": id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [choice]}
    return f"data: {json.dumps(chunk)}\n\n".encode()


def _sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_chat_completions(request: web.Request) -> web.Response:
    """POST /v1/chat/completions"""

    # --- Parse body ---
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return _error_json(400, "Only a single user message is supported")

    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return _error_json(400, "Only a single user message is supported")
    user_content = message.get("content", "")
    if isinstance(user_content, list):
        # Multi-modal content array — extract text parts
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )

    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    model_name: str = request.app.get("model_name", "nanobot")
    if (requested_model := body.get("model")) and requested_model != model_name:
        return _error_json(400, f"Only configured model '{model_name}' is available")

    session_key = f"api:{body['session_id']}" if body.get("session_id") else API_SESSION_KEY
    session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())
    sender_id = request.get("user_id", "anonymous")

    # SSE streaming branch
    if body.get("stream", False):
        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        await resp.prepare(request)

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        role_sent_wrapper = [False]  # closure mutable cell for role_sent

        def sse_write(delta: str) -> None:
            if delta:
                chunk = _sse_chunk(delta, completion_id, model_name, created, role_sent=role_sent_wrapper[0])
                resp.write(chunk)
                role_sent_wrapper[0] = True

        async def sse_end(resuming: bool = False) -> None:
            resp.write(_sse_chunk("", completion_id, model_name, created, role_sent=role_sent_wrapper[0], finish_reason="stop"))
            resp.write(_sse_done())
            await resp.write_eof()

        try:
            async with session_lock:
                try:
                    await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                            sender_id=sender_id,
                            on_stream=sse_write,
                            on_stream_end=sse_end,
                        ),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    resp.write(_sse_done())
                    await resp.write_eof()
                    return resp
                except Exception:
                    resp.write(_sse_done())
                    await resp.write_eof()
                    raise
        except Exception:
            logger.exception("Unexpected API lock error for session {}", session_key)
            resp.write(_sse_done())
            await resp.write_eof()
            raise

        return resp

    logger.info("API request session_key={} content={}", session_key, user_content[:80])

    _fallback = EMPTY_FINAL_RESPONSE_MESSAGE

    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_content,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                        sender_id=sender_id,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)

                if not response_text or not response_text.strip():
                    logger.warning(
                        "Empty response for session {}, retrying",
                        session_key,
                    )
                    retry_response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                            sender_id=sender_id,
                        ),
                        timeout=timeout_s,
                    )
                    response_text = _response_text(retry_response)
                    if not response_text or not response_text.strip():
                        logger.warning(
                            "Empty response after retry for session {}, using fallback",
                            session_key,
                        )
                        response_text = _fallback

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    return web.json_response(_chat_completion_response(response_text, model_name))


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = request.app.get("model_name", "nanobot")
    return web.json_response({
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": "nanobot",
            }
        ],
    })


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(agent_loop, *, jwt_secret: str = "", model_name: str = "nanobot", request_timeout: float = 120.0, workspace: "Path | None" = None) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
        workspace: Base workspace path for user workspace isolation.
    """
    app = web.Application()
    app["agent_loop"] = agent_loop
    app["model_name"] = model_name
    app["request_timeout"] = request_timeout
    app["session_locks"] = {}  # per-user locks, keyed by session_key
    if workspace is not None:
        app["workspace"] = workspace
    if jwt_secret:
        app.middlewares.append(JWTAuthMiddleware(jwt_secret))

    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    return app
