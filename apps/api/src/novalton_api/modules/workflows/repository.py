"""Explicit scoped SQL for workflow graphs and run state."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepHandoff,
    WorkflowStepRun,
)


async def get_task_scope(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, task_id: UUID
) -> tuple[UUID, UUID] | None:
    from novalton_api.modules.projects.models import Project
    from novalton_api.modules.tasks.models import Task
    from novalton_api.modules.workspaces.models import Workspace

    row = (
        await session.execute(
            select(Project.id, Task.id)
            .join(Task, Task.project_id == Project.id)
            .join(Workspace, Workspace.id == Project.workspace_id)
            .where(
                Workspace.tenant_id == tenant_id, Workspace.id == workspace_id, Task.id == task_id
            )
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def latest_plan(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, task_id: UUID
) -> WorkflowPlan | None:
    return await session.scalar(
        select(WorkflowPlan)
        .where(
            WorkflowPlan.tenant_id == tenant_id,
            WorkflowPlan.workspace_id == workspace_id,
            WorkflowPlan.task_id == task_id,
        )
        .order_by(WorkflowPlan.version.desc())
        .limit(1)
    )


async def get_plan(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    plan_id: UUID,
    task_id: UUID | None = None,
) -> WorkflowPlan | None:
    statement = select(WorkflowPlan).where(
        WorkflowPlan.tenant_id == tenant_id,
        WorkflowPlan.workspace_id == workspace_id,
        WorkflowPlan.id == plan_id,
    )
    if task_id is not None:
        statement = statement.where(WorkflowPlan.task_id == task_id)
    return await session.scalar(statement)


async def list_plans(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    limit: int,
    offset: int,
) -> list[WorkflowPlan]:
    values = await session.scalars(
        select(WorkflowPlan)
        .where(
            WorkflowPlan.tenant_id == tenant_id,
            WorkflowPlan.workspace_id == workspace_id,
            WorkflowPlan.task_id == task_id,
        )
        .order_by(WorkflowPlan.version.asc(), WorkflowPlan.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(values)


async def steps_for_plan(session: AsyncSession, *, plan_id: UUID) -> list[WorkflowStep]:
    return list(
        await session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_plan_id == plan_id)
            .order_by(WorkflowStep.position.asc(), WorkflowStep.id.asc())
        )
    )


async def dependencies_for_plan(
    session: AsyncSession, *, plan_id: UUID
) -> list[WorkflowStepDependency]:
    return list(
        await session.scalars(
            select(WorkflowStepDependency)
            .where(WorkflowStepDependency.workflow_plan_id == plan_id)
            .order_by(
                WorkflowStepDependency.workflow_step_id.asc(),
                WorkflowStepDependency.depends_on_step_id.asc(),
            )
        )
    )


async def get_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> WorkflowRun | None:
    return await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
            WorkflowRun.id == run_id,
        )
    )


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: str | None,
) -> list[WorkflowRun]:
    statement: Select[tuple[WorkflowRun]] = select(WorkflowRun).where(
        WorkflowRun.tenant_id == tenant_id, WorkflowRun.workspace_id == workspace_id
    )
    if status is not None:
        statement = statement.where(WorkflowRun.status == status)
    return list(
        await session.scalars(
            statement.order_by(WorkflowRun.created_at.asc(), WorkflowRun.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )


async def step_runs_for_runs(
    session: AsyncSession, *, run_ids: list[UUID]
) -> list[WorkflowStepRun]:
    if not run_ids:
        return []
    return list(
        await session.scalars(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.workflow_run_id.in_(run_ids))
            .order_by(WorkflowStepRun.created_at.asc(), WorkflowStepRun.id.asc())
        )
    )


async def get_step_run(
    session: AsyncSession, *, run_id: UUID, step_run_id: UUID, for_update: bool = False
) -> WorkflowStepRun | None:
    statement = select(WorkflowStepRun).where(
        WorkflowStepRun.workflow_run_id == run_id, WorkflowStepRun.id == step_run_id
    )
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def step_run_for_agent(
    session: AsyncSession, *, agent_run_id: UUID, for_update: bool = False
) -> WorkflowStepRun | None:
    statement = select(WorkflowStepRun).where(WorkflowStepRun.agent_run_id == agent_run_id)
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def ordered_step_runs(
    session: AsyncSession, *, run_id: UUID
) -> list[tuple[WorkflowStepRun, WorkflowStep]]:
    """Return the persisted run graph in its immutable plan order."""
    rows = await session.execute(
        select(WorkflowStepRun, WorkflowStep)
        .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
        .where(WorkflowStepRun.workflow_run_id == run_id)
        .order_by(WorkflowStep.position.asc(), WorkflowStep.step_key.asc(), WorkflowStep.id.asc())
    )
    return list(rows.tuples())


async def count_step_states(session: AsyncSession, *, run_id: UUID) -> dict[str, int]:
    rows = await session.execute(
        select(WorkflowStepRun.status, func.count())
        .where(WorkflowStepRun.workflow_run_id == run_id)
        .group_by(WorkflowStepRun.status)
    )
    return {status: int(count) for status, count in rows}


async def transition_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    expected: str,
    values: Mapping[str, Any],
) -> WorkflowRun | None:
    return await session.scalar(
        update(WorkflowRun)
        .where(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
            WorkflowRun.id == run_id,
            WorkflowRun.status == expected,
        )
        .values(**values)
        .returning(WorkflowRun)
    )


async def transition_step_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    step_run_id: UUID,
    expected: str,
    values: Mapping[str, Any],
) -> WorkflowStepRun | None:
    return await session.scalar(
        update(WorkflowStepRun)
        .where(
            WorkflowStepRun.workflow_run_id == run_id,
            WorkflowStepRun.id == step_run_id,
            WorkflowStepRun.status == expected,
        )
        .values(**values)
        .returning(WorkflowStepRun)
    )


async def pending_dependents(
    session: AsyncSession, *, run_id: UUID, completed_step_id: UUID
) -> list[WorkflowStepRun]:
    return list(
        await session.scalars(
            select(WorkflowStepRun)
            .join(
                WorkflowStepDependency,
                WorkflowStepDependency.workflow_step_id == WorkflowStepRun.workflow_step_id,
            )
            .where(
                WorkflowStepRun.workflow_run_id == run_id,
                WorkflowStepRun.status == "PENDING",
                WorkflowStepDependency.depends_on_step_id == completed_step_id,
            )
            .order_by(WorkflowStepRun.workflow_step_id.asc())
        )
    )


async def incomplete_dependency_count(session: AsyncSession, *, run_id: UUID, step_id: UUID) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(WorkflowStepDependency)
        .join(
            WorkflowStepRun,
            (WorkflowStepRun.workflow_run_id == run_id)
            & (WorkflowStepRun.workflow_step_id == WorkflowStepDependency.depends_on_step_id),
        )
        .where(
            WorkflowStepDependency.workflow_step_id == step_id,
            WorkflowStepRun.status != "COMPLETED",
        )
    )
    return int(value or 0)


async def link_agent_run(
    session: AsyncSession, *, step_run_id: UUID, agent_run_id: UUID
) -> WorkflowStepRun | None:
    return await session.scalar(
        update(WorkflowStepRun)
        .where(WorkflowStepRun.id == step_run_id, WorkflowStepRun.agent_run_id.is_(None))
        .values(agent_run_id=agent_run_id)
        .returning(WorkflowStepRun)
    )


async def handoff_for_destination(
    session: AsyncSession, *, run_id: UUID, destination_step_run_id: UUID
) -> WorkflowStepHandoff | None:
    return await session.scalar(
        select(WorkflowStepHandoff).where(
            WorkflowStepHandoff.workflow_run_id == run_id,
            WorkflowStepHandoff.destination_step_run_id == destination_step_run_id,
        )
    )


async def add_handoff(session: AsyncSession, handoff: WorkflowStepHandoff) -> WorkflowStepHandoff:
    session.add(handoff)
    await session.flush()
    return handoff
