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

Session files are persisted through the S3-backed workspace, so they survive service restarts.

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
