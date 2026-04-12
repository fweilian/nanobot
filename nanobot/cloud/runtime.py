"""Cloud runtime that bridges object storage, auth, and AgentLoop."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.config import (
    CloudAgentConfig,
    ManagedProviderView,
    UserWorkspaceConfig,
    utc_now_iso,
)
from nanobot.cloud.storage import ObjectStore, download_prefix, upload_tree
from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.nanobot import _make_provider
from nanobot.utils.helpers import sync_workspace_templates


@dataclass(slots=True)
class CloudChatResult:
    """Final response from a cloud agent run."""

    content: str
    model: str


class CloudContextBuilder(ContextBuilder):
    """Context builder that limits builtin skills to an agent-selected subset."""

    def __init__(
        self,
        workspace: Path,
        timezone: str | None,
        builtin_skills_dir: Path,
        selected_skills_dir: Path,
    ):
        super().__init__(workspace, timezone=timezone)
        self.skills = SkillsLoader(workspace, builtin_skills_dir=builtin_skills_dir)
        self.skills.workspace_skills = selected_skills_dir


class CloudSubagentManager(SubagentManager):
    """Subagent manager with a scoped builtin skills directory."""

    def __init__(
        self,
        *args,
        builtin_skills_dir: Path,
        selected_skills_dir: Path,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._builtin_skills_dir = builtin_skills_dir
        self._selected_skills_dir = selected_skills_dir

    def _build_subagent_prompt(self) -> str:
        from nanobot.utils.prompt_templates import render_template

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        loader = SkillsLoader(
            self.workspace,
            builtin_skills_dir=self._builtin_skills_dir,
        )
        loader.workspace_skills = self._selected_skills_dir
        skills_summary = loader.build_skills_summary()
        return render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(self.workspace),
            skills_summary=skills_summary or "",
        )


class CloudAgentLoop(AgentLoop):
    """AgentLoop variant used only by the cloud module."""

    def __init__(
        self,
        *args,
        builtin_skills_dir: Path,
        selected_skills_dir: Path,
        **kwargs,
    ) -> None:
        self._cloud_builtin_skills_dir = builtin_skills_dir
        self._cloud_selected_skills_dir = selected_skills_dir
        super().__init__(*args, **kwargs)
        self.context = CloudContextBuilder(
            self.workspace,
            timezone=self.context.timezone,
            builtin_skills_dir=builtin_skills_dir,
            selected_skills_dir=selected_skills_dir,
        )
        self.subagents = CloudSubagentManager(
            provider=self.provider,
            workspace=self.workspace,
            bus=self.bus,
            model=self.model,
            web_config=self.web_config,
            max_tool_result_chars=self.max_tool_result_chars,
            exec_config=self.exec_config,
            restrict_to_workspace=self.restrict_to_workspace,
            builtin_skills_dir=builtin_skills_dir,
            selected_skills_dir=selected_skills_dir,
        )
        self.tools = self.tools.__class__()
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.filesystem import (
            EditFileTool,
            ListDirTool,
            ReadFileTool,
            WriteFileTool,
        )
        from nanobot.agent.tools.message import MessageTool
        from nanobot.agent.tools.notebook import NotebookEditTool
        from nanobot.agent.tools.search import GlobTool, GrepTool
        from nanobot.agent.tools.shell import ExecTool
        from nanobot.agent.tools.spawn import SpawnTool
        from nanobot.agent.tools.web import WebFetchTool, WebSearchTool

        allowed_dir = (
            self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
        )
        extra_read = [self._cloud_builtin_skills_dir] if allowed_dir else None
        self.tools.register(
            ReadFileTool(
                workspace=self.workspace,
                allowed_dir=allowed_dir,
                extra_allowed_dirs=extra_read,
            )
        )
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        for cls in (GlobTool, GrepTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(NotebookEditTool(workspace=self.workspace, allowed_dir=allowed_dir))
        if self.exec_config.enable:
            self.tools.register(
                ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                    sandbox=self.exec_config.sandbox,
                    path_append=self.exec_config.path_append,
                    allowed_env_keys=self.exec_config.allowed_env_keys,
                )
            )
        if self.web_config.enable:
            self.tools.register(
                WebSearchTool(config=self.web_config.search, proxy=self.web_config.proxy)
            )
            self.tools.register(WebFetchTool(proxy=self.web_config.proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(
                CronTool(self.cron_service, default_timezone=self.context.timezone or "UTC")
            )


class CloudWorkspaceManager:
    """Manage per-user workspaces backed by object storage."""

    CONFIG_NAME = "config.json"

    def __init__(
        self,
        *,
        store: ObjectStore,
        cache_root: Path,
        workspace_prefix: str,
        platform_provider: ManagedProviderView,
    ) -> None:
        self.store = store
        self.cache_root = cache_root
        self.workspace_prefix = workspace_prefix.strip("/")
        self.platform_provider = platform_provider

    def user_prefix(self, user_id: str) -> str:
        return f"{self.workspace_prefix}/{user_id}"

    def user_cache_dir(self, user_id: str) -> Path:
        return self.cache_root / "users" / user_id

    def runtime_root(self, user_id: str) -> Path:
        return self.cache_root / "runtimes" / user_id

    def ensure_user_workspace(self, user_id: str) -> Path:
        prefix = self.user_prefix(user_id)
        root = self.user_cache_dir(user_id)
        if self.store.list_keys(prefix):
            download_prefix(self.store, prefix, root)
        else:
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True, exist_ok=True)
            sync_workspace_templates(root, silent=True)
            cfg = UserWorkspaceConfig(
                user_id=user_id,
                providers={"managed": self.platform_provider},
                agents={"default": "agents/default/config.json"},
            )
            self.save_workspace_config(root, cfg)
            self.save_agent_config(root, CloudAgentConfig(name="default"))
            upload_tree(self.store, root, prefix)
        return root

    def load_workspace_config(self, root: Path) -> UserWorkspaceConfig:
        return UserWorkspaceConfig.model_validate_json((root / self.CONFIG_NAME).read_text(encoding="utf-8"))

    def save_workspace_config(self, root: Path, config: UserWorkspaceConfig) -> None:
        (root / self.CONFIG_NAME).write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def agent_config_path(self, root: Path, agent_name: str) -> Path:
        return root / "agents" / agent_name / "config.json"

    def load_agent_config(self, root: Path, agent_name: str) -> CloudAgentConfig:
        path = self.agent_config_path(root, agent_name)
        if not path.exists():
            raise FileNotFoundError(agent_name)
        return CloudAgentConfig.model_validate_json(path.read_text(encoding="utf-8"))

    def save_agent_config(self, root: Path, config: CloudAgentConfig) -> None:
        path = self.agent_config_path(root, config.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def create_runtime_workspace(self, root: Path, agent: CloudAgentConfig) -> tuple[Path, Path, Path]:
        runtime_parent = self.runtime_root(root.name)
        runtime_parent.mkdir(parents=True, exist_ok=True)
        runtime_dir = Path(tempfile.mkdtemp(prefix=f"{agent.name}-", dir=runtime_parent))
        shutil.copytree(root, runtime_dir, dirs_exist_ok=True)
        selected_builtin_dir = runtime_dir / ".cloud_builtin_skills"
        selected_builtin_dir.mkdir(parents=True, exist_ok=True)
        selected_skills_dir = runtime_dir / ".cloud_selected_skills"
        selected_skills_dir.mkdir(parents=True, exist_ok=True)
        skill_manifest: dict[str, str] = {}

        runtime_skills = runtime_dir / "skills"
        if runtime_skills.exists():
            shutil.rmtree(runtime_skills)
        for path in (runtime_dir / "agents").glob("*/skills"):
            if path.exists():
                shutil.rmtree(path)

        agent_skill_root = root / "agents" / agent.name / "skills"
        workspace_skill_root = root / "skills"
        for skill in agent.skills:
            builtin_path = BUILTIN_SKILLS_DIR / skill
            agent_path = agent_skill_root / skill
            workspace_path = workspace_skill_root / skill
            if agent_path.exists():
                shutil.copytree(agent_path, selected_skills_dir / skill, dirs_exist_ok=True)
                skill_manifest[skill] = (Path("agents") / agent.name / "skills" / skill).as_posix()
            elif workspace_path.exists():
                shutil.copytree(workspace_path, selected_skills_dir / skill, dirs_exist_ok=True)
                skill_manifest[skill] = (Path("skills") / skill).as_posix()
            elif builtin_path.exists():
                shutil.copytree(builtin_path, selected_builtin_dir / skill, dirs_exist_ok=True)
            else:
                raise FileNotFoundError(f"Unknown skill '{skill}' for agent '{agent.name}'")
        (selected_skills_dir / "manifest.json").write_text(
            json.dumps(skill_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return runtime_dir, selected_builtin_dir, selected_skills_dir

    def persist_runtime_workspace(self, root: Path, runtime_dir: Path) -> None:
        transient = {".cloud_builtin_skills", ".cloud_selected_skills", ".git"}

        def _is_skill_path(relative: Path) -> bool:
            parts = relative.parts
            return bool(parts) and (
                parts[0] == "skills"
                or (len(parts) >= 3 and parts[0] == "agents" and parts[2] == "skills")
            )

        if root.exists():
            for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                relative = path.relative_to(root)
                if any(part in transient for part in relative.parts) or _is_skill_path(relative):
                    continue
                counterpart = runtime_dir / relative
                if counterpart.exists():
                    continue
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)

        for path in runtime_dir.rglob("*"):
            relative = path.relative_to(runtime_dir)
            if any(part in transient for part in relative.parts) or _is_skill_path(relative):
                continue
            target = root / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

        manifest_path = runtime_dir / ".cloud_selected_skills" / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for skill, relative_target in manifest.items():
                staged = runtime_dir / ".cloud_selected_skills" / skill
                target = root / relative_target
                if target.exists():
                    shutil.rmtree(target)
                if staged.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(staged, target)

    def upload_user_workspace(self, user_id: str, root: Path) -> None:
        self.store.delete_prefix(self.user_prefix(user_id))
        upload_tree(self.store, root, self.user_prefix(user_id))


class CloudRuntimeService:
    """Main application service for the cloud runtime."""

    def __init__(
        self,
        *,
        settings,
        workspace_manager: CloudWorkspaceManager,
        platform_config_path: Path,
        executor: Callable[..., Awaitable[CloudChatResult]] | None = None,
    ) -> None:
        self.settings = settings
        self.workspace_manager = workspace_manager
        self.platform_config_path = platform_config_path
        self.platform_config = resolve_config_env_vars(load_config(platform_config_path))
        self.platform_model = self.platform_config.agents.defaults.model
        self._executor = executor or self._run_with_agent_loop
        self._user_locks: dict[str, asyncio.Lock] = {}

    def user_lock(self, user_id: str) -> asyncio.Lock:
        return self._user_locks.setdefault(user_id, asyncio.Lock())

    async def list_agents(self, user: AuthenticatedUser) -> list[CloudAgentConfig]:
        async with self.user_lock(user.user_id):
            root = self.workspace_manager.ensure_user_workspace(user.user_id)
            cfg = self.workspace_manager.load_workspace_config(root)
            agents: list[CloudAgentConfig] = []
            for name in sorted(cfg.agents):
                agents.append(self.workspace_manager.load_agent_config(root, name))
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            return agents

    async def ensure_agent(self, user: AuthenticatedUser, agent_name: str) -> CloudAgentConfig:
        async with self.user_lock(user.user_id):
            root = self.workspace_manager.ensure_user_workspace(user.user_id)
            cfg = self.workspace_manager.load_workspace_config(root)
            if agent_name not in cfg.agents:
                raise FileNotFoundError(agent_name)
            return self.workspace_manager.load_agent_config(root, agent_name)

    async def run_chat(
        self,
        *,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
        content: str,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> CloudChatResult:
        async with self.user_lock(user.user_id):
            root = self.workspace_manager.ensure_user_workspace(user.user_id)
            cfg = self.workspace_manager.load_workspace_config(root)
            if agent_name not in cfg.agents:
                raise FileNotFoundError(agent_name)
            agent = self.workspace_manager.load_agent_config(root, agent_name)
            runtime_dir, builtin_dir, selected_skills_dir = self.workspace_manager.create_runtime_workspace(root, agent)
            try:
                result = await self._executor(
                    root,
                    runtime_dir,
                    builtin_dir,
                    selected_skills_dir,
                    user=user,
                    agent=agent,
                    session_key=f"cloud:{user.user_id}:{agent_name}:{session_id}",
                    content=content,
                    on_stream=on_stream,
                    on_stream_end=on_stream_end,
                )
                self.workspace_manager.persist_runtime_workspace(root, runtime_dir)
                cfg.updated_at = utc_now_iso()
                self.workspace_manager.save_workspace_config(root, cfg)
                self.workspace_manager.upload_user_workspace(user.user_id, root)
                return result
            finally:
                shutil.rmtree(runtime_dir, ignore_errors=True)

    async def _run_with_agent_loop(
        self,
        root: Path,
        runtime_dir: Path,
        builtin_dir: Path,
        selected_skills_dir: Path,
        *,
        user: AuthenticatedUser,
        agent: CloudAgentConfig,
        session_key: str,
        content: str,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> CloudChatResult:
        config = self._build_effective_config(runtime_dir, agent)
        provider = _make_provider(config)
        bus = MessageBus()
        defaults = config.agents.defaults
        loop = CloudAgentLoop(
            bus=bus,
            provider=provider,
            workspace=runtime_dir,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            web_config=config.tools.web,
            exec_config=config.tools.exec,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            timezone=defaults.timezone,
            unified_session=defaults.unified_session,
            session_ttl_minutes=defaults.session_ttl_minutes,
            builtin_skills_dir=builtin_dir,
            selected_skills_dir=selected_skills_dir,
        )
        try:
            response = await asyncio.wait_for(
                loop.process_direct(
                    content=content,
                    session_key=session_key,
                    channel="cloud",
                    chat_id=user.user_id,
                    on_stream=on_stream,
                    on_stream_end=on_stream_end,
                ),
                timeout=self.settings.request_timeout,
            )
        finally:
            await loop.close_mcp()
        return CloudChatResult(
            content=(response.content if response else "") or "",
            model=config.agents.defaults.model,
        )

    def _build_effective_config(self, runtime_dir: Path, agent: CloudAgentConfig):
        config = deepcopy(self.platform_config)
        defaults = config.agents.defaults
        defaults.workspace = str(runtime_dir)
        for field in (
            "temperature",
            "max_tokens",
            "context_window_tokens",
            "context_block_limit",
            "max_tool_iterations",
            "max_tool_result_chars",
            "provider_retry_mode",
            "reasoning_effort",
            "timezone",
            "unified_session",
            "session_ttl_minutes",
        ):
            value = getattr(agent, field)
            if value is not None:
                setattr(defaults, field, value)
        return config
