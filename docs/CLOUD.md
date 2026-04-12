# Cloud Mode

`nanobot.cloud` is the new multi-user, multi-agent, S3-backed server mode.

It is separate from the original local mode:

- local mode still uses the traditional single local `config.json` + local workspace path
- cloud mode adds FastAPI + OAuth/OIDC + per-user workspaces backed by S3-compatible storage

## Environment Variables

Cloud mode reads settings from `.env` / environment variables using the `NANOBOT_CLOUD_` prefix.

See [`.env.example`](../.env.example) for the full list.

### Required variables

- `NANOBOT_CLOUD_NANOBOT_CONFIG_PATH`
- `NANOBOT_CLOUD_S3__BUCKET`
- One of:
  - `NANOBOT_CLOUD_AUTH__JWKS_URL`
  - `NANOBOT_CLOUD_AUTH__SHARED_SECRET`

### Common optional variables

- `NANOBOT_CLOUD_LOCAL_CACHE_DIR`
- `NANOBOT_CLOUD_HOST`
- `NANOBOT_CLOUD_PORT`
- `NANOBOT_CLOUD_REQUEST_TIMEOUT`
- `NANOBOT_CLOUD_WORKSPACE_PREFIX`
- `NANOBOT_CLOUD_REDIS__URL`
- `NANOBOT_CLOUD_REDIS__KEY_PREFIX`
- `NANOBOT_CLOUD_REDIS__SESSION_TTL_S`
- `NANOBOT_CLOUD_REDIS__LOCK_TTL_S`
- `NANOBOT_CLOUD_AUTH__ISSUER`
- `NANOBOT_CLOUD_AUTH__AUDIENCE`
- `NANOBOT_CLOUD_AUTH__USER_ID_CLAIM`
- `NANOBOT_CLOUD_AUTH__ALGORITHMS`
- `NANOBOT_CLOUD_S3__PREFIX`
- `NANOBOT_CLOUD_S3__ENDPOINT_URL`
- `NANOBOT_CLOUD_S3__REGION_NAME`
- `NANOBOT_CLOUD_S3__ACCESS_KEY_ID`
- `NANOBOT_CLOUD_S3__SECRET_ACCESS_KEY`

## Config Ownership

Cloud mode has two configuration layers:

1. Platform-level config
2. User/agent-level cloud config

Runtime state in the current stateless multi-instance design is split across:

- `Redis` for online session state and distributed locks
- `S3` for durable workspace files and long-term artifacts
- local disk only for request-scoped temporary execution directories

### 1. Platform-level config

This is the file pointed to by `NANOBOT_CLOUD_NANOBOT_CONFIG_PATH`.

It is a **local filesystem path on the cloud service machine**, not an S3 URL.

It is **not** stored under a user workspace.
It defines the platform-managed provider/model/tools defaults used by cloud mode.

Typical responsibilities:

- managed provider credentials
- managed model selection
- default tool settings
- default retry/window/session behavior

