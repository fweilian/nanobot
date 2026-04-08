# Channel/Provider Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除所有内置 channel 实现（仅保留 plugin 架构）和除 openai/custom 外的所有 provider，清理无效依赖。

**Architecture:** 直接删除文件 + 修改少数配置。Channel plugin 架构和 Gateway 逻辑完全不变。

**Tech Stack:** Python 3.11+, Pydantic, loguru

---

## 文件变更总览

### 待删除的文件（共 36 个）

**Channels (15 个):**
```
nanobot/channels/feishu.py
nanobot/channels/dingtalk.py
nanobot/channels/discord.py
nanobot/channels/email.py
nanobot/channels/matrix.py
nanobot/channels/mochat.py
nanobot/channels/qq.py
nanobot/channels/slack.py
nanobot/channels/telegram.py
nanobot/channels/wecom.py
nanobot/channels/weixin.py
nanobot/channels/whatsapp.py
```

**Providers (5 个):**
```
nanobot/providers/anthropic_provider.py
nanobot/providers/azure_openai_provider.py
nanobot/providers/openai_codex_provider.py
nanobot/providers/github_copilot_provider.py
```

**Channel Tests (12 个):**
```
tests/channels/test_feishu_markdown_rendering.py
tests/channels/test_feishu_mention.py
tests/channels/test_feishu_mentions.py
tests/channels/test_feishu_reaction.py
tests/channels/test_feishu_reply.py
tests/channels/test_feishu_streaming.py
tests/channels/test_feishu_table_split.py
tests/channels/test_feishu_tool_hint_code_block.py
tests/channels/test_dingtalk_channel.py
tests/channels/test_discord_channel.py
tests/channels/test_email_channel.py
tests/channels/test_matrix_channel.py
tests/channels/test_qq_ack_message.py
tests/channels/test_qq_channel.py
tests/channels/test_slack_channel.py
tests/channels/test_telegram_channel.py
tests/channels/test_weixin_channel.py
tests/channels/test_whatsapp_channel.py
```

**Provider Tests (8 个):**
```
tests/providers/test_anthropic_thinking.py
tests/providers/test_azure_openai_provider.py
tests/providers/test_mistral_provider.py
tests/providers/test_openai_responses.py
tests/providers/test_stepfun_reasoning.py
tests/providers/test_litellm_kwargs.py
tests/providers/test_provider_retry.py
tests/providers/test_provider_retry_after_hints.py
tests/providers/test_provider_sdk_retry_defaults.py
```

### 待修改的文件（7 个）

```
nanobot/providers/registry.py       # 简化为 2 个 ProviderSpec
nanobot/config/schema.py            # ProvidersConfig 简化，删除 FeishuConfig
nanobot/channels/__init__.py        # 移除 feishu 导出（已无变化）
nanobot/providers/__init__.py       # 移除已删除 provider 的导出
nanobot/channels/manager.py        # 删除 _resolve_transcription_key
nanobot/cli/commands.py             # 删除 provider login，简化 status
pyproject.toml                     # 删除无效依赖
tests/providers/test_providers_init.py  # 更新导出列表
tests/channels/test_channel_plugins.py  # 移除 TelegramChannel 引用
```

---

## Task 1: 简化 `providers/registry.py`

**Files:**
- Modify: `nanobot/providers/registry.py`

- [ ] **Step 1: 备份并替换 registry.py 为简化版本**

用以下内容替换整个文件：

```python
"""Provider Registry — single source of truth for LLM provider metadata."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic.alias_generators import to_snake


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""
    backend: str = "openai_compat"
    env_extras: tuple[tuple[str, str], ...] = ()
    is_gateway: bool = False
    is_local: bool = False
    detect_by_key_prefix: str = ""
    detect_by_base_keyword: str = ""
    default_api_base: str = ""
    strip_model_prefix: bool = False
    supports_max_completion_tokens: bool = False
    model_overrides: tuple[tuple[str, dict[str, object]], ...] = ()
    is_oauth: bool = False
    is_direct: bool = False
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


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


def find_by_name(name: str) -> ProviderSpec | None:
    normalized = to_snake(name.replace("-", "_"))
    for spec in PROVIDERS:
        if spec.name == normalized:
            return spec
    return None
```

- [ ] **Step 2: 验证 registry 可正常导入**

