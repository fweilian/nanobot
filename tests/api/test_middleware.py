import jwt
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from nanobot.api.middleware import JWTAuthMiddleware, WORKSPACE_KEY


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


async def test_missing_user_id_returns_401():
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


async def test_workspace_initialized_on_first_login(tmp_path):
    """Verify user workspace is created with templates on first authenticated request."""
    from nanobot.api.middleware import JWTAuthMiddleware

    workspace = tmp_path / ".nanobot"
    workspace.mkdir()

    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app[WORKSPACE_KEY] = workspace
    app.router.add_get("/test", handler)

    token = _make_token({"userId": "alice"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200

    # 验证用户 workspace 目录已创建
    user_ws = workspace / "workspaces" / "alice"
    assert user_ws.exists(), f"User workspace not created: {user_ws}"
    assert (user_ws / "SOUL.md").exists(), "SOUL.md not created"
    assert (user_ws / "USER.md").exists(), "USER.md not created"
    assert (user_ws / "memory" / "MEMORY.md").exists(), "MEMORY.md not created"
    assert (user_ws / "memory" / "history.jsonl").exists(), "history.jsonl not created"


async def test_workspace_init_idempotent(tmp_path):
    """Verify workspace initialization is idempotent (second login doesn't error)."""
    from nanobot.api.middleware import JWTAuthMiddleware

    workspace = tmp_path / ".nanobot"
    workspace.mkdir()
    user_ws = workspace / "workspaces" / "alice"
    user_ws.mkdir(parents=True)
    # 预先创建一些文件
    (user_ws / "SOUL.md").write_text("existing content")

    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app[WORKSPACE_KEY] = workspace
    app.router.add_get("/test", handler)

    token = _make_token({"userId": "alice"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200
        # 原有内容应保留
        assert (user_ws / "SOUL.md").read_text() == "existing content"