Example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-..."
    }
  },
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "openai/gpt-4.1",
      "temperature": 0.1,
      "maxToolIterations": 200,
      "contextWindowTokens": 65536,
      "maxToolResultChars": 16000,
      "providerRetryMode": "standard",
      "timezone": "UTC",
      "sessionTtlMinutes": 0
    }
  },
  "tools": {
    "web": {
      "enable": true
    },
    "exec": {
      "enable": true
    }
  }
}
```

A ready-to-copy example is provided at [platform-config.json.example](/home/fweil/gitprojects/nanobot/platform-config.json.example).

In cloud mode, provider/model are platform-managed.
Users do not choose their own provider/model from workspace config.

### 2. User-level config

Each user has a root config at:

`workspaces/{user_id}/config.json`

This file is **based on `user_id`**, not on a single agent.
It acts as the workspace index for that user.

Responsibilities:

- identify the owner user
- define the default agent
- expose the managed provider/model view
- index the user's available agents

Example:

```json
{
  "schema_version": 1,
  "user_id": "user_123",
  "default_agent": "default",
  "providers": {
    "managed": {
      "provider": "openrouter",
      "model": "openai/gpt-4.1",
      "managed": true
    }
  },
  "agents": {
    "default": "agents/default/config.json",
    "research": "agents/research/config.json"
  },
  "created_at": "2026-04-12T03:00:00+00:00",
  "updated_at": "2026-04-12T03:00:00+00:00"
}
```

### 3. Agent-level config

Each agent has its own independent config at:

`workspaces/{user_id}/agents/{agent_name}/config.json`

This file is **agent-specific**.
It defines behavior overrides for that one agent only.

Responsibilities:

- agent name / description
- enabled skills for this agent
- runtime overrides on top of platform defaults

Current supported agent-level fields:

- `name`
- `description`
- `skills`
- `temperature`
- `max_tokens`
- `context_window_tokens`
- `context_block_limit`
- `max_tool_iterations`
- `max_tool_result_chars`
- `provider_retry_mode`
- `reasoning_effort`
- `timezone`
- `unified_session`
- `session_ttl_minutes`

Example:

```json
{
  "name": "research",
  "description": "Research-focused agent",
  "skills": ["web-search", "memory"],
  "temperature": 0.2,
  "max_tokens": 8192,
  "max_tool_iterations": 300,
  "reasoning_effort": "high",
  "timezone": "Asia/Shanghai",
  "session_ttl_minutes": 60,
  "created_at": "2026-04-12T03:00:00+00:00",
  "updated_at": "2026-04-12T03:00:00+00:00"
}
```

## Which `config.json` should I edit?

Short answer:

- Edit `workspaces/{user_id}/config.json` when you are managing the user's agent index and default agent
- Edit `workspaces/{user_id}/agents/{agent_name}/config.json` when you are configuring one specific agent

So the answer is:

- root `config.json` is **user-based**
- per-agent `config.json` is **agent-based**

They are not alternatives; they are two layers.

## Skills Layout

Skills are selected per agent, but persisted in user workspace storage.

Possible storage locations:

- workspace-level custom skills:
  - `workspaces/{user_id}/skills/{skill_name}/`
- agent-level custom skills:
  - `workspaces/{user_id}/agents/{agent_name}/skills/{skill_name}/`

At runtime, cloud mode only exposes the current agent's declared skills.
Undeclared skills are hidden from the runtime workspace.

## Sessions

Sessions are isolated by:

`user_id + agent_name + session_id`

This means:

- different users are isolated
- different agents under the same user are isolated
- different `session_id` values under the same user+agent are isolated

Online session truth lives in `Redis`.
Durable workspace/session artifacts can still be archived through the S3-backed workspace.
Instances are expected to be stateless across requests.

## First Login Bootstrap

On first authenticated access, cloud mode initializes:

- `workspaces/{user_id}/`
- `workspaces/{user_id}/config.json`
- `workspaces/{user_id}/agents/default/config.json`
- standard workspace templates such as memory files

## Running Cloud Mode

After preparing `.env`:

```bash
uv run --extra cloud nanobot-cloud
```

For local MinIO development, set:

- `NANOBOT_CLOUD_S3__ENDPOINT_URL`
- `NANOBOT_CLOUD_S3__ACCESS_KEY_ID`
- `NANOBOT_CLOUD_S3__SECRET_ACCESS_KEY`
- `NANOBOT_CLOUD_S3__BUCKET`

For stateless multi-instance development, also set:

- `NANOBOT_CLOUD_REDIS__URL`

## Real E2E Validation

This section records a real local validation flow that was executed in WSL2 against:

- Redis on `127.0.0.1:6379`
- MinIO on `http://127.0.0.1:9000`
- a real provider from local `platform-config.json`

It is intended as a repeatable smoke test, not just a conceptual example.

### Local Prerequisites

- WSL2 shell
- repo at `/home/fweil/gitprojects/nanobot`
- `platform-config.json` contains a real, working provider key
- Redis running locally
- MinIO running locally

### Example local services

The validation run used:

- Redis:
  - host: `127.0.0.1`
  - port: `6379`
  - password: `123456`
- MinIO:
  - endpoint: `http://127.0.0.1:9000`
  - access key: `admin`
  - secret key: `password123`
  - bucket: `nanobot-cloud`

Adjust these if your local setup differs.

### 1. Verify Redis and MinIO connectivity

```bash
cd /home/fweil/gitprojects/nanobot

uv run --extra cloud python - <<'PY'
import asyncio
from redis.asyncio import Redis
import boto3

async def main():
    r = Redis.from_url('redis://:123456@127.0.0.1:6379/0', encoding='utf-8', decode_responses=True)
    try:
        await r.ping()
        print('redis=ok')
    finally:
        await r.aclose()

    s3 = boto3.client(
        's3',
        endpoint_url='http://127.0.0.1:9000',
        region_name='us-east-1',
        aws_access_key_id='admin',
        aws_secret_access_key='password123',
    )
    print('minio_list_buckets_ok=', isinstance(s3.list_buckets().get('Buckets', []), list))

asyncio.run(main())
PY
```

