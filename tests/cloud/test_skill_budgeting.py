from __future__ import annotations

import pytest

from nanobot.cloud.skills_cache import SkillStageBudgetExceededError, SkillStageBudgetManager


@pytest.mark.asyncio
async def test_skill_stage_budget_rejects_request_over_request_limit():
    manager = SkillStageBudgetManager(
        request_budget_bytes=100,
        instance_budget_bytes=1000,
    )

    with pytest.raises(SkillStageBudgetExceededError):
        await manager.acquire(101)


@pytest.mark.asyncio
async def test_skill_stage_budget_rejects_when_concurrent_budget_is_exceeded():
    manager = SkillStageBudgetManager(
        request_budget_bytes=100,
        instance_budget_bytes=150,
    )

    await manager.acquire(80)
    with pytest.raises(SkillStageBudgetExceededError):
        await manager.acquire(80)
    await manager.release(80)
    await manager.acquire(80)
