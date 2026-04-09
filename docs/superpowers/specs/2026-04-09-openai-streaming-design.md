# OpenAI 兼容 SSE 流式输出设计

## 目标

为 `/v1/chat/completions` 增加 SSE 流式返回支持，符合 OpenAI Chat Completions Streaming API 规范。

## 现状

`handle_chat_completions` 在 `stream=true` 时返回 400 错误：
```
"stream=true is not supported yet. Set stream=false or omit it."
```

## 方案

修改 `nanobot/api/server.py` 中的 `handle_chat_completions`，当 `stream=true` 时启用 SSE 模式。

### SSE 响应格式

符合 OpenAI 规范：

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"nanobot","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"nanobot","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"nanobot","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"nanobot","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 实现步骤

1. **检测 stream 参数**：当 `body.get("stream", False) == True` 时进入 SSE 分支

2. **创建 SSE Response 对象**：
   ```python
   resp = web.StreamResponse(
       status=200,
       reason="OK",
       headers={
           "Content-Type": "text/event-stream",
           "Cache-Control": "no-cache",
           "Connection": "keep-alive",
       }
   )
   await resp.prepare(request)
   ```

3. **SSE 写入函数**（作为 `on_stream` 回调）：
   - 每次 delta 到达时构造 OpenAI 格式的 chunk JSON
   - 使用 `resp.write(f"data: {json.dumps(chunk)}\n\n".encode())`

4. **流式调用 `process_direct`**：
   ```python
   response = await asyncio.wait_for(
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
   ```

5. **on_stream_end 回调**：发送最终的 `finish_reason=stop` chunk 和 `data: [DONE]`

6. **错误处理**：
   - 捕获异常后写入错误 chunk，然后关闭 SSE
   - 超时在 SSE 场景下发送 `[DONE]` 并关闭

### 关键细节

- **Session lock**：流式请求仍然在 session lock 保护下执行，但 SSE 写入在锁内进行
- **Incremental ID**：使用 `chatcmpl-{uuid}` 格式，与非流式响应保持一致
- **第一个 chunk**：必须包含 `delta: {"role": "assistant"}`，OpenAI 客户端依赖此字段
- **空内容 delta**：当某次 delta 为空时不发送，避免无效 chunk
- **keep-alive**：SSE 需要定期发送注释行防止代理超时（`// keepalive\n\n`）

### 测试

- 验证 SSE 响应头正确
- 验证 chunk 格式符合 OpenAI 规范
- 验证 `data: [DONE]` 在结束时发送
- 验证流式与非流式 session 隔离
