import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.agents import service as agents_service
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import AgentDefinitionCreate, AgentRunCreate
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workflows import repository, service
from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepRun,
)
from novalton_api.modules.workflows.schemas import (
    WorkflowPlanCreate,
    WorkflowPlanVersionCreate,
    WorkflowStepRunStatus,
)
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID


async def _seed() -> tuple[Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            values = []
            for marker in ("first", "second"):
                tenant = Tenant(name=marker, slug=f"workflow-{marker}-{uuid4().hex[:6]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(tenant_id=tenant.id, name=marker, slug=marker)
                session.add(workspace)
                await session.flush()
                project = Project(workspace_id=workspace.id, name=marker, slug=marker)
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title=marker)
                session.add(task)
                await session.flush()
                values.append(Scope(tenant.id, workspace.id, project.id, task.id))
            return values[0], values[1]
    finally:
        await database.dispose()


async def _cleanup(scopes: tuple[Scope, Scope]) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant_ids = [scope.tenant_id for scope in scopes]
            await session.execute(
                delete(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id.in_(
                        select(WorkflowRun.id).where(WorkflowRun.tenant_id.in_(tenant_ids))
                    )
                )
            )
            await session.execute(delete(WorkflowRun).where(WorkflowRun.tenant_id.in_(tenant_ids)))
            await session.execute(
                delete(WorkflowStepDependency).where(
                    WorkflowStepDependency.workflow_plan_id.in_(
                        select(WorkflowPlan.id).where(WorkflowPlan.tenant_id.in_(tenant_ids))
                    )
                )
            )
            await session.execute(
                delete(WorkflowStep).where(
                    WorkflowStep.workflow_plan_id.in_(
                        select(WorkflowPlan.id).where(WorkflowPlan.tenant_id.in_(tenant_ids))
                    )
                )
            )
            await session.execute(
                delete(WorkflowPlan).where(WorkflowPlan.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                update(AgentRun).where(AgentRun.tenant_id.in_(tenant_ids)).values(model_run_id=None)
            )
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id.in_(tenant_ids)))
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id.in_(tenant_ids)))
            await session.execute(
                delete(AgentDefinition).where(AgentDefinition.tenant_id.in_(tenant_ids))
            )
            await session.execute(delete(AuditRecord).where(AuditRecord.tenant_id.in_(tenant_ids)))
            for scope in scopes:
                await session.execute(delete(Task).where(Task.id == scope.task_id))
                await session.execute(delete(Project).where(Project.id == scope.project_id))
                await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
                await session.execute(delete(Tenant).where(Tenant.id == scope.tenant_id))
    finally:
        await database.dispose()


@pytest.fixture
def scopes() -> tuple[Scope, Scope]:
    value = asyncio.run(_seed())
    yield value
    asyncio.run(_cleanup(value))


def _plan(*, cycle: str | None = None) -> WorkflowPlanCreate:
    dependencies = {
        "scope": [],
        "backend": ["scope"],
        "frontend": ["scope"],
        "qa": ["backend", "frontend"],
    }
    if cycle == "two":
        dependencies = {"scope": ["backend"], "backend": ["scope"]}
    elif cycle == "three":
        dependencies = {"scope": ["qa"], "backend": ["scope"], "qa": ["backend"]}
    elif cycle == "long":
        dependencies = {
            "scope": ["release"],
            "backend": ["scope"],
            "qa": ["backend"],
            "release": ["qa"],
        }
    return WorkflowPlanCreate(
        title="Implementation workflow",
        summary="A bounded persisted graph.",
        steps=[
            {"step_key": key, "title": key.title(), "step_type": "AGENT_TASK", "depends_on": value}
            for key, value in dependencies.items()
        ],
    )


async def _create(scope: Scope) -> WorkflowPlan:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            return await service.create_plan(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                task_id=scope.task_id,
                data=_plan(),
            )
    finally:
        await database.dispose()


