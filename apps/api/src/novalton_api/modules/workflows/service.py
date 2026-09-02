"""Immutable graph creation and trusted workflow lifecycle operations."""

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents import repository as agents_repository
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.workflows import repository
from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepHandoff,
    WorkflowStepRun,
)
from novalton_api.modules.workflows.schemas import (
    DevelopmentWorkflowCreate,
    WorkflowPlanCreate,
    WorkflowPlanVersionCreate,
    WorkflowRunStatus,
    WorkflowStepRunStatus,
)
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)
_FAILURE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _invalid_graph(message: str) -> ApplicationError:
    return ApplicationError("invalid_workflow_graph", message, status_code=422)


def validate_graph(data: WorkflowPlanCreate) -> list[str]:
    """Validate references and cycles deterministically, returning topological keys."""
    keys = {step.step_key for step in data.steps}
    incoming: dict[str, set[str]] = {}
    outgoing: dict[str, set[str]] = defaultdict(set)
    for step in data.steps:
        dependencies = set(step.depends_on)
        if step.step_key in dependencies:
            raise _invalid_graph("A workflow step cannot depend on itself")
        if not dependencies <= keys:
            raise _invalid_graph("Workflow dependencies must reference steps in the same plan")
        incoming[step.step_key] = dependencies
        for dependency in dependencies:
            outgoing[dependency].add(step.step_key)
    ready = sorted(key for key, dependencies in incoming.items() if not dependencies)
    ordered: list[str] = []
    while ready:
        key = ready.pop(0)
        ordered.append(key)
        for dependent in sorted(outgoing[key]):
            incoming[dependent].remove(key)
            if not incoming[dependent]:
                ready.append(dependent)
                ready.sort()
    if len(ordered) != len(keys):
        raise _invalid_graph("Workflow dependencies must form an acyclic graph")
    return ordered


async def _task_scope(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, task_id: UUID
) -> UUID:
    scope = await repository.get_task_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
    )
    if scope is None:
        raise _not_found()
    return scope[0]


async def _validate_assignments(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: WorkflowPlanCreate
) -> None:
    for definition_id in sorted(
        {step.agent_definition_id for step in data.steps if step.agent_definition_id is not None},
        key=str,
    ):
        definition = await agents_repository.get_definition(
            session, tenant_id=tenant_id, workspace_id=workspace_id, definition_id=definition_id
        )
        if definition is None:
            raise _not_found()


async def _create_plan(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    project_id: UUID,
    version: int,
    change_reason: str | None,
    data: WorkflowPlanCreate,
    audit_action: str,
) -> WorkflowPlan:
    validate_graph(data)
    await _validate_assignments(session, tenant_id=tenant_id, workspace_id=workspace_id, data=data)
    plan = WorkflowPlan(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        version=version,
        title=data.title,
        summary=data.summary,
        change_reason=change_reason,
    )
    session.add(plan)
    await session.flush()
    by_key: dict[str, WorkflowStep] = {}
    for position, item in enumerate(data.steps):
        step = WorkflowStep(
            workflow_plan_id=plan.id,
            step_key=item.step_key,
            title=item.title,
            step_type=item.step_type.value,
            assigned_capability=item.assigned_capability,
            agent_definition_id=item.agent_definition_id,
            position=position,
            risk_level=item.risk_level.value if item.risk_level else None,
        )
        session.add(step)
        by_key[item.step_key] = step
    await session.flush()
    for item in data.steps:
        for dependency_key in sorted(item.depends_on):
            session.add(
                WorkflowStepDependency(
                    workflow_plan_id=plan.id,
                    workflow_step_id=by_key[item.step_key].id,
                    depends_on_step_id=by_key[dependency_key].id,
                )
            )
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            resource_type="task",
            resource_id=task_id,
            action=audit_action,
            actor_type="service",
            outcome="success",
            metadata={
                "workflow_plan_id": str(plan.id),
                "plan_version": version,
            },
        ),
        commit=False,
    )
    await session.commit()
    await session.refresh(plan)
    logger.info(
        "Workflow plan persisted",
        extra={
            "event": audit_action,
            "workflow_plan_id": str(plan.id),
            "plan_version": version,
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id),
            "task_id": str(task_id),
        },
    )
    return plan


async def create_plan(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    data: WorkflowPlanCreate,
) -> WorkflowPlan:
    project_id = await _task_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
    )
    if (
        await repository.latest_plan(
            session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
        )
        is not None
    ):
        raise ApplicationError(
            "workflow_plan_exists", "Create a new explicit plan version", status_code=409
        )
    try:
        return await _create_plan(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            project_id=project_id,
            version=1,
            change_reason=None,
            data=data,
            audit_action="workflow.plan.created",
        )
    except IntegrityError:
        await session.rollback()
        raise ApplicationError(
            "workflow_plan_conflict", "Workflow plan creation conflicted", status_code=409
        ) from None


