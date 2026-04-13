"""Cloud runtime that bridges object storage, Redis, and AgentLoop."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.config import CloudAgentConfig, utc_now_iso
from nanobot.cloud.lock import CloudSessionLockedError
from nanobot.cloud.session_catalog import CloudSessionCatalog
from nanobot.cloud.session_store import OnlineSessionStore, session_file_path
from nanobot.cloud.skills_cache import (
    PreparedSkillBundle,
    SkillBundleContentStore,
    SkillStageBudgetManager,
    build_skill_bundle,
    load_or_populate_bundle_content,
)
from nanobot.cloud.workspace_sync import RequestWorkspaceManager
from nanobot.nanobot import _make_provider


@dataclass(slots=True)
class CloudChatResult:
    """Final response from a cloud agent run."""

    content: str
    model: str
    message_id: str | None = None


@dataclass(slots=True)
class ReservedChatExecution:
    """Reserved execution resources for a chat request."""

    lock_scope: str
    lock_token: str
    reserved_bytes: int
    agent: CloudAgentConfig


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
        loader = SkillsLoader(self.workspace, builtin_skills_dir=self._builtin_skills_dir)
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

        allowed_dir = self.workspace if (self.restrict_to_workspace or self.exec_config.sandbox) else None
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
            self.tools.register(WebSearchTool(config=self.web_config.search, proxy=self.web_config.proxy))
            self.tools.register(WebFetchTool(proxy=self.web_config.proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(
                CronTool(self.cron_service, default_timezone=self.context.timezone or "UTC")
            )


class CloudWorkspaceManager(RequestWorkspaceManager):
    """Request-scoped cloud workspace manager with runtime materialization."""

    def prepare_skill_bundles(
        self,
        root: Path,
        agent: CloudAgentConfig,
        *,
        small_skill_max_bytes: int,
    ) -> list[PreparedSkillBundle]:
        bundles: list[PreparedSkillBundle] = []
        agent_skill_root = root / "agents" / agent.name / "skills"
        workspace_skill_root = root / "skills"
        for skill in agent.skills:
            builtin_path = BUILTIN_SKILLS_DIR / skill
            agent_path = agent_skill_root / skill
            workspace_path = workspace_skill_root / skill
            if agent_path.exists():
                bundles.append(build_skill_bundle(
                    skill_name=skill,
                    source_dir=agent_path,
                    source_kind="agent",
                    source=agent_path.as_posix(),
                    relative_target=(Path("agents") / agent.name / "skills" / skill).as_posix(),
                    small_skill_max_bytes=small_skill_max_bytes,
                ))
            elif workspace_path.exists():
                bundles.append(build_skill_bundle(
                    skill_name=skill,
                    source_dir=workspace_path,
                    source_kind="workspace",
                    source=workspace_path.as_posix(),
                    relative_target=(Path("skills") / skill).as_posix(),
                    small_skill_max_bytes=small_skill_max_bytes,
                ))
            elif builtin_path.exists():
                bundles.append(build_skill_bundle(
                    skill_name=skill,
                    source_dir=builtin_path,
                    source_kind="builtin",
                    source=builtin_path.as_posix(),
                    relative_target=None,
                    small_skill_max_bytes=small_skill_max_bytes,
                ))
            else:
                raise FileNotFoundError(f"Unknown skill '{skill}' for agent '{agent.name}'")
        return bundles

    async def create_runtime_workspace(
        self,
        root: Path,
        agent: CloudAgentConfig,
        bundles: list[PreparedSkillBundle] | None = None,
        bundle_store: SkillBundleContentStore | None = None,
    ) -> tuple[Path, Path, Path, int]:
        runtime_dir = Path(tempfile.mkdtemp(prefix=f"{agent.name}-", dir=root.parent))
        shutil.copytree(root, runtime_dir, dirs_exist_ok=True)
        selected_builtin_dir = runtime_dir / ".cloud_builtin_skills"
        selected_builtin_dir.mkdir(parents=True, exist_ok=True)
        selected_skills_dir = runtime_dir / ".cloud_selected_skills"
        selected_skills_dir.mkdir(parents=True, exist_ok=True)

        runtime_skills = runtime_dir / "skills"
        if runtime_skills.exists():
            shutil.rmtree(runtime_skills)
        for path in (runtime_dir / "agents").glob("*/skills"):
            if path.exists():
                shutil.rmtree(path)

        bundles = bundles or self.prepare_skill_bundles(
            root,
            agent,
            small_skill_max_bytes=64 * 1024,
        )
        total_skill_bytes = sum(bundle.manifest.total_bytes for bundle in bundles)
        manifest_payload = {"skills": []}

        for bundle in bundles:
            target_root = selected_builtin_dir if bundle.manifest.source_kind == "builtin" else selected_skills_dir
            skill_target = target_root / bundle.manifest.skill_name
            if skill_target.exists():
                shutil.rmtree(skill_target)
            skill_target.mkdir(parents=True, exist_ok=True)

            cached_files = None
            if bundle_store is not None:
                cached_files = await load_or_populate_bundle_content(bundle, bundle_store)
            if cached_files is None:
                shutil.copytree(bundle.source_dir, skill_target, dirs_exist_ok=True)
            else:
                for rel_path, content in cached_files.items():
                    fp = skill_target / rel_path
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(content)
            manifest_payload["skills"].append(bundle.manifest.model_dump(mode="json"))

        (selected_skills_dir / "manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return runtime_dir, selected_builtin_dir, selected_skills_dir, total_skill_bytes

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
            for skill in manifest.get("skills", []):
                relative_target = skill.get("relative_target")
                if not relative_target:
                    continue
                staged = runtime_dir / ".cloud_selected_skills" / skill["skill_name"]
                target = root / relative_target
                if target.exists():
                    shutil.rmtree(target)
                if staged.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(staged, target)


class CloudRuntimeService:
    """Main application service for the cloud runtime."""

    def __init__(
        self,
        *,
        settings,
        workspace_manager: CloudWorkspaceManager,
        platform_config_path: Path,
        session_store: OnlineSessionStore,
        lock_manager,
        skill_bundle_store: SkillBundleContentStore | None = None,
        skill_stage_budget: SkillStageBudgetManager | None = None,
        executor: Callable[..., Awaitable[CloudChatResult]] | None = None,
    ) -> None:
        from nanobot.config.loader import load_config, resolve_config_env_vars

        self.settings = settings
        self.workspace_manager = workspace_manager
        self.platform_config_path = platform_config_path
        self.platform_config = resolve_config_env_vars(load_config(platform_config_path))
        self.platform_model = self.platform_config.agents.defaults.model
        self.session_store = session_store
        self.session_catalog = CloudSessionCatalog(workspace_manager, session_store)
        self.lock_manager = lock_manager
        self.skill_bundle_store = skill_bundle_store
        self.skill_stage_budget = skill_stage_budget
        self._executor = executor or self._run_with_agent_loop
        self._bootstrap_tasks: dict[str, asyncio.Task[bool]] = {}
        self._bootstrap_tasks_lock = asyncio.Lock()

    async def list_agents(self, user: AuthenticatedUser) -> list[CloudAgentConfig]:
        agents = self.workspace_manager.list_agents_remote(user.user_id)
        if agents is None:
            await self._start_bootstrap_task(user.user_id)
            return [self._default_agent()]
        return agents

    async def ensure_agent(self, user: AuthenticatedUser, agent_name: str) -> CloudAgentConfig:
        return self.load_agent_metadata(user.user_id, agent_name)

    def _default_agent(self) -> CloudAgentConfig:
        return CloudAgentConfig(name="default")

    def load_agent_metadata(self, user_id: str, agent_name: str) -> CloudAgentConfig:
        workspace_cfg = self.workspace_manager.load_workspace_config_remote(user_id)
        if workspace_cfg is None:
            if agent_name != "default":
                raise FileNotFoundError(agent_name)
            return self._default_agent()
        if agent_name not in workspace_cfg.agents:
            raise FileNotFoundError(agent_name)
        agent = self.workspace_manager.load_agent_config_remote(user_id, agent_name)
        if agent is None:
            raise FileNotFoundError(agent_name)
        return agent

    async def _start_bootstrap_task(self, user_id: str) -> asyncio.Task[bool] | None:
        if self.workspace_manager.workspace_exists_remote(user_id):
            return None
        async with self._bootstrap_tasks_lock:
            task = self._bootstrap_tasks.get(user_id)
            if task is not None and not task.done():
                return task
            if self.workspace_manager.workspace_exists_remote(user_id):
                return None
            task = asyncio.create_task(asyncio.to_thread(self.workspace_manager.bootstrap_user_workspace, user_id))
            self._bootstrap_tasks[user_id] = task
            task.add_done_callback(lambda done, uid=user_id: self._on_bootstrap_done(uid, done))
            return task

    def _on_bootstrap_done(self, user_id: str, task: asyncio.Task[bool]) -> None:
        current = self._bootstrap_tasks.get(user_id)
        if current is task:
            self._bootstrap_tasks.pop(user_id, None)
        try:
            task.result()
        except Exception:
            logger.exception("cloud bootstrap failed for user {}", user_id)

    async def _ensure_bootstrapped(self, user_id: str) -> None:
        if self.workspace_manager.workspace_exists_remote(user_id):
            return
        task = await self._start_bootstrap_task(user_id)
        if task is not None:
            await task
        if self.workspace_manager.workspace_exists_remote(user_id):
            return
        await asyncio.to_thread(self.workspace_manager.bootstrap_user_workspace, user_id)

    def validate_skill_sources(self, user_id: str, agent_name: str, agent: CloudAgentConfig) -> None:
        for skill in agent.skills:
            if BUILTIN_SKILLS_DIR.joinpath(skill).exists():
                continue
            if self.workspace_manager.skill_exists_remote(user_id, agent_name, skill):
                continue
            raise FileNotFoundError(f"Unknown skill '{skill}' for agent '{agent_name}'")

    def estimate_request_local_bytes(self, user_id: str, agent: CloudAgentConfig) -> int:
        workspace_bytes = self.workspace_manager.estimate_workspace_bytes(user_id)
        builtin_bytes = 0
        for skill in agent.skills:
            builtin_path = BUILTIN_SKILLS_DIR / skill
            if not builtin_path.exists():
                continue
            bundle = build_skill_bundle(
                skill_name=skill,
                source_dir=builtin_path,
                source_kind="builtin",
                source=builtin_path.as_posix(),
                relative_target=None,
                small_skill_max_bytes=self.settings.skill_cache.small_skill_max_bytes,
            )
            builtin_bytes += bundle.manifest.total_bytes
        return (2 * workspace_bytes) + builtin_bytes

    async def acquire_chat_lock(self, user_id: str, agent_name: str, session_id: str) -> str | None:
        return await self.lock_manager.acquire(
            self._lock_scope(user_id, agent_name, session_id),
            self.settings.redis.lock_ttl_s,
        )

    async def reserve_chat_execution(
        self,
        user_id: str,
        agent_name: str,
        session_id: str,
    ) -> ReservedChatExecution:
        agent = self.load_agent_metadata(user_id, agent_name)
        self.validate_skill_sources(user_id, agent_name, agent)
        reserved_bytes = self.estimate_request_local_bytes(user_id, agent)
        lock_scope = self._lock_scope(user_id, agent_name, session_id)
        lock_token = await self.acquire_chat_lock(user_id, agent_name, session_id)
        if lock_token is None:
            raise CloudSessionLockedError(lock_scope)
        try:
            if self.skill_stage_budget is not None:
                await self.skill_stage_budget.acquire(reserved_bytes)
        except Exception:
            await self.lock_manager.release(lock_scope, lock_token)
            raise
        return ReservedChatExecution(
            lock_scope=lock_scope,
            lock_token=lock_token,
            reserved_bytes=reserved_bytes,
            agent=agent,
        )

    async def run_chat(
        self,
        *,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
        content: str,
        reservation: ReservedChatExecution | None = None,
        message_id: str | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        on_tool_event: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    ) -> CloudChatResult:
        if reservation is None:
            reservation = await self.reserve_chat_execution(user.user_id, agent_name, session_id)
        await self._ensure_bootstrapped(user.user_id)
        root = self.workspace_manager.ensure_user_workspace(user.user_id)

        runtime_dir: Path | None = None
        try:
            cfg = self.workspace_manager.load_workspace_config(root)
            if agent_name not in cfg.agents:
                raise FileNotFoundError(agent_name)
            agent = reservation.agent
            bundles = self.workspace_manager.prepare_skill_bundles(
                root,
                agent,
                small_skill_max_bytes=self.settings.skill_cache.small_skill_max_bytes,
            )
            runtime_dir, builtin_dir, selected_skills_dir, _ = await self.workspace_manager.create_runtime_workspace(
                root,
                agent,
                bundles=bundles,
                bundle_store=self.skill_bundle_store,
            )
            session_key = self._session_key(user.user_id, agent_name, session_id)
            await self._hydrate_online_session(runtime_dir, session_key)
            result = await self._executor(
                root,
                runtime_dir,
                builtin_dir,
                selected_skills_dir,
                user=user,
                agent=agent,
                session_key=session_key,
                content=content,
                message_id=message_id,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
                on_tool_event=on_tool_event,
            )
            self.workspace_manager.persist_runtime_workspace(root, runtime_dir)
            self.session_catalog.sync_session_from_root(root, user.user_id, agent_name, session_id)
            await self._persist_online_session(runtime_dir, session_key)
            cfg.updated_at = utc_now_iso()
            self.workspace_manager.save_workspace_config(root, cfg)
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            return result
        finally:
            if runtime_dir is not None:
                shutil.rmtree(runtime_dir, ignore_errors=True)
            self.workspace_manager.cleanup_workspace(root)
            if self.skill_stage_budget is not None and reservation.reserved_bytes:
                await self.skill_stage_budget.release(reservation.reserved_bytes)
            await self.lock_manager.release(reservation.lock_scope, reservation.lock_token)

    async def _hydrate_online_session(self, runtime_dir: Path, session_key: str) -> None:
        payload = await self.session_store.load(session_key)
        if payload is None:
            return
        path = session_file_path(runtime_dir, session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    async def _persist_online_session(self, runtime_dir: Path, session_key: str) -> None:
        path = session_file_path(runtime_dir, session_key)
        if not path.exists():
            await self.session_store.delete(session_key)
            return
        await self.session_store.save(session_key, path.read_bytes())

    def _session_key(self, user_id: str, agent_name: str, session_id: str) -> str:
        return f"cloud:{user_id}:{agent_name}:{session_id}"

    def _lock_scope(self, user_id: str, agent_name: str, session_id: str) -> str:
        return f"chat:{user_id}:{agent_name}:{session_id}"

    async def list_chat_sessions(self, user: AuthenticatedUser, agent_name: str) -> list[dict[str, Any]]:
        self.load_agent_metadata(user.user_id, agent_name)
        summaries = await asyncio.to_thread(
            self.session_catalog.list_sessions_remote,
            user.user_id,
            agent_name,
        )
        return [item.to_dto() for item in summaries]

    async def get_chat_session(
        self,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
    ) -> dict[str, Any]:
        self.load_agent_metadata(user.user_id, agent_name)
        detail = await asyncio.to_thread(
            self.session_catalog.get_session_detail_remote,
            user.user_id,
            agent_name,
            session_id,
        )
        return detail.to_dto()

    async def create_chat_session(
        self,
        user: AuthenticatedUser,
        agent_name: str,
    ) -> dict[str, Any]:
        self.load_agent_metadata(user.user_id, agent_name)
        await self._ensure_bootstrapped(user.user_id)
        session_id = uuid.uuid4().hex
        lock_scope = self._lock_scope(user.user_id, agent_name, session_id)
        lock_token = await self.acquire_chat_lock(user.user_id, agent_name, session_id)
        if lock_token is None:
            raise CloudSessionLockedError(lock_scope)
        root = self.workspace_manager.ensure_user_workspace(user.user_id)
        try:
            summary = await asyncio.to_thread(
                self.session_catalog.create_session,
                root,
                user.user_id,
                agent_name,
                session_id,
            )
            cfg = self.workspace_manager.load_workspace_config(root)
            cfg.updated_at = utc_now_iso()
            self.workspace_manager.save_workspace_config(root, cfg)
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            return summary.to_dto()
        finally:
            self.workspace_manager.cleanup_workspace(root)
            await self.lock_manager.release(lock_scope, lock_token)

    async def rename_chat_session(
        self,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
        title: str,
    ) -> dict[str, Any]:
        self.load_agent_metadata(user.user_id, agent_name)
        lock_scope = self._lock_scope(user.user_id, agent_name, session_id)
        lock_token = await self.acquire_chat_lock(user.user_id, agent_name, session_id)
        if lock_token is None:
            raise CloudSessionLockedError(lock_scope)
        root = self.workspace_manager.ensure_user_workspace(user.user_id)
        try:
            summary = await asyncio.to_thread(
                self.session_catalog.rename_session,
                root,
                user.user_id,
                agent_name,
                session_id,
                title,
            )
            cfg = self.workspace_manager.load_workspace_config(root)
            cfg.updated_at = utc_now_iso()
            self.workspace_manager.save_workspace_config(root, cfg)
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            return summary.to_dto()
        finally:
            self.workspace_manager.cleanup_workspace(root)
            await self.lock_manager.release(lock_scope, lock_token)

    async def delete_chat_session(
        self,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
    ) -> None:
        self.load_agent_metadata(user.user_id, agent_name)
        lock_scope = self._lock_scope(user.user_id, agent_name, session_id)
        lock_token = await self.acquire_chat_lock(user.user_id, agent_name, session_id)
        if lock_token is None:
            raise CloudSessionLockedError(lock_scope)
        root = self.workspace_manager.ensure_user_workspace(user.user_id)
        try:
            await asyncio.to_thread(
                self.session_catalog.delete_session,
                root,
                user.user_id,
                agent_name,
                session_id,
            )
            cfg = self.workspace_manager.load_workspace_config(root)
            cfg.updated_at = utc_now_iso()
            self.workspace_manager.save_workspace_config(root, cfg)
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            await self.session_store.delete(self._session_key(user.user_id, agent_name, session_id))
        finally:
            self.workspace_manager.cleanup_workspace(root)
            await self.lock_manager.release(lock_scope, lock_token)

    async def cleanup_empty_chat_session(
        self,
        user: AuthenticatedUser,
        agent_name: str,
        session_id: str,
    ) -> bool:
        self.load_agent_metadata(user.user_id, agent_name)
        lock_scope = self._lock_scope(user.user_id, agent_name, session_id)
        lock_token = await self.acquire_chat_lock(user.user_id, agent_name, session_id)
        if lock_token is None:
            return False
        root = self.workspace_manager.ensure_user_workspace(user.user_id)
        try:
            has_user_turn = await asyncio.to_thread(
                self.session_catalog.session_has_durable_user_turn,
                user.user_id,
                agent_name,
                session_id,
            )
            if has_user_turn:
                return False
            await asyncio.to_thread(
                self.session_catalog.delete_session,
                root,
                user.user_id,
                agent_name,
                session_id,
            )
            cfg = self.workspace_manager.load_workspace_config(root)
            cfg.updated_at = utc_now_iso()
            self.workspace_manager.save_workspace_config(root, cfg)
            self.workspace_manager.upload_user_workspace(user.user_id, root)
            await self.session_store.delete(self._session_key(user.user_id, agent_name, session_id))
            return True
        except FileNotFoundError:
            return False
        finally:
            self.workspace_manager.cleanup_workspace(root)
            await self.lock_manager.release(lock_scope, lock_token)

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
        message_id: str | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        on_tool_event: Callable[[dict[str, object]], Awaitable[None]] | None = None,
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
                    on_tool_event=on_tool_event,
                ),
                timeout=self.settings.request_timeout,
            )
        finally:
            await loop.close_mcp()
        return CloudChatResult(
            content=(response.content if response else "") or "",
            model=config.agents.defaults.model,
            message_id=message_id,
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
