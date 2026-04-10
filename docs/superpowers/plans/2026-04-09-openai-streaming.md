# OpenAI SSE Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `/v1/chat/completions` 增加 OpenAI 兼容的 SSE 流式返回支持，当 `stream=true` 时以 SSE 格式增量返回 LLM 输出。

**Architecture:** 在 `handle_chat_completions` 中检测 `stream=true`，进入 SSE 分支：创建 `web.StreamResponse`，将 SSE 写入函数作为 `on_stream` 回调，通过 `process_direct(on_stream=sse_write, on_stream_end=sse_finalize)` 驱动流式输出，最终发送 `data: [DONE]` 并关闭连接。

**Key Constraints (aiohttp):**
- 一旦 `await resp.prepare(request)` 后开始写入 body，就不能再返回 `web.json_response(...)`（HTTP status / headers 已经发出）。
- 因此：流式路径的错误/超时必须通过 SSE 结束（可选发送 `event: error` 或仅发送 `[DONE]`），并返回同一个 `StreamResponse`。

**Tech Stack:** aiohttp (已有), Python asyncio

---

## File Map

- **Modify:** `nanobot/api/server.py` — 在 `handle_chat_completions` 中新增 SSE 分支
- **Modify:** `tests/test_openai_api.py` — 更新 `test_stream_true_returns_400` 为新行为测试，新增流式场景测试

---

## Task 1: 修改 `handle_chat_completions` 支持 SSE 流式输出

**Files:**
- Modify: `nanobot/api/server.py:65-154`

- [ ] **Step 1: 在 `_chat_completion_response` 后添加 SSE chunk 构造辅助函数**

在 `_chat_completion_response` 函数下方（第 50 行后）添加：

```python
def _sse_chunk(
    content: str,
    *,
    completion_id: str,
    model: str,
    created: int,
    role_sent: bool,
    finish_reason: str | None = None,
) -> bytes:
    delta: dict[str, Any] = {}
    if not role_sent:
        delta["role"] = "assistant"
    if content:
        delta["content"] = content
    choice = {"index": 0, "delta": delta, "finish_reason": finish_reason}
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [choice],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


def _sse_done() -> bytes:
    return b"data: [DONE]\n\n"
```

- [ ] **Step 2: 修改 `handle_chat_completions` 中的 stream 检测逻辑（返回 StreamResponse）**

找到第 79-80 行：
```python
    if body.get("stream", False):
        return _error_json(400, "stream=true is not supported yet. Set stream=false or omit it.")
```

替换为 SSE 分支逻辑（建议放在解析完 `user_content`、`model_name`、`session_key`、`session_lock` 之后），核心要点：

- 构造并 `prepare` 一个 `web.StreamResponse`，header 至少包括：
  - `Content-Type: text/event-stream`
  - `Cache-Control: no-cache`
  - `Connection: keep-alive`
  -（可选）`X-Accel-Buffering: no`（避免反向代理缓冲导致前端看不到增量）
- 定义一个幂等的 `finalize()`：写出最后一个 `finish_reason="stop"` chunk、再写 `data: [DONE]`，然后 `write_eof()`；多次调用只生效一次
- `on_stream(delta)`：每次收到增量就 `resp.write(_sse_chunk(...))`，并在首次写入时带上 `delta.role=assistant`
- 超时 / 异常 / 客户端断开：也走 `finalize()`（可选额外发送一个 `event: error` 数据帧），但不再尝试返回 JSON 错误响应

```python
    # --- SSE streaming branch ---
    if body.get("stream", False):
        import json

        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        role_sent = False

        async def sse_write(delta: str) -> None:
            nonlocal role_sent
            if not delta:
                return
            await resp.write(_sse_chunk(delta, completion_id, model_name, created, role_sent=role_sent))
            role_sent = True

        async def sse_finalize(resuming: bool = False) -> None:
            # Must be idempotent; may be called from normal end / exception / timeout paths.
            ...

        session_key = f"api:{body['session_id']}" if body.get("session_id") else API_SESSION_KEY
        session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
        session_lock = session_locks.setdefault(session_key, asyncio.Lock())
        sender_id = request.get("user_id", "anonymous")

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
                    await sse_finalize(resuming=False)
                except asyncio.CancelledError:
                    await sse_finalize(resuming=False)
                    raise
                except Exception:
                    await sse_finalize(resuming=False)
                    raise
        except Exception:
            logger.exception("Error processing stream request for session {}", session_key)
            # Response is already started; best effort finalize.
            try:
                await sse_finalize(resuming=False)
            except Exception:
                pass
        return resp
```

- [ ] **Step 3: 确认 SSE 分支前 `user_content` 变量已定义**

在 SSE 分支（第 79 行进入）前，确认第 82-90 行的 `user_content` 解析逻辑：
```python
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return _error_json(400, "Only a single user message is supported")
    user_content = message.get("content", "")
    if isinstance(user_content, list):
        # Multi-modal content array — extract text parts
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )
```
这段逻辑在 SSE 分支之前已有，不需要移动位置。SSE 分支直接利用这些变量。

- [ ] **Step 4: 运行现有测试确保未破坏非流式路径**

Run: `pytest tests/test_openai_api.py -v`
Expected: All existing tests pass