async def create_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    plan_id: UUID,
    data: WorkflowPlanVersionCreate,
) -> WorkflowPlan:
    project_id = await _task_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
    )
    source = await repository.get_plan(
        session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan_id, task_id=task_id
    )
    if source is None:
        raise _not_found()
    latest = await repository.latest_plan(
        session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
    )
    if latest is None:
        raise _not_found()
    try:
        return await _create_plan(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            project_id=project_id,
            version=latest.version + 1,
            change_reason=data.change_reason,
            data=data,
            audit_action="workflow.plan.versioned",
        )
    except IntegrityError:
        await session.rollback()
        raise ApplicationError(
            "workflow_plan_conflict", "Workflow plan version creation conflicted", status_code=409
        ) from None


async def get_plan(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, plan_id: UUID
) -> WorkflowPlan:
    plan = await repository.get_plan(
        session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan_id
    )
    if plan is None:
        raise _not_found()
    return plan


async def list_plans(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    limit: int,
    offset: int,
) -> list[WorkflowPlan]:
    await _task_scope(session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id)
    return await repository.list_plans(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )


async def plan_graph(
    session: AsyncSession, plan: WorkflowPlan
) -> tuple[list[WorkflowStep], list[WorkflowStepDependency]]:
    return await repository.steps_for_plan(
        session, plan_id=plan.id
    ), await repository.dependencies_for_plan(session, plan_id=plan.id)


async def create_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, plan_id: UUID
) -> WorkflowRun:
    plan = await get_plan(session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan_id)
    steps, dependencies = await plan_graph(session, plan)
    if not steps:
        raise _invalid_graph("Workflow plan must contain at least one step")
    keys = {step.id: step.step_key for step in steps}
    spec = WorkflowPlanCreate(
        title=plan.title,
        summary=plan.summary,
        steps=[
            {
                "step_key": step.step_key,
                "title": step.title,
                "step_type": step.step_type,
                "assigned_capability": step.assigned_capability,
                "agent_definition_id": step.agent_definition_id,
                "risk_level": step.risk_level,
                "depends_on": [
                    keys[edge.depends_on_step_id]
                    for edge in dependencies
                    if edge.workflow_step_id == step.id
                ],
            }
            for step in steps
        ],
    )
    validate_graph(spec)
    run = WorkflowRun(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=plan.project_id,
        task_id=plan.task_id,
        workflow_plan_id=plan.id,
        plan_version=plan.version,
        status=WorkflowRunStatus.CREATED.value,
        correlation_id=get_correlation_id(),
    )
    session.add(run)
    await session.flush()
    dependent_ids = {edge.workflow_step_id for edge in dependencies}
    for step in steps:
        session.add(
            WorkflowStepRun(
                workflow_run_id=run.id,
                workflow_plan_id=plan.id,
                workflow_step_id=step.id,
                status=WorkflowStepRunStatus.PENDING.value
                if step.id in dependent_ids
                else WorkflowStepRunStatus.READY.value,
            )
        )
    await session.commit()
    await session.refresh(run)
    return run


def _trusted_definition(
    definition: object,
    *,
    name: str,
    version: int,
    category: str,
    mission: str,
    capabilities: list[str],
    permissions: list[str],
) -> bool:
    return (
        getattr(definition, "version", None) == version
        and getattr(definition, "name", None) == name
        and getattr(definition, "category", None) == category
        and getattr(definition, "mission", None) == mission
        and getattr(definition, "capabilities", None) == capabilities
        and getattr(definition, "permissions", None) == permissions
    )


