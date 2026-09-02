"""Scoped persistence helpers for trusted tool calls."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.tools.models import ToolCall


async def get_by_key(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, agent_run_id: UUID, call_key: str
) -> ToolCall | None:
    return await session.scalar(
        select(ToolCall).where(
            ToolCall.tenant_id == tenant_id,
            ToolCall.workspace_id == workspace_id,
            ToolCall.agent_run_id == agent_run_id,
            ToolCall.call_key == call_key,
        )
    )


async def get_for_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_request_id: UUID,
    for_update: bool = False,
) -> ToolCall | None:
    statement = select(ToolCall).where(
        ToolCall.tenant_id == tenant_id,
        ToolCall.workspace_id == workspace_id,
        ToolCall.approval_request_id == approval_request_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def create(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID | None,
    task_id: UUID | None,
    agent_run_id: UUID,
    proposal_model_run_id: UUID | None,
    call_key: str,
    tool_id: str,
    safe_input_metadata: dict[str, object],
    side_effect_class: str = "READ_ONLY",
    mutation_fingerprint: str | None = None,
    preimage_sha256: str | None = None,
    candidate_sha256: str | None = None,
    prepared_mutation: dict[str, object] | None = None,
) -> ToolCall:
    value = ToolCall(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        proposal_model_run_id=proposal_model_run_id,
        call_key=call_key,
        tool_id=tool_id,
        safe_input_metadata=safe_input_metadata,
        status="PROPOSED",
        matched_rule_ids=[],
        execution_target_class="LOCAL",
        side_effect_class=side_effect_class,
        mutation_fingerprint=mutation_fingerprint,
        preimage_sha256=preimage_sha256,
        candidate_sha256=candidate_sha256,
        prepared_mutation=prepared_mutation,
    )
    session.add(value)
    await session.flush()
    return value


async def set_state(
    session: AsyncSession,
    *,
    tool_call_id: UUID,
    status: str,
    policy_effect: str | None = None,
    matched_rule_ids: list[str] | None = None,
    approval_request_id: UUID | None = None,
    result_metadata: dict[str, object] | None = None,
    failure_code: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ToolCall:
    values: dict[str, object] = {"status": status, "failure_code": failure_code}
    if policy_effect is not None:
        values["policy_effect"] = policy_effect
    if matched_rule_ids is not None:
        values["matched_rule_ids"] = matched_rule_ids
    if approval_request_id is not None:
        values["approval_request_id"] = approval_request_id
    if result_metadata is not None:
        values["result_metadata"] = result_metadata
    if started_at is not None:
        values["started_at"] = started_at
    if completed_at is not None:
        values["completed_at"] = completed_at
    value = await session.scalar(
        update(ToolCall).where(ToolCall.id == tool_call_id).values(**values).returning(ToolCall)
    )
    assert value is not None
    return value


async def list_for_agent_runs(
    session: AsyncSession, *, agent_run_ids: list[UUID]
) -> list[ToolCall]:
    if not agent_run_ids:
        return []
    return list(
        await session.scalars(
            select(ToolCall)
            .where(ToolCall.agent_run_id.in_(agent_run_ids))
            .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
        )
    )