- [ ] **Step 5:（可选）更新文档/README（如果仓库对 OpenAI API 支持有描述）**

---

## Task 2: 更新测试并新增流式场景测试

**Files:**
- Modify: `tests/test_openai_api.py`

- [ ] **Step 1: 更新 `test_stream_true_returns_400` 为流式测试**

找到第 104-112 行，替换为：

```python
@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_true_returns_sse_chunks(aiohttp_client, mock_agent) -> None:
    """stream=true returns SSE chunks in OpenAI format."""
    chunks_received: list[bytes] = []

    async def fake_process(content, session_key="", channel="", chat_id="", on_stream=None, on_stream_end=None):
        if on_stream:
            await on_stream("Hello")
            await on_stream(" world")
        if on_stream_end:
            await on_stream_end(resuming=False)
        return "Hello world"

    mock_agent.process_direct = fake_process

    app = create_app(mock_agent, model_name="test-model", request_timeout=10.0)
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/event-stream")

    # Read all SSE data
    body = b""
    async for chunk in resp.content.iter_any():
        body += chunk

    lines = body.decode().strip().split("\n")
    data_lines = [l for l in lines if l.startswith("data: ")]
    assert len(data_lines) >= 3  # role chunk + content chunks + finish chunk + [DONE]

    import json
    first_chunk = json.loads(data_lines[0][6:])
    assert first_chunk["choices"][0]["delta"].get("role") == "assistant"
    assert first_chunk["choices"][0]["finish_reason"] is None

    # Check content chunks
    content_chunks = [json.loads(l[6:]) for l in data_lines[1:-1] if l != "data: [DONE]"]
    full_content = "".join(c["choices"][0]["delta"].get("content", "") for c in content_chunks)
    assert "Hello" in full_content or "world" in full_content

    # Last chunk before [DONE] should have finish_reason=stop
    last_json_line = next(l for l in reversed(data_lines) if l != "data: [DONE]")
    last_chunk = json.loads(last_json_line[6:])
    assert last_chunk["choices"][0]["finish_reason"] == "stop"

    assert "data: [DONE]" in data_lines
```

- [ ] **Step 2: 新增测试 — SSE 超时处理（只验证连接能结束）**

在 `test_stream_true_returns_sse_chunks` 后添加：

```python
@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_timeout_sends_done(aiohttp_client) -> None:
    """Stream request that times out sends [DONE] before returning 504."""
    async def slow_process(content, session_key="", channel="", chat_id="", on_stream=None, on_stream_end=None):
        await asyncio.sleep(10)  # longer than timeout
        return "nope"

    agent = MagicMock()
    agent.process_direct = slow_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m", request_timeout=0.1)
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status == 200
    body = b""
    async for chunk in resp.content.iter_any():
        body += chunk
    assert b"data: [DONE]" in body
```

- [ ] **Step 3: 新增测试 — SSE 包含正确的 role chunk**

在上一测试后添加：

```python
@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_first_chunk_contains_role(aiohttp_client) -> None:
    """First SSE chunk must contain delta.role=assistant (OpenAI client requirement)."""
    async def fake_process(content, session_key="", channel="", chat_id="", on_stream=None, on_stream_end=None):
        if on_stream:
            await on_stream("Hi")
        if on_stream_end:
            await on_stream_end(resuming=False)
        return "Hi"

    mock_agent = MagicMock()
    mock_agent.process_direct = fake_process
    mock_agent._connect_mcp = AsyncMock()
    mock_agent.close_mcp = AsyncMock()

    app = create_app(mock_agent, model_name="test-model")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert resp.status == 200

    body = b""
    async for chunk in resp.content.iter_any():
        body += chunk

    import json
    lines = body.decode().strip().split("\n")
    first_data = json.loads(lines[0][6:])
    assert first_data["choices"][0]["delta"].get("role") == "assistant"
```

- [ ] **Step 4: 运行完整测试套件**

Run: `pytest tests/test_openai_api.py -v`
Expected: All tests pass including new streaming tests

- [ ] **Step 5:（可选）补充一个“客户端断开”场景测试（如果 aiohttp test client 支持模拟断开）**

---

## Spec Coverage Check

| Spec Requirement | Task |
|----------------|------|
| SSE 流式返回 OpenAI 兼容格式 | Task 1 Step 2 |
| `stream=true` 检测进入 SSE 分支 | Task 1 Step 2 |
| `data: [DONE]` 结束事件 | Task 1 Step 2 (sse_end) |
| Session lock 保护 | Task 1 Step 2 |
| 超时发送 `[DONE]` 后返回 504 | Task 1 Step 2 + Task 2 Step 2 |
| 第一个 chunk 包含 `role: assistant` | Task 2 Step 3 |
| 现有测试不破坏 | Task 1 Step 4 |

## Self-Review

- `_sse_done()` 和 `_sse_chunk` 函数定义在辅助函数区，风格与非流式响应一致
- SSE 分支复用现有的 session_key、timeout_s、model_name、sender_id 解析逻辑
- `process_direct` 的 `on_stream` 和 `on_stream_end` 回调签名与 `loop.py` 定义一致
- `test_stream_true_returns_sse_chunks` 替换了原来的 `test_stream_true_returns_400`，不破坏现有测试计数