async def create_development_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    data: DevelopmentWorkflowCreate,
) -> tuple[WorkflowPlan, WorkflowRun]:
    """Persist the one fixed Manager -> Developer -> QA graph without model execution."""
    scoped_project = await _task_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id
    )
    if scoped_project != project_id:
        raise _not_found()
    manager = await manager_service.resolve_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    developer = await developer_service.resolve_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    qa = await qa_service.resolve_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    checks = (
        (
            manager,
            manager_service.DEVELOPER_MANAGER_NAME,
            1,
            manager_service.DEVELOPER_MANAGER_CATEGORY,
            manager_service.DEVELOPER_MANAGER_MISSION,
            manager_service.DEVELOPER_MANAGER_CAPABILITIES,
            [],
        ),
        (
            developer,
            developer_service.DEVELOPER_WORKER_NAME,
            developer_service.DEVELOPER_WORKER_VERSION,
            developer_service.DEVELOPER_WORKER_CATEGORY,
            developer_service.DEVELOPER_WORKER_MISSION,
            developer_service.DEVELOPER_WORKER_CAPABILITIES,
            developer_service.DEVELOPER_WORKER_PERMISSIONS,
        ),
        (
            qa,
            qa_service.QA_WORKER_NAME,
            1,
            qa_service.QA_WORKER_CATEGORY,
            qa_service.QA_WORKER_MISSION,
            qa_service.QA_WORKER_CAPABILITIES,
            [],
        ),
    )
    if not all(
        _trusted_definition(
            item,
            name=name,
            version=version,
            category=category,
            mission=mission,
            capabilities=capabilities,
            permissions=permissions,
        )
        for item, name, version, category, mission, capabilities, permissions in checks
    ):
        raise ApplicationError(
            "development_workflow_unavailable",
            "Trusted development agents are unavailable",
            status_code=409,
        )
    plan = await create_plan(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        data=WorkflowPlanCreate(
            title="Development workflow",
            summary="Fixed governed Manager to Developer Worker to QA Worker workflow",
            steps=[
                {
                    "step_key": "manager_plan",
                    "title": "Plan development assignment",
                    "step_type": "AGENT_TASK",
                    "assigned_capability": "implementation_planning",
                    "agent_definition_id": manager.id,
                    "risk_level": "LOW",
                    "depends_on": [],
                },
                {
                    "step_key": "developer_execute",
                    "title": "Execute development assignment",
                    "step_type": "AGENT_TASK",
                    "assigned_capability": "software_implementation",
                    "agent_definition_id": developer.id,
                    "risk_level": "LOW",
                    "depends_on": ["manager_plan"],
                },
                {
                    "step_key": "qa_validate",
                    "title": "Validate development result",
                    "step_type": "AGENT_TASK",
                    "assigned_capability": "acceptance_validation",
                    "agent_definition_id": qa.id,
                    "risk_level": "LOW",
                    "depends_on": ["developer_execute"],
                },
            ],
        ),
    )
    run = await create_run(session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan.id)
    ordered = await repository.ordered_step_runs(session, run_id=run.id)
    manager_step_run = ordered[0][0]
    await repository.add_handoff(
        session,
        WorkflowStepHandoff(
            workflow_run_id=run.id,
            workflow_plan_id=plan.id,
            source_step_run_id=None,
            destination_step_run_id=manager_step_run.id,
            handoff_type="DEVELOPMENT_REQUEST",
            objective=data.objective,
            acceptance_criteria=data.acceptance_criteria,
            evidence_items=[],
        ),
    )
    await session.commit()
    return plan, run


async def get_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> WorkflowRun:
    run = await repository.get_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id
    )
    if run is None:
        raise _not_found()
    return run


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: WorkflowRunStatus | None,
) -> list[WorkflowRun]:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()
    return await repository.list_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status.value if status else None,
    )


async def _transition_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    expected: WorkflowRunStatus,
    target: WorkflowRunStatus,
    failure_code: str | None = None,
) -> WorkflowRun:
    await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    now = datetime.now(UTC)
    values: dict[str, object] = {"status": target.value, "updated_at": now}
    if target == WorkflowRunStatus.RUNNING:
        values["started_at"] = now
    else:
        values.update(completed_at=now, failure_code=failure_code)
    value = await repository.transition_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=expected.value,
        values=values,
    )
    if value is None:
        raise ApplicationError(
            "workflow_run_invalid_transition",
            "Workflow run state transition is invalid",
            status_code=409,
        )
    await session.commit()
    return value


async def start_run(session: AsyncSession, **scope: object) -> WorkflowRun:
    return await _transition_run(
        session, **scope, expected=WorkflowRunStatus.CREATED, target=WorkflowRunStatus.RUNNING
    )  # type: ignore[arg-type]


async def complete_run(session: AsyncSession, **scope: object) -> WorkflowRun:
    return await _transition_run(
        session, **scope, expected=WorkflowRunStatus.RUNNING, target=WorkflowRunStatus.COMPLETED
    )  # type: ignore[arg-type]


async def fail_run(session: AsyncSession, *, failure_code: str, **scope: object) -> WorkflowRun:
    if _FAILURE.fullmatch(failure_code) is None:
        raise ApplicationError(
            "workflow_run_invalid_failure", "Failure code is invalid", status_code=422
        )
    return await _transition_run(
        session,
        **scope,
        expected=WorkflowRunStatus.RUNNING,
        target=WorkflowRunStatus.FAILED,
        failure_code=failure_code,
    )  # type: ignore[arg-type]