Expected result:

- `redis=ok`
- `minio_list_buckets_ok= True`

### 2. Make sure the MinIO bucket exists

```bash
uv run --extra cloud python - <<'PY'
import boto3

s3 = boto3.client(
    's3',
    endpoint_url='http://127.0.0.1:9000',
    region_name='us-east-1',
    aws_access_key_id='admin',
    aws_secret_access_key='password123',
)

try:
    s3.head_bucket(Bucket='nanobot-cloud')
    print('bucket_exists')
except Exception:
    s3.create_bucket(Bucket='nanobot-cloud')
    print('bucket_created')
PY
```

### 3. Start the cloud service in WSL2

Use a dedicated Redis key prefix and S3 prefix for one validation run:

```bash
export NANOBOT_CLOUD_NANOBOT_CONFIG_PATH=/home/fweil/gitprojects/nanobot/platform-config.json
export NANOBOT_CLOUD_LOCAL_CACHE_DIR=/tmp/nanobot-cloud-manual
export NANOBOT_CLOUD_HOST=127.0.0.1
export NANOBOT_CLOUD_PORT=8890
export NANOBOT_CLOUD_REQUEST_TIMEOUT=60
export NANOBOT_CLOUD_WORKSPACE_PREFIX=workspaces

export NANOBOT_CLOUD_REDIS__URL='redis://:123456@127.0.0.1:6379/0'
export NANOBOT_CLOUD_REDIS__KEY_PREFIX='nanobot-cloud-e2e:e2e-manual-1775971831-588c77'
export NANOBOT_CLOUD_REDIS__SESSION_TTL_S=3600
export NANOBOT_CLOUD_REDIS__LOCK_TTL_S=120

export NANOBOT_CLOUD_AUTH__ISSUER='nanobot-cloud-e2e'
export NANOBOT_CLOUD_AUTH__AUDIENCE='nanobot-cloud'
export NANOBOT_CLOUD_AUTH__USER_ID_CLAIM='sub'
export NANOBOT_CLOUD_AUTH__ALGORITHMS='["HS256"]'
export NANOBOT_CLOUD_AUTH__SHARED_SECRET='manual-e2e-long-secret-1234567890'

export NANOBOT_CLOUD_S3__BUCKET='nanobot-cloud'
export NANOBOT_CLOUD_S3__PREFIX='e2e-manual-1775971831-588c77'
export NANOBOT_CLOUD_S3__ENDPOINT_URL='http://127.0.0.1:9000'
export NANOBOT_CLOUD_S3__REGION_NAME='us-east-1'
export NANOBOT_CLOUD_S3__ACCESS_KEY_ID='admin'
export NANOBOT_CLOUD_S3__SECRET_ACCESS_KEY='password123'

uv run --extra cloud nanobot-cloud
```

Expected startup log:

- `Application startup complete.`
- `Uvicorn running on http://127.0.0.1:8890`

### 4. Verify health and model listing

In another WSL2 terminal:

```bash
cd /home/fweil/gitprojects/nanobot

uv run --extra cloud python - <<'PY'
import httpx

print('health=', httpx.get('http://127.0.0.1:8890/health', timeout=5).text)
print('models=', httpx.get('http://127.0.0.1:8890/v1/models', timeout=5).text)
PY
```

Expected result:

- `health= {"status":"ok"}`
- `/v1/models` returns the platform-managed model from `platform-config.json`

### 5. Generate local HS256 bearer tokens

```bash
uv run --extra cloud python - <<'PY'
import jwt, time

secret = 'manual-e2e-long-secret-1234567890'
for user in ('alice', 'bob'):
    payload = {
        'sub': user,
        'iss': 'nanobot-cloud-e2e',
        'aud': 'nanobot-cloud',
        'iat': int(time.time()),
        'exp': int(time.time()) + 3600,
    }
    print(user, jwt.encode(payload, secret, algorithm='HS256'))
PY
```

### 6. Verify first-login bootstrap for two users

Using the generated tokens:

```bash
uv run --extra cloud python - <<'PY'
import httpx

ALICE='PASTE_ALICE_TOKEN_HERE'
BOB='PASTE_BOB_TOKEN_HERE'

client = httpx.Client(timeout=10)
print('alice_agents=', client.get('http://127.0.0.1:8890/v1/agents', headers={'Authorization': f'Bearer {ALICE}'}).text)
print('bob_agents=', client.get('http://127.0.0.1:8890/v1/agents', headers={'Authorization': f'Bearer {BOB}'}).text)
PY
```