def test_graph_contract_bounds_duplicates_and_cycles_are_deterministic() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlanCreate(
            title="x",
            steps=[
                {"step_key": "same", "title": "A", "step_type": "SYSTEM"},
                {"step_key": "same", "title": "B", "step_type": "SYSTEM"},
            ],
        )
    with pytest.raises(ValidationError):
        WorkflowPlanCreate(
            title="x",
            steps=[
                {"step_key": "a", "title": "A", "step_type": "SYSTEM", "depends_on": ["b", "b"]},
                {"step_key": "b", "title": "B", "step_type": "SYSTEM"},
            ],
        )
    for kind in ("two", "three", "long"):
        with pytest.raises(ApplicationError) as error:
            service.validate_graph(_plan(cycle=kind))
        assert error.value.code == "invalid_workflow_graph"
    assert service.validate_graph(_plan()) == ["scope", "backend", "frontend", "qa"]


def test_plan_version_history_is_immutable_and_scope_is_sanitized(
    scopes: tuple[Scope, Scope],
) -> None:
    first, second = scopes
    plan = asyncio.run(_create(first))

    async def scenario() -> tuple[int, str, int, int]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                run = await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    plan_id=plan.id,
                )
                changed = _plan().model_dump()
                changed["title"] = "Changed"
                version = await service.create_version(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    task_id=first.task_id,
                    plan_id=plan.id,
                    data=WorkflowPlanVersionCreate(**changed, change_reason="Requirements changed"),
                )
                original = await service.get_plan(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    plan_id=plan.id,
                )
                with pytest.raises(ApplicationError) as error:
                    await service.get_plan(
                        session,
                        tenant_id=second.tenant_id,
                        workspace_id=second.workspace_id,
                        plan_id=plan.id,
                    )
                assert (error.value.code, error.value.message) == (
                    "resource_not_found",
                    "Resource not found",
                )
                return (
                    version.version,
                    original.title,
                    run.plan_version,
                    await session.scalar(select(func.count()).select_from(ModelRun)) or 0,
                )
        finally:
            await database.dispose()

    assert asyncio.run(scenario()) == (2, "Implementation workflow", 1, 0)


def test_run_readiness_and_all_dependency_unlock(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    plan = asyncio.run(_create(first))

    async def scenario() -> tuple[list[str], str, str]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                run = await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    plan_id=plan.id,
                )
                steps = await repository.steps_for_plan(session, plan_id=plan.id)
                states = {
                    value.workflow_step_id: value
                    for value in await repository.step_runs_for_runs(session, run_ids=[run.id])
                }
                assert {step.step_key: states[step.id].status for step in steps} == {
                    "scope": "READY",
                    "backend": "PENDING",
                    "frontend": "PENDING",
                    "qa": "PENDING",
                }
                scope_step = next(step for step in steps if step.step_key == "scope")
                await service.transition_step(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                    step_run_id=states[scope_step.id].id,
                    expected=WorkflowStepRunStatus.READY,
                    target=WorkflowStepRunStatus.RUNNING,
                )
                await service.transition_step(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                    step_run_id=states[scope_step.id].id,
                    expected=WorkflowStepRunStatus.RUNNING,
                    target=WorkflowStepRunStatus.COMPLETED,
                )
                states = {
                    value.workflow_step_id: value
                    for value in await repository.step_runs_for_runs(session, run_ids=[run.id])
                }
                backend, frontend, qa = (
                    next(step for step in steps if step.step_key == key)
                    for key in ("backend", "frontend", "qa")
                )
                for step in (backend, frontend):
                    await service.transition_step(
                        session,
                        tenant_id=first.tenant_id,
                        workspace_id=first.workspace_id,
                        run_id=run.id,
                        step_run_id=states[step.id].id,
                        expected=WorkflowStepRunStatus.READY,
                        target=WorkflowStepRunStatus.RUNNING,
                    )
                await service.transition_step(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                    step_run_id=states[backend.id].id,
                    expected=WorkflowStepRunStatus.RUNNING,
                    target=WorkflowStepRunStatus.COMPLETED,
                )
                one_done = (
                    await repository.get_step_run(
                        session, run_id=run.id, step_run_id=states[qa.id].id
                    )
                ).status
                await service.transition_step(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                    step_run_id=states[frontend.id].id,
                    expected=WorkflowStepRunStatus.RUNNING,
                    target=WorkflowStepRunStatus.COMPLETED,
                )
                all_done = (
                    await repository.get_step_run(
                        session, run_id=run.id, step_run_id=states[qa.id].id
                    )
                ).status
                return sorted(value.status for value in states.values()), one_done, all_done
        finally:
            await database.dispose()

    _, one_done, all_done = asyncio.run(scenario())
    assert (one_done, all_done) == ("PENDING", "READY")


