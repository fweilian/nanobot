"""JWT 认证中间件，用于 aiohttp."""

from aiohttp import web
from typing import Callable, Awaitable
import jwt


class JWTAuthMiddleware:
    """验证 JWT token 并将 userId claim 提取到 request['user_id']."""

    __middleware_version__ = 1

    def __init__(self, secret: str):
        self.secret = secret.encode()

    async def __call__(self, request: web.Request, handler: Callable[[web.Request], Awaitable[web.Response]]) -> web.Response:
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

        request["user_id"] = user_id
        return await handler(request)


def _error(status: int, message: str) -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": "invalid_request_error", "code": status}},
        status=status,
    )