Expected result:

- both users return `default` agent
- this confirms auth, first login bootstrap, and per-user workspace creation

### 7. Real chat validation for Alice

```bash
uv run --extra cloud python - <<'PY'
import httpx, time

ALICE='PASTE_ALICE_TOKEN_HERE'
payload = {
    'agent': 'default',
    'session_id': 'manual-thread-1',
    'messages': [{'role': 'user', 'content': 'Reply with exactly: ALICE_OK'}],
}

start = time.time()
r = httpx.post(
    'http://127.0.0.1:8890/v1/chat/completions',
    headers={'Authorization': f'Bearer {ALICE}'},
    json=payload,
    timeout=90,
)
print('elapsed=', round(time.time() - start, 2))
print('status=', r.status_code)
print(r.text[:4000])
PY
```

Observed result from the real run:

- HTTP `200`
- model: `MiniMax-M2.7`
- assistant content: `ALICE_OK`

### 8. Real chat validation for Bob with the same raw session id

```bash
uv run --extra cloud python - <<'PY'
import httpx, time

BOB='PASTE_BOB_TOKEN_HERE'
payload = {
    'agent': 'default',
    'session_id': 'manual-thread-1',
    'messages': [{'role': 'user', 'content': 'Reply with exactly: BOB_OK'}],
}

start = time.time()
r = httpx.post(
    'http://127.0.0.1:8890/v1/chat/completions',
    headers={'Authorization': f'Bearer {BOB}'},
    json=payload,
    timeout=90,
)
print('elapsed=', round(time.time() - start, 2))
print('status=', r.status_code)
print(r.text[:4000])
PY
```

Observed result from the real run:

- HTTP `200`
- assistant content: `BOB_OK`

This validates that the same raw `session_id` is still isolated by:

- `user_id`
- `agent_name`
- `session_id`

### 9. Check durable state in MinIO

```bash
uv run --extra cloud python - <<'PY'
import boto3

s3 = boto3.client(
    's3',
    endpoint_url='http://127.0.0.1:9000',
    region_name='us-east-1',
    aws_access_key_id='admin',
    aws_secret_access_key='password123',
)

for user in ('alice', 'bob'):
    resp = s3.list_objects_v2(
        Bucket='nanobot-cloud',
        Prefix=f'e2e-manual-1775971831-588c77/workspaces/{user}/sessions/',
    )
    print(user, [x['Key'] for x in resp.get('Contents', [])])
PY
```

Observed result from the real run:

- Alice session file existed:
  - `.../workspaces/alice/sessions/cloud_alice_default_manual-thread-1.jsonl`
- Bob session file existed:
  - `.../workspaces/bob/sessions/cloud_bob_default_manual-thread-1.jsonl`

### 10. Check online session state in Redis

```bash
uv run --extra cloud python - <<'PY'
import asyncio
from redis.asyncio import Redis

async def main():
    r = Redis.from_url('redis://:123456@127.0.0.1:6379/0', encoding='utf-8', decode_responses=False)
    try:
        keys = await r.keys('nanobot-cloud-e2e:e2e-manual-1775971831-588c77*')
        print([k.decode() if isinstance(k, bytes) else k for k in keys])
    finally:
        await r.aclose()

asyncio.run(main())
PY
```

Observed result from the real run included:

- lock key for Alice chat scope
- online session key for Alice
- online session key for Bob

### 11. Restart the cloud service and re-test Alice

Stop the service, restart it with the same environment, then run:

```bash
uv run --extra cloud python - <<'PY'
import httpx, time

ALICE='PASTE_ALICE_TOKEN_HERE'
payload = {
    'agent': 'default',
    'session_id': 'manual-thread-1',
    'messages': [{'role': 'user', 'content': 'Reply with exactly: ALICE_RESTART_OK'}],
}

start = time.time()
r = httpx.post(
    'http://127.0.0.1:8890/v1/chat/completions',
    headers={'Authorization': f'Bearer {ALICE}'},
    json=payload,
    timeout=90,
)
print('elapsed=', round(time.time() - start, 2))
print('status=', r.status_code)
print(r.text[:4000])
PY
```

Observed result from the real run:

- HTTP `200`
- assistant content: `ALICE_RESTART_OK`

This validates that:

- the service can restart cleanly
- the same `user + agent + session_id` can continue after restart
- Redis and S3 together preserve the needed state

## Real Validation Summary

This real WSL2 validation confirmed:

