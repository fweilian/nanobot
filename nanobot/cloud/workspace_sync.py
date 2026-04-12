"""Request-scoped workspace checkout and cleanup for cloud mode."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from nanobot.cloud.config import CloudAgentConfig, ManagedProviderView, UserWorkspaceConfig
from nanobot.cloud.storage import download_prefix, upload_tree
from nanobot.utils.helpers import sync_workspace_templates


class RequestWorkspaceManager:
    """Manage request-scoped workspaces backed by object storage."""

    CONFIG_NAME = "config.json"

    def __init__(
        self,
        *,
        store,
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

    def _requests_root(self) -> Path:
        root = self.cache_root / "requests"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def ensure_user_workspace(self, user_id: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix=f"{user_id}-", dir=self._requests_root()))
        prefix = self.user_prefix(user_id)
        if self.store.list_keys(prefix):
            download_prefix(self.store, prefix, root)
        else:
            sync_workspace_templates(root, silent=True)
            cfg = UserWorkspaceConfig(
                user_id=user_id,
                providers={"managed": self.platform_provider},
                agents={"default": "agents/default/config.json"},
            )
            self.save_workspace_config(root, cfg)
            self.save_agent_config(root, CloudAgentConfig(name="default"))
            self.upload_user_workspace(user_id, root)
        return root

    def cleanup_workspace(self, root: Path) -> None:
        shutil.rmtree(root, ignore_errors=True)

    def load_workspace_config(self, root: Path) -> UserWorkspaceConfig:
        return UserWorkspaceConfig.model_validate_json((root / self.CONFIG_NAME).read_text(encoding="utf-8"))

    def save_workspace_config(self, root: Path, config: UserWorkspaceConfig) -> None:
        (root / self.CONFIG_NAME).write_text(
            config.model_dump_json(indent=2),
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
        path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    def upload_user_workspace(self, user_id: str, root: Path) -> None:
        self.store.delete_prefix(self.user_prefix(user_id))
        upload_tree(self.store, root, self.user_prefix(user_id))
