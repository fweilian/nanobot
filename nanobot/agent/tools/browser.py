"""High-level browser orchestration tools."""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.cloud.browser_orchestrator import BrowserOrchestrator
from nanobot.cloud.browser_store import BrowserStore


class _BrowserToolBase(Tool):
    def __init__(self, orchestrator: BrowserOrchestrator, store: BrowserStore):
        self._orchestrator = orchestrator
        self._store = store
        self._channel = ""
        self._chat_id = ""
        self._session_key = ""

    def set_context(self, channel: str, chat_id: str, session_key: str | None = None) -> None:
        self._channel = channel
        self._chat_id = chat_id
        self._session_key = session_key or ""

    def _cloud_identity(self) -> tuple[str, str, str] | None:
        parts = self._session_key.split(":")
        if len(parts) >= 4 and parts[0] == "cloud":
            return parts[1], parts[2], parts[3]
        if self._channel == "cloud" and self._chat_id:
            return self._chat_id, "default", self._session_key or "default"
        return None

    async def _submit(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        configured_realm: str | None = None,
        timeout_s: int = 120,
        wait_timeout_s: int = 20,
    ) -> str:
        identity = self._cloud_identity()
        if identity is None:
            return "Error: browser tools currently require a cloud session context."
        user_id, agent_name, session_id = identity
        job = await self._orchestrator.submit_task(
            user_id=user_id,
            agent_name=agent_name,
            chat_session_id=session_id,
            action=action,
            payload=payload,
            configured_realm=configured_realm,
            timeout_s=timeout_s,
        )
        try:
            task = await self._orchestrator.wait_for_status_change(
                job.task_id,
                timeout_s=wait_timeout_s,
                target_statuses=("awaiting_user", "completed", "failed", "cancelled"),
            )
        except TimeoutError:
            return (
                f"Error: browser task timed out while waiting for worker response.\n"
                f"task_id: {job.task_id}\n"
                f"browser_session: {job.browser_session_id}\n"
                f"auth_realm: {job.auth_realm_id or '(none)'}\n"
                f"Likely causes:\n"
                f"- browser worker is not running\n"
                f"- worker Redis config does not match cloud Redis config\n"
                f"- worker connected to Redis but is listening on a different key prefix\n"
                f"- Playwright/browser startup is blocked on the worker\n"
                f"Check worker logs first."
            )
        lines = [
            f"browser task queued: {job.task_id}",
            f"browser session: {job.browser_session_id}",
        ]
        if job.auth_realm_id:
            lines.append(f"auth realm: {job.auth_realm_id}")
        if task.get("reused_auth") == "1":
            lines.append("reused existing login credentials: yes")
        status = task.get("status", "queued")
        lines.append(f"status: {status}")
        result_json = task.get("result_json")
        if result_json:
            try:
                result = json.loads(result_json)
            except json.JSONDecodeError:
                result = {"raw": result_json}
            if isinstance(result, dict):
                if media_id := result.get("media_id"):
                    lines.append(f"qr image: ![qr](/v1/media/{media_id})")
                if message := result.get("message"):
                    lines.append(str(message))
                if current_url := result.get("current_url"):
                    lines.append(f"url: {current_url}")
        if error := task.get("error_message"):
            lines.append(f"error: {error}")
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        url=StringSchema("URL to open"),
        configured_realm=StringSchema("Optional auth realm override", nullable=True),
        wait_timeout_s=IntegerSchema(description="Seconds to wait for initial worker result", minimum=1, maximum=120),
        required=["url"],
    )
)
class BrowserOpenTool(_BrowserToolBase):
    name = "browser_open"
    description = "Open a URL in the remote browser session, reusing existing auth when possible."

    async def execute(
        self,
        url: str,
        configured_realm: str | None = None,
        wait_timeout_s: int = 20,
        **kwargs: Any,
    ) -> str:
        return await self._submit(
            action="open_url",
            payload={"url": url},
            configured_realm=configured_realm,
            wait_timeout_s=wait_timeout_s,
        )


@tool_parameters(
    tool_parameters_schema(
        url=StringSchema("Optional URL that requires login", nullable=True),
        configured_realm=StringSchema("Optional auth realm override", nullable=True),
        wait_timeout_s=IntegerSchema(description="Seconds to wait for qr/login result", minimum=1, maximum=180),
    )
)
class BrowserLoginTool(_BrowserToolBase):
    name = "browser_login"
    description = "Login to the current website. Reuses auth if available; otherwise requests QR or login flow."

    async def execute(
        self,
        url: str | None = None,
        configured_realm: str | None = None,
        wait_timeout_s: int = 30,
        **kwargs: Any,
    ) -> str:
        payload = {"url": url} if url else {}
        return await self._submit(
            action="begin_login",
            payload=payload,
            configured_realm=configured_realm,
            wait_timeout_s=wait_timeout_s,
        )


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("Navigation/click/fill instruction"),
        wait_timeout_s=IntegerSchema(description="Seconds to wait for result", minimum=1, maximum=180),
        required=["instruction"],
    )
)
class BrowserContinueTool(_BrowserToolBase):
    name = "browser_continue"
    description = "Continue browser interaction after opening or logging in."

    async def execute(self, instruction: str, wait_timeout_s: int = 20, **kwargs: Any) -> str:
        return await self._submit(
            action="navigate",
            payload={"instruction": instruction},
            wait_timeout_s=wait_timeout_s,
        )


@tool_parameters(
    tool_parameters_schema(
        mode=StringSchema("Extraction mode: summary, markdown, links, forms", enum=["summary", "markdown", "links", "forms"]),
        wait_timeout_s=IntegerSchema(description="Seconds to wait for extraction", minimum=1, maximum=180),
        required=["mode"],
    )
)
class BrowserExtractTool(_BrowserToolBase):
    name = "browser_extract"
    description = "Extract structured content from the current browser page."

    async def execute(self, mode: str, wait_timeout_s: int = 20, **kwargs: Any) -> str:
        return await self._submit(
            action="extract",
            payload={"mode": mode},
            wait_timeout_s=wait_timeout_s,
        )


@tool_parameters(tool_parameters_schema())
class BrowserCloseTool(_BrowserToolBase):
    name = "browser_close"
    description = "Close the current browser session and release remote resources."

    async def execute(self, **kwargs: Any) -> str:
        return await self._submit(
            action="close_session",
            payload={},
            wait_timeout_s=10,
        )
