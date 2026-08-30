"""Scoped persistence for Agent challenge resolution."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.orchestrator.models import AgentChallengeResolution


async def create_pending(session: AsyncSession, **values: object) -> AgentChallengeResolution:
    resolution = AgentChallengeResolution(**values)
    session.add(resolution)
    await session.flush()
    return resolution


async def get_for_step(
    session: AsyncSession, *, workflow_run_id: UUID, workflow_step_run_id: UUID
) -> AgentChallengeResolution | None:
    return await session.scalar(
        select(AgentChallengeResolution).where(
            AgentChallengeResolution.workflow_run_id == workflow_run_id,
            AgentChallengeResolution.workflow_step_run_id == workflow_step_run_id,
        )
    )


async def get_scoped_for_update(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    workflow_step_run_id: UUID,
) -> AgentChallengeResolution | None:
    return await session.scalar(
        select(AgentChallengeResolution)
        .where(
            AgentChallengeResolution.tenant_id == tenant_id,
            AgentChallengeResolution.workspace_id == workspace_id,
            AgentChallengeResolution.workflow_run_id == workflow_run_id,
            AgentChallengeResolution.workflow_step_run_id == workflow_step_run_id,
        )
        .with_for_update()
    )


async def decide_pending(
    session: AsyncSession,
    *,
    resolution_id: UUID,
    decision: str,
    reason: str | None,
    decided_at: datetime,
) -> AgentChallengeResolution | None:
    return await session.scalar(
        update(AgentChallengeResolution)
        .where(
            AgentChallengeResolution.id == resolution_id,
            AgentChallengeResolution.decision.is_(None),
        )
        .values(
            decision=decision,
            decision_actor_type="local_user",
            decision_actor_id=None,
            reason=reason,
            decided_at=decided_at,
        )
        .returning(AgentChallengeResolution)
    )
