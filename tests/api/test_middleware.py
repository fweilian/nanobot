import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from nanobot.api.middleware import JWTAuthMiddleware
import jwt


def _make_token(payload: dict, secret: str = "test-secret") -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


async def test_missing_auth_header_returns_401():
    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test")
        assert resp.status == 401
        data = await resp.json()
        assert "Missing or invalid Authorization header" in data["error"]["message"]


async def test_valid_token_sets_user_id():
    async def handler(request):
        assert request["user_id"] == "alice"
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    token = _make_token({"userId": "alice"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200


async def test_missing_userId_returns_401():
    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    token = _make_token({"some": "claim"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 401
        data = await resp.json()
        assert "Missing userId in token" in data["error"]["message"]


async def test_wrong_secret_returns_401():
    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app.router.add_get("/test", handler)

    token = _make_token({"userId": "alice"}, "wrong-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 401
        data = await resp.json()
        assert "Invalid token" in data["error"]["message"]