- Redis connectivity
- MinIO connectivity
- cloud service startup
- health and model listing
- first-login bootstrap for multiple users
- real provider-backed chat completions
- per-user isolation with the same raw `session_id`
- Redis online session keys
- MinIO durable session files
- successful post-restart chat continuation

## Staging Checklist

Use this PASS/FAIL checklist for repeatable staging validation.

| Category | Check | Method | Expected | Pass/Fail |
| --- | --- | --- | --- | --- |
| Base | Redis reachable | `PING` / app startup | Connects successfully |  |
| Base | S3/MinIO reachable | bucket list / app startup | Connects successfully |  |
| Base | `platform-config.json` valid | start service | Service boots without config error |  |
| Base | `/health` | `GET /health` | `200`, `{"status":"ok"}` |  |
| Base | `/v1/models` | `GET /v1/models` | `200`, platform model returned |  |
| Auth | Bearer token valid | `GET /v1/agents` with valid token | `200` |  |
| Auth | Missing token rejected | `GET /v1/agents` without token | `401` |  |
| Auth | Invalid token rejected | `GET /v1/agents` with bad token | `401` |  |
| Bootstrap | First login creates workspace | first `GET /v1/agents` for new user | user workspace appears in S3 |  |
| Bootstrap | First login creates default agent | first `GET /v1/agents` | `default` agent present |  |
| Chat | Non-streaming chat works | `POST /v1/chat/completions` | `200`, assistant content returned |  |
| Chat | Streaming chat works | `POST /v1/chat/completions` with `stream=true` | SSE stream + `[DONE]` |  |
| Isolation | Two users can both chat | Alice + Bob requests | both succeed |  |
| Isolation | Same raw `session_id` is isolated per user | Alice/Bob use same `session_id` | separate session state |  |
| Session | Redis online session created | inspect Redis keys | session key exists per `user+agent+session` |  |
| Session | S3 durable session file created | inspect S3 prefix | session `.jsonl` file exists |  |
| Restart | Service restart preserves session continuity | stop/start service, re-chat same session | same user/session continues successfully |  |
| Locking | Concurrent write conflict | send 2 writes to same `user+agent+session` | one success, one `409 session_locked` |  |
| Budget | Non-stream budget exceeded path | set tiny skill budget, call non-stream chat | `507 skill_stage_budget_exceeded` |  |
| Budget | Stream budget exceeded path | set tiny skill budget, call `stream=true` | deterministic error, no server crash |  |
| Skills | Small skill runs correctly | attach small skill to agent and chat | expected behavior |  |
| Skills | Small skill can reuse cache | repeat same request | behavior unchanged, lower remote fetches if measured |  |
| Skills | Large skill runs correctly | attach large skill to agent and chat | expected behavior |  |
| Skills | Large skill not stored as Redis full-content cache by default | inspect Redis keys/size | no large bundle content retention |  |
| Skills | Missing skill non-stream | reference missing skill | deterministic error (`404`) |  |
| Skills | Missing skill stream | reference missing skill with `stream=true` | deterministic error, no `response already started` crash |  |
| Skills | Immutable bundle consistency | same skill on 2 instances | same bundle revision/object set |  |
| Local FS | Request temp dirs cleaned up | inspect local cache dir after request | temp dirs removed |  |
| Local FS | Local disk budget respected | monitor local cache usage under load | does not exceed configured bounds |  |
| Metrics | S3 fetch metrics visible | logs/metrics | request/object counts visible |  |
| Metrics | Redis skill/session metrics visible | logs/metrics | key counts / bytes / hits visible |  |
| Regression | Existing OpenAI API tests still pass in CI | run regression suite | pass |  |

### Suggested Evidence To Save

- service startup logs
- one successful non-stream response
- one successful stream transcript
- Redis key snapshot
- S3 object listing for two users
- one `409 session_locked` response
- one `507 skill_stage_budget_exceeded` response
- post-restart successful chat response

### Minimal Commands

Health:

```bash
curl http://127.0.0.1:8890/health
```

Models:

```bash
curl http://127.0.0.1:8890/v1/models
```

Agents:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8890/v1/agents
```

Real end-to-end flow:

```bash
uv run --extra cloud python test_cloud_api.py \
  --platform-config /path/to/platform-config.json \
  --redis-url redis://:PASSWORD@HOST:6379/0 \
  --s3-endpoint-url http://HOST:9000 \
  --s3-access-key-id ACCESS_KEY \
  --s3-secret-access-key SECRET_KEY \
  --s3-bucket BUCKET
```