Run: `python -c "from nanobot.providers.registry import PROVIDERS, find_by_name; print([s.name for s in PROVIDERS])"`
Expected: `['openai', 'custom']`

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/registry.py
git commit -m "refactor(providers): simplify registry to openai + custom only"
```

---

## Task 2: 简化 `config/schema.py`

**Files:**
- Modify: `nanobot/config/schema.py`

- [ ] **Step 1: 修改 ProvidersConfig**

将 `ProvidersConfig` 类替换为：

```python
class ProvidersConfig(Base):
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    custom: ProviderConfig = Field(default_factory=ProviderConfig)
```

删除 `FeishuConfig` 类（整个类）。

- [ ] **Step 2: 验证 config 可正常加载**

Run: `python -c "from nanobot.config.schema import Config; c = Config(); print(list(c.providers.model_fields.keys()))"`
Expected: `['openai', 'custom']`

- [ ] **Step 3: Commit**

```bash
git add nanobot/config/schema.py
git commit -m "refactor(config): simplify ProvidersConfig to openai + custom, remove FeishuConfig"
```

---

## Task 3: 简化 `providers/__init__.py`

**Files:**
- Modify: `nanobot/providers/__init__.py`

- [ ] **Step 1: 替换为简化版本**

```python
"""LLM provider abstraction module."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from nanobot.providers.base import LLMProvider, LLMResponse

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "OpenAICompatProvider",
]

_LAZY_IMPORTS = {
    "OpenAICompatProvider": ".openai_compat_provider",
}

if TYPE_CHECKING:
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def __getattr__(name: str):
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from nanobot.providers import OpenAICompatProvider; print(OpenAICompatProvider.__name__)"`
Expected: `OpenAICompatProvider`

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/__init__.py
git commit -m "refactor(providers): remove deleted provider exports"
```

---

## Task 4: 更新 `providers/test_providers_init.py`

**Files:**
- Modify: `tests/providers/test_providers_init.py`

- [ ] **Step 1: 更新测试**

将 `test_importing_providers_package_is_lazy` 中的断言更新：

```python
def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "nanobot.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nanobot.providers.openai_compat_provider", raising=False)

    providers = importlib.import_module("nanobot.providers")

    assert "nanobot.providers.openai_compat_provider" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "OpenAICompatProvider",
    ]
```

删除 `test_explicit_provider_import_still_works`（测试已删除的 AnthropicProvider）。

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/providers/test_providers_init.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/providers/test_providers_init.py
git commit -m "test: update provider init tests for openai/custom only"
```

---

## Task 5: 更新 `channels/manager.py`

**Files:**
- Modify: `nanobot/channels/manager.py`

- [ ] **Step 1: 删除 `_resolve_transcription_key` 方法**

删除以下整个方法：

```python
def _resolve_transcription_key(self, provider: str) -> str:
    """Pick the API key for the configured transcription provider."""
    try:
        if provider == "openai":
            return self.config.providers.openai.api_key
        return self.config.providers.groq.api_key
    except AttributeError:
        return ""
```

删除 `transcription_provider` 和 `transcription_key` 相关的初始化代码（`_init_channels` 中）。同时删除 `_init_channels` 中这两行：

```python
channel.transcription_provider = transcription_provider
channel.transcription_api_key = transcription_key
```

- [ ] **Step 2: 验证 Manager 可正常导入**

Run: `python -c "from nanobot.channels.manager import ChannelManager; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add nanobot/channels/manager.py
git commit -m "refactor(channels): remove transcription key resolution (feishu-only feature)"
```

---

## Task 6: 更新 `cli/commands.py`

**Files:**
- Modify: `nanobot/cli/commands.py`

- [ ] **Step 1: 删除 provider login 相关代码**

删除以下内容：
- `provider_app = typer.Typer(...)` 整个 typer app 及其命令
- `_LOGIN_HANDLERS` dict 和 `_register_login` 装饰器
- `_login_openai_codex` 函数
- `_login_github_copilot` 函数
- `app.add_typer(provider_app, ...)` 这一行

- [ ] **Step 2: 简化 status 命令中的 provider 显示逻辑**

将 `status` 命令中的 provider 显示部分从遍历所有 `PROVIDERS` 简化为只显示 `openai` 和 `custom`：

```python
# 简化后的 provider 显示逻辑（status 命令函数中）
console.print(f"Model: {config.agents.defaults.model}")

# 只检查 openai 和 custom
for name in ("openai", "custom"):
    p = getattr(config.providers, name, None)
    if p:
        has_key = bool(p.api_key)
        console.print(f"{name.title()}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")
```

- [ ] **Step 3: 简化 `_make_provider` 函数**

删除 `backend == "openai_codex"` 和 `backend == "github_copilot"` 的分支，删除 `backend == "anthropic"` 的分支（保留 `else` 分支作为 openai_compat）。更新 `_make_provider` 的注释说明只有 openai 和 custom。

同时更新 `_make_provider` 的 import 部分 — 删除 `AnthropicProvider` 的 import。

- [ ] **Step 4: 验证 CLI 可正常导入**

Run: `python -c "from nanobot.cli.commands import app; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add nanobot/cli/commands.py
git commit -m "refactor(cli): remove provider login, simplify status for openai/custom"
```

---

## Task 7: 更新 `pyproject.toml` 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 从 dependencies 中删除以下行**

删除：
- `anthropic>=0.45.0,<1.0.0`
- `oauth-cli-kit>=0.1.3,<1.0.0`
- `dingtalk-stream>=0.24.0,<1.0.0`
- `python-telegram-bot[socks]>=22.6,<23.0`
- `lark-oapi>=1.5.0,<2.0.0`
- `socksio>=1.0.0,<2.0.0`
- `slack-sdk>=3.39.0,<4.0.0`
- `slackify-markdown>=0.2.0,<1.0.0`
- `qq-botpy>=1.2.0,<2.0.0`
- `python-socks[asyncio]>=2.8.0,<3.0.0`
- `websocket-client>=1.9.0,<2.0.0`
- `websockets>=16.0,<17.0`
- `python-socketio>=5.16.0,<6.0.0`
- `msgpack>=1.1.0,<2.0.0`
- `chardet>=3.0.2,<6.0.0`

- [ ] **Step 2: 从 optional-dependencies 中删除以下整个 section**

删除：
- `wecom = [...]`
- `weixin = [...]`
- `matrix = [...]`
- `discord = [...]`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: remove unused dependencies for deleted channels/providers"
```

---

## Task 8: 删除 Channel 文件

**Files:**
- Delete: `nanobot/channels/feishu.py`
- Delete: `nanobot/channels/dingtalk.py`
- Delete: `nanobot/channels/discord.py`
- Delete: `nanobot/channels/email.py`
- Delete: `nanobot/channels/matrix.py`
- Delete: `nanobot/channels/mochat.py`
- Delete: `nanobot/channels/qq.py`
- Delete: `nanobot/channels/slack.py`
- Delete: `nanobot/channels/telegram.py`
- Delete: `nanobot/channels/wecom.py`
- Delete: `nanobot/channels/weixin.py`
- Delete: `nanobot/channels/whatsapp.py`

- [ ] **Step 1: 批量删除所有 channel 文件**

```bash
git rm nanobot/channels/feishu.py nanobot/channels/dingtalk.py nanobot/channels/discord.py nanobot/channels/email.py nanobot/channels/matrix.py nanobot/channels/mochat.py nanobot/channels/qq.py nanobot/channels/slack.py nanobot/channels/telegram.py nanobot/channels/wecom.py nanobot/channels/weixin.py nanobot/channels/whatsapp.py
```

- [ ] **Step 2: 验证 channel registry 正常工作**

Run: `python -c "from nanobot.channels.registry import discover_all; print(discover_all())"`
Expected: `{}`（无内置 channel）

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove all built-in channel implementations"
```

---

## Task 9: 删除 Provider 文件

**Files:**
- Delete: `nanobot/providers/anthropic_provider.py`
- Delete: `nanobot/providers/azure_openai_provider.py`
- Delete: `nanobot/providers/openai_codex_provider.py`
- Delete: `nanobot/providers/github_copilot_provider.py`

- [ ] **Step 1: 删除 provider 文件**

```bash
git rm nanobot/providers/anthropic_provider.py nanobot/providers/azure_openai_provider.py nanobot/providers/openai_codex_provider.py nanobot/providers/github_copilot_provider.py
```

- [ ] **Step 2: 验证 provider 导入仍然正常**

Run: `python -c "from nanobot.providers import OpenAICompatProvider; print(OpenAICompatProvider.__name__)"`
Expected: `OpenAICompatProvider`

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove deleted provider implementations"
```

---

## Task 10: 删除 Channel 测试文件

**Files:**
- Delete: `tests/channels/test_feishu_*.py`（8 个文件）
- Delete: `tests/channels/test_dingtalk_channel.py`
- Delete: `tests/channels/test_discord_channel.py`
- Delete: `tests/channels/test_email_channel.py`
- Delete: `tests/channels/test_matrix_channel.py`
- Delete: `tests/channels/test_qq_ack_message.py`
- Delete: `tests/channels/test_qq_channel.py`
- Delete: `tests/channels/test_slack_channel.py`
- Delete: `tests/channels/test_telegram_channel.py`
- Delete: `tests/channels/test_weixin_channel.py`
- Delete: `tests/channels/test_whatsapp_channel.py`

- [ ] **Step 1: 删除所有 channel 测试文件**

```bash
git rm tests/channels/test_feishu_*.py tests/channels/test_dingtalk_channel.py tests/channels/test_discord_channel.py tests/channels/test_email_channel.py tests/channels/test_matrix_channel.py tests/channels/test_qq_ack_message.py tests/channels/test_qq_channel.py tests/channels/test_slack_channel.py tests/channels/test_telegram_channel.py tests/channels/test_weixin_channel.py tests/channels/test_whatsapp_channel.py
```

- [ ] **Step 2: 更新 test_channel_plugins.py 中引用 TelegramChannel 的测试**

`test_builtin_channel_default_config` 和 `test_builtin_channel_init_from_dict` 这两个测试引用了已删除的 `TelegramChannel`。需要修改这两个测试或将其删除。

最简单的处理方式是删除这两个测试函数（它们测试的是已删除的 channel），保留文件中其他测试。

在 `test_channel_plugins.py` 中删除：
```python
def test_builtin_channel_default_config():
    """Built-in channels expose default_config() returning a dict with 'enabled': False."""
    from nanobot.channels.telegram import TelegramChannel
    cfg = TelegramChannel.default_config()
    assert isinstance(cfg, dict)
    assert cfg["enabled"] is False
    assert "token" in cfg


def test_builtin_channel_init_from_dict():
    """Built-in channels accept a raw dict and convert to Pydantic internally."""
    from nanobot.channels.telegram import TelegramChannel
    bus = MessageBus()
    ch = TelegramChannel({"enabled": False, "token": "test-tok", "allowFrom": ["*"]}, bus)
    assert ch.config.token == "test-tok"
    assert ch.config.allow_from == ["*"]
```

- [ ] **Step 3: 验证 channel 相关测试**

Run: `pytest tests/channels/test_channel_plugins.py -v -k "not telegram"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/channels/
git commit -m "test: remove channel-specific tests for deleted implementations"
```

---

## Task 11: 删除 Provider 测试文件

**Files:**
- Delete: `tests/providers/test_anthropic_thinking.py`
- Delete: `tests/providers/test_azure_openai_provider.py`
- Delete: `tests/providers/test_mistral_provider.py`
- Delete: `tests/providers/test_openai_responses.py`
- Delete: `tests/providers/test_stepfun_reasoning.py`
- Delete: `tests/providers/test_litellm_kwargs.py`
- Delete: `tests/providers/test_provider_retry.py`
- Delete: `tests/providers/test_provider_retry_after_hints.py`
- Delete: `tests/providers/test_provider_sdk_retry_defaults.py`

- [ ] **Step 1: 删除 provider 测试文件**

```bash
git rm tests/providers/test_anthropic_thinking.py tests/providers/test_azure_openai_provider.py tests/providers/test_mistral_provider.py tests/providers/test_openai_responses.py tests/providers/test_stepfun_reasoning.py tests/providers/test_litellm_kwargs.py tests/providers/test_provider_retry.py tests/providers/test_provider_retry_after_hints.py tests/providers/test_provider_sdk_retry_defaults.py
```

- [ ] **Step 2: 验证剩余 provider 测试通过**

Run: `pytest tests/providers/ -v`
Expected: PASS（包括 test_custom_provider.py, test_providers_init.py 等）

- [ ] **Step 3: Commit**

```bash
git commit -m "test: remove provider-specific tests for deleted implementations"
```

---

## Task 12: 最终验证

**Files:**
- Run: 全量测试

- [ ] **Step 1: 运行全部测试**

Run: `pytest tests/ -v --tb=short 2>&1 | head -100`
Expected: 所有测试通过，无 ImportError 或 ModuleNotFoundError

- [ ] **Step 2: 验证 CLI 命令正常**

Run: `python -m nanobot --version`
Expected: 正常输出版本号

Run: `python -m nanobot status`
Expected: 只显示 openai 和 custom provider 状态

- [ ] **Step 3: 验证 gateway 初始化（无 channel 警告）**

Run: `python -c "import asyncio; from nanobot.config.loader import load_config; from nanobot.bus.queue import MessageBus; from nanobot.channels.manager import ChannelManager; from nanobot.config.schema import Config; c = Config(); mgr = ChannelManager(c, MessageBus()); print('enabled channels:', mgr.enabled_channels)"`
Expected: `enabled channels: []` 且无错误

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: final verification pass for channel/provider simplification"
```

---

## Spec 覆盖检查

| Spec 要求 | 对应 Task |
|---------|---------|
| 删除 feishu.py | Task 8 |
| 删除其他 channel 实现 | Task 8 |
| 删除 anthropic/azure/codex/copilot provider | Task 9 |
| registry.py 只保留 openai + custom | Task 1 |
| ProvidersConfig 简化 | Task 2 |
| channels/__init__.py 无 feishu | Task 3（无变化） |
| providers/__init__.py 清理导出 | Task 3 |
| channels/manager.py 删除 _resolve_transcription_key | Task 5 |
| CLI 删除 provider login | Task 6 |
| CLI status 简化 | Task 6 |
| pyproject.toml 删除依赖 | Task 7 |
| 删除相关测试文件 | Task 10, 11 |
| Gateway 逻辑不变 | Task 12 验证 |