def test_database_rejects_cross_plan_dependency(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    plan = asyncio.run(_create(first))

    async def scenario() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                changed = _plan().model_dump()
                changed["title"] = "Second graph"
                version = await service.create_version(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    task_id=first.task_id,
                    plan_id=plan.id,
                    data=WorkflowPlanVersionCreate(**changed, change_reason="Graph changed"),
                )
                old_step = (await repository.steps_for_plan(session, plan_id=plan.id))[0]
                new_step = (await repository.steps_for_plan(session, plan_id=version.id))[0]
                session.add(
                    WorkflowStepDependency(
                        workflow_plan_id=plan.id,
                        workflow_step_id=old_step.id,
                        depends_on_step_id=new_step.id,
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_run_lifecycle_terminal_cannot_reopen(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    plan = asyncio.run(_create(first))

    async def scenario() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                run = await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    plan_id=plan.id,
                )
                run = await service.start_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                )
                await service.complete_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                )
                with pytest.raises(ApplicationError) as error:
                    await service.start_run(
                        session,
                        tenant_id=first.tenant_id,
                        workspace_id=first.workspace_id,
                        run_id=run.id,
                    )
                assert error.value.code == "workflow_run_invalid_transition"
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_agent_run_link_is_trusted_same_scope_only(scopes: tuple[Scope, Scope]) -> None:
    first, second = scopes
    plan = asyncio.run(_create(first))

    async def scenario() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                definition = await agents_service.create_definition(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=AgentDefinitionCreate(
                        name="Worker",
                        slug=f"worker_{uuid4().hex[:8]}",
                        mission="Perform bounded work.",
                        capabilities=[],
                        permissions=[],
                    ),
                )
                agent_run = await agents_service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=AgentRunCreate(
                        agent_definition_id=definition.id,
                        project_id=first.project_id,
                        task_id=first.task_id,
                    ),
                )
                run = await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    plan_id=plan.id,
                )
                step_run = (await repository.step_runs_for_runs(session, run_ids=[run.id]))[0]
                linked = await service.link_agent_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                    step_run_id=step_run.id,
                    agent_run_id=agent_run.id,
                )
                assert linked.agent_run_id == agent_run.id
                with pytest.raises(ApplicationError) as error:
                    await service.link_agent_run(
                        session,
                        tenant_id=second.tenant_id,
                        workspace_id=second.workspace_id,
                        run_id=run.id,
                        step_run_id=step_run.id,
                        agent_run_id=agent_run.id,
                    )
                assert error.value.code == "resource_not_found"
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_public_api_is_read_create_only_and_bounded(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    with TestClient(create_app()) as client:
        base = f"/api/v1/tenants/{first.tenant_id}/workspaces/{first.workspace_id}"
        response = client.post(
            f"{base}/tasks/{first.task_id}/workflow-plans", json=_plan().model_dump(mode="json")
        )
        assert response.status_code == 201
        plan_id = response.json()["id"]
        run = client.post(f"{base}/workflow-plans/{plan_id}/runs", json={})
        assert run.status_code == 201
        assert (
            client.patch(
                f"{base}/workflow-runs/{run.json()['id']}", json={"status": "COMPLETED"}
            ).status_code
            == 405
        )
        assert client.get(f"{base}/workflow-runs", params={"limit": 101}).status_code == 422
        assert client.get(f"{base}/workflow-runs/{run.json()['id']}").status_code == 200


def test_schema_has_no_executable_or_authority_payloads() -> None:
    columns = (
        set(WorkflowStep.__table__.c) | set(WorkflowPlan.__table__.c) | set(WorkflowRun.__table__.c)
    )
    for forbidden in {
        "plan_json",
        "input_json",
        "result_json",
        "prompt",
        "tool_args",
        "approval_id",
        "policy_id",
        "retry_count",
        "checkpoint_id",
    }:
        assert forbidden not in columns
