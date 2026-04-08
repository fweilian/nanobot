# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI agent framework (~2K lines of core agent code). It connects to multiple chat channels (Telegram, Discord, WhatsApp, WeChat, Feishu, etc.), uses layered memory (Consolidator + Dream), and exposes tools via MCP or built-in implementations.

**Branching model**: `main` = stable releases, `nightly` = experimental features. Bug fixes → `main`, new features → `nightly`.

## Development Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/agent/test_loop.py

# Lint (flake-like rules E, F, I, N, W; line-length 100)
ruff check nanobot/

# Format
ruff format nanobot/

# Type check (if present)
ruff check nanobot/ --select F401,F841  # CI lints this way
```

**CI**: Runs on ubuntu with Python 3.11–3.13, installs via `uv sync --all-extras`, lints with `ruff`, runs `pytest tests/`.

## Cloud Storage (COS)

When `cloud_storage` is configured in `config.json`, nanobot uses COS (Tencent Cloud Object Storage) via S3-compatible API instead of local disk.

Config example:
```json
{
  "cloud_storage": {
    "provider": "cos",
    "endpoint_url": "https://cos.ap-beijing.myqcloud.com",
    "bucket": "your-bucket",
    "region": "ap-beijing",
    "secret_id": "${COS_SECRET_ID}",
    "secret_key": "${COS_SECRET_KEY}",
    "prefix": "mclaw/"
  }
}
```

- All nanobot data (memory, sessions, tool results) is stored under the `prefix` path in the bucket
- When `cloud_storage` is absent, nanobot uses local filesystem (default behavior)
- GitStore version control is disabled in cloud mode
- Storage interface is defined in `nanobot/providers/cloud_storage.py`

## Architecture

```
nanobot/
├── agent/              # Core agent runtime
│   ├── loop.py         # Async message loop (consume → process → respond)
│   ├── context.py      # Builds prompt messages from history + templates
│   ├── runner.py       # LLM tool-calling loop via provider SDK
│   ├── memory.py       # Session + Consolidator (history.jsonl summarization)
│   ├── skills.py       # Loads *.md skill files as agent capabilities
│   ├── subagent.py     # Background/spawned task execution
│   ├── hook.py         # AgentHook lifecycle (before/after execute tools, etc.)
│   └── tools/          # Built-in tools: cron, filesystem, shell, spawn, web, mcp, search, message
├── channels/           # Chat platform integrations (plugin-style)
│   ├── manager.py      # Routes inbound/outbound across channels
│   ├── registry.py     # Channel plugin registry
│   ├── telegram.py, discord.py, feishu.py, etc.
├── providers/          # LLM provider SDK wrappers
│   ├── registry.py     # ProviderSpec registry — adding a provider = 2-step
│   ├── base.py         # Base provider interface
│   ├── openai_compat_provider.py   # OpenAI-compatible (OpenRouter, Ollama, etc.)
│   ├── anthropic_provider.py       # Direct Anthropic
│   ├── azure_openai_provider.py, etc.
├── config/
│   ├── schema.py       # Pydantic config models
│   ├── loader.py       # JSON config loading + env var interpolation
├── bus/                # Async message queue (inbound/outbound routing)
├── cli/                # Typer CLI commands (agent, gateway, onboard, serve)
├── skills/            # Bundled skills (github, weather, tmux, cron, etc.)
├── templates/         # Agent prompt templates (SOUL.md, USER.md, HEARTBEAT.md, TOOLS.md)
```

### Key Design Patterns

**Provider Registry** (`providers/registry.py`): Adding a new LLM provider = (1) add `ProviderSpec` entry, (2) add field to `ProvidersConfig` in schema.py. No if-elif chains.

**Channel Plugins**: Channels self-register via `nanobot.channels.registry`. Each channel implements `BaseChannel` (inbound/outbound interface). See `docs/CHANNEL_PLUGIN_GUIDE.md`.

**Tool System**: Tools are registered in `ToolRegistry`. Built-in tools live in `agent/tools/`. MCP tools are auto-discovered and wrapped. Tools receive a `ToolContext` with channel, chat_id, workspace info.

**Memory Layers**:
1. `session.messages` — short-term conversation
2. `memory/history.jsonl` — append-only summarized history (Consolidator)
3. `SOUL.md`, `USER.md`, `memory/MEMORY.md` — long-term knowledge (Dream, runs on schedule)

**Runtime Loop**: `AgentLoop.run()` consumes from `bus`, dispatches per-session (serial) with cross-session concurrency. Checkpoints unfinished turns into session metadata for crash recovery.

**Async Throughout**: Uses `asyncio`, pytest with `asyncio_mode = "auto"`. No `async def` inside sync functions that don't await.

## Config

Config file: `~/.nanobot/config.json` (or `--config` for multi-instance). Schema in `nanobot/config/schema.py`. Secrets support `${ENV_VAR}` interpolation.

## Skills

Skills are `.md` files loaded by `agent/skills.py`. Bundled skills in `nanobot/skills/` (github, weather, tmux, cron, memory, summarize, clawhub, skill-creator). Each skill has a `SKILL.md` that defines its name, description, prompt, and optional scripts.
