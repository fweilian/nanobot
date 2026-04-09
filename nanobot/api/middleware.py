"""JWT 认证中间件，用于 aiohttp."""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

import jwt
from aiohttp import web

WORKSPACE_KEY = web.AppKey("workspace")


class JWTAuthMiddleware:
    """验证 JWT token 并将 userId claim 提取到 request['user_id']."""

    __middleware_version__ = 1

    def __init__(self, secret: str):
        self.secret = secret.encode()

    async def __call__(self, request: web.Request, handler: Callable[[web.Request], Awaitable[web.Response]]) -> web.Response:
        # Skip auth for public endpoints
        if request.path in {"/health", "/v1/models"}:
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _error(401, "Missing or invalid Authorization header")

        token = auth_header[7:]
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
        except jwt.InvalidSignatureError:
            return _error(401, "Invalid token")
        except jwt.ExpiredSignatureError:
            return _error(401, "Token expired")
        except jwt.DecodeError:
            return _error(401, "Invalid token")

        user_id = payload.get("userId")
        if not user_id:
            return _error(401, "Missing userId in token")

        # 初始化用户 workspace（幂等操作，首次登录时触发）
        await self._ensure_user_workspace(request, user_id)

        request["user_id"] = user_id
        return await handler(request)

    async def _ensure_user_workspace(self, request: web.Request, user_id: str) -> None:
        """确保用户 workspace 已初始化（幂等操作）."""
        workspace = request.app.get(WORKSPACE_KEY)
        if not workspace:
            return
        user_workspace = workspace / "workspaces" / user_id
        # sync_workspace_templates 是同步的，在线程池中运行
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _sync_user_workspace(user_workspace, user_id),
        )


def _error(status: int, message: str) -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": "invalid_request_error", "code": status}},
        status=status,
    )


def _sync_user_workspace(user_workspace: Path, user_id: str) -> None:
    """Sync templates to user workspace with correct cloud storage prefix."""
    from nanobot.utils.helpers import sync_workspace_templates
    storage_prefix = f"workspaces/{user_id}/"
    sync_workspace_templates(user_workspace, silent=True, storage_prefix=storage_prefix)