async def cancel_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> WorkflowRun:
    run = await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    expected = WorkflowRunStatus(run.status)
    if expected not in {WorkflowRunStatus.CREATED, WorkflowRunStatus.RUNNING}:
        raise ApplicationError(
            "workflow_run_invalid_transition",
            "Workflow run state transition is invalid",
            status_code=409,
        )
    return await _transition_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=expected,
        target=WorkflowRunStatus.CANCELLED,
    )


async def transition_step(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    step_run_id: UUID,
    expected: WorkflowStepRunStatus,
    target: WorkflowStepRunStatus,
    failure_code: str | None = None,
) -> WorkflowStepRun:
    await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    if (expected, target) not in {
        (WorkflowStepRunStatus.READY, WorkflowStepRunStatus.RUNNING),
        (WorkflowStepRunStatus.RUNNING, WorkflowStepRunStatus.WAITING_FOR_APPROVAL),
        (WorkflowStepRunStatus.WAITING_FOR_APPROVAL, WorkflowStepRunStatus.RUNNING),
        (WorkflowStepRunStatus.WAITING_FOR_APPROVAL, WorkflowStepRunStatus.FAILED),
        (WorkflowStepRunStatus.WAITING_FOR_APPROVAL, WorkflowStepRunStatus.CANCELLED),
        (WorkflowStepRunStatus.RUNNING, WorkflowStepRunStatus.COMPLETED),
        (WorkflowStepRunStatus.RUNNING, WorkflowStepRunStatus.FAILED),
        (WorkflowStepRunStatus.PENDING, WorkflowStepRunStatus.CANCELLED),
        (WorkflowStepRunStatus.READY, WorkflowStepRunStatus.CANCELLED),
        (WorkflowStepRunStatus.RUNNING, WorkflowStepRunStatus.CANCELLED),
    }:
        raise ApplicationError(
            "workflow_step_invalid_transition",
            "Workflow step state transition is invalid",
            status_code=409,
        )
    if target == WorkflowStepRunStatus.FAILED and (
        failure_code is None or _FAILURE.fullmatch(failure_code) is None
    ):
        raise ApplicationError(
            "workflow_step_invalid_failure", "Failure code is invalid", status_code=422
        )
    now = datetime.now(UTC)
    values: dict[str, object] = {"status": target.value, "updated_at": now}
    if target == WorkflowStepRunStatus.RUNNING and expected == WorkflowStepRunStatus.READY:
        values["started_at"] = now
    elif target in {
        WorkflowStepRunStatus.COMPLETED,
        WorkflowStepRunStatus.FAILED,
        WorkflowStepRunStatus.CANCELLED,
    }:
        values.update(completed_at=now, failure_code=failure_code)
    value = await repository.transition_step_run(
        session, run_id=run_id, step_run_id=step_run_id, expected=expected.value, values=values
    )
    if value is None:
        raise ApplicationError(
            "workflow_step_invalid_transition",
            "Workflow step state transition is invalid",
            status_code=409,
        )
    if target == WorkflowStepRunStatus.COMPLETED:
        for dependent in await repository.pending_dependents(
            session, run_id=run_id, completed_step_id=value.workflow_step_id
        ):
            if (
                await repository.incomplete_dependency_count(
                    session, run_id=run_id, step_id=dependent.workflow_step_id
                )
                == 0
            ):
                await repository.transition_step_run(
                    session,
                    run_id=run_id,
                    step_run_id=dependent.id,
                    expected=WorkflowStepRunStatus.PENDING.value,
                    values={"status": WorkflowStepRunStatus.READY.value, "updated_at": now},
                )
    await session.commit()
    return value


async def link_agent_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    step_run_id: UUID,
    agent_run_id: UUID,
) -> WorkflowStepRun:
    run = await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    step_run = await repository.get_step_run(session, run_id=run_id, step_run_id=step_run_id)
    agent_run = await agents_repository.get_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=agent_run_id
    )
    if (
        step_run is None
        or agent_run is None
        or (agent_run.project_id, agent_run.task_id) != (run.project_id, run.task_id)
    ):
        raise _not_found()
    linked = await repository.link_agent_run(
        session, step_run_id=step_run_id, agent_run_id=agent_run_id
    )
    if linked is None:
        raise ApplicationError(
            "workflow_step_agent_link_conflict",
            "Workflow step Agent Run link conflicted",
            status_code=409,
        )
    await session.commit()
    return linked
