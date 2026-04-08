# Channel/Provider Simplification Design

**Date**: 2026-04-08
**Status**: Approved

## Goals

- Remove all built-in channel implementations (Feishu, Telegram, Discord, etc.)
- Remove all LLM providers except `openai` and `custom`
- Preserve the channel plugin architecture for future internal channels
- Gateway logic remains unchanged

## Deleted Files

### Channels
- `nanobot/channels/feishu.py`

### Providers
- `nanobot/providers/anthropic_provider.py`
- `nanobot/providers/azure_openai_provider.py`
- `nanobot/providers/openai_codex_provider.py`
- `nanobot/providers/github_copilot_provider.py`
- `nanobot/providers/openai_compat_provider.py` (merged into single file)

> All other provider implementation files beyond `openai` and `custom` backends.

## Changed Files

### `nanobot/providers/registry.py`

**Before**: ~360 lines, 20+ `ProviderSpec` entries
**After**: 2 entries

```python
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        supports_max_completion_tokens=True,
    ),
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        backend="openai_compat",
        is_direct=True,
    ),
)
```

### `nanobot/config/schema.py`

**ProvidersConfig** — simplified to only `openai` and `custom`:

```python
class ProviderConfig(Base):
    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None

class ProvidersConfig(Base):
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    custom: ProviderConfig = Field(default_factory=ProviderConfig)
```

**FeishuConfig** — deleted entirely.

**ChannelsConfig** — `extra="allow"` kept so custom channel plugins can add their own config fields. `transcription_provider` field kept but not used by any built-in channel.

### `nanobot/channels/__init__.py`

Remove Feishu export.

### `nanobot/channels/manager.py`

- `_resolve_transcription_key()` — removed (only Feishu used this)
- `discover_all()` behavior unchanged — will find 0 built-in channels, custom plugins work normally
- `_init_channels()` — removes transcription key resolution

### `nanobot/nanobot.py`

`_make_provider()` — unchanged. Logic is provider-backend driven; with only `openai_compat` backends remaining, behavior is identical.

### `nanobot/cli/commands.py`

- **`status`** — simplify to only show `openai` and `custom` API key status
- **`provider login`** — removed (no OAuth providers remain)
- `channels status`, `channels login`, `plugins list` — unchanged (will show 0 built-in channels, custom plugins work)
- `_make_provider()` in CLI — unchanged

### `nanobot/providers/__init__.py`

Remove exports for deleted providers.

### `nanobot/providers/base.py`

Retained as-is (no changes needed).

## Dependency Cleanup

### Removed from `dependencies` in `pyproject.toml`

| Package | Reason |
|---------|--------|
| `anthropic` | Anthropic provider deleted |
| `oauth-cli-kit` | OAuth providers (OpenAI Codex, GitHub Copilot) deleted |
| `dingtalk-stream` | DingTalk channel deleted |
| `python-telegram-bot[socks]` | Telegram channel deleted |
| `lark-oapi` | Feishu channel deleted |
| `socksio` | SOCKS support — only used by deleted channels (telegram, wecom, qq) |
| `slack-sdk` | Slack channel deleted |
| `slackify-markdown` | Slack channel deleted |
| `qq-botpy` | QQ channel deleted |
| `python-socks[asyncio]` | SOCKS support — only used by deleted channels |
| `websocket-client` | WhatsApp channel deleted |
| `websockets` | WhatsApp channel deleted |
| `python-socketio` | Mochat channel deleted |
| `msgpack` | Mochat channel deleted |
| `chardet` | Not used anywhere in codebase |

### Removed from `optional-dependencies`

- `wecom` — WeCom channel deleted
- `weixin` — WeChat channel deleted
- `matrix` — Matrix channel deleted
- `discord` — Discord channel deleted

## Preserved Architecture

### Channel Plugin System (unchanged)
- `channels/registry.py` — `discover_all()`, `discover_channel_names()`, `discover_plugins()` remain
- `channels/base.py` — `BaseChannel` interface unchanged
- `channels/manager.py` — `ChannelManager` unchanged (works with 0 discovered channels)

Internal channels added later as plugins will use the existing discovery mechanism.

### Provider System (simplified)
- `providers/registry.py` — only `openai` and `custom` specs
- `providers/openai_compat_provider.py` — handles both `openai` and `custom` (via `spec.name` distinction)
- `providers/base.py` — unchanged

### Gateway Logic (unchanged)
`nanobot gateway` initializes `ChannelManager`, which calls `discover_all()`. With no built-in channels, it starts with an empty channel dict — this is already a valid state (tested by the "no channels enabled" warning path).

## Config Migration Notes

Existing configs with `providers.feishu`, `providers.anthropic`, etc. will load fine — Pydantic ignores extra fields on `ProvidersConfig`. Channels that had feishu or other deleted channels configured will also load — `ChannelsConfig` uses `extra="allow"`.

No automatic config migration is performed. Users removing the package should clean their config manually.

## Testing Notes

- `gateway` command with no channels enabled should show "No channels enabled" warning and run normally
- `provider` selection with `openai` and `custom` should work identically to before
- Channel plugin discovery should return empty dict for built-ins, custom plugins still work
