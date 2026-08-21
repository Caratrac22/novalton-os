"""Scoped read/create APIs for workflow persistence and diagnostics."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.workflows import repository, service
from novalton_api.modules.workflows.models import WorkflowPlan, WorkflowRun
from novalton_api.modules.workflows.schemas import (
    DevelopmentWorkflowCreate,
    DevelopmentWorkflowResponse,
    WorkflowPlanCreate,
    WorkflowPlanListResponse,
    WorkflowPlanResponse,
    WorkflowPlanVersionCreate,
    WorkflowRunCreate,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowRunStatus,
    WorkflowStepResponse,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
plans_router = APIRouter(tags=["workflows"])
runs_router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/workflow-runs", tags=["workflows"]
)


async def _plan_response(session: AsyncSession, plan: WorkflowPlan) -> WorkflowPlanResponse:
    steps, dependencies = await service.plan_graph(session, plan)
    key_by_id = {step.id: step.step_key for step in steps}
    depends_on: dict[UUID, list[str]] = {step.id: [] for step in steps}
    for edge in dependencies:
        depends_on[edge.workflow_step_id].append(key_by_id[edge.depends_on_step_id])
    return WorkflowPlanResponse(
        id=plan.id,
        tenant_id=plan.tenant_id,
        workspace_id=plan.workspace_id,
        project_id=plan.project_id,
        task_id=plan.task_id,
        version=plan.version,
        title=plan.title,
        summary=plan.summary,
        change_reason=plan.change_reason,
        steps=[
            WorkflowStepResponse.model_validate(
                {**step.__dict__, "depends_on": sorted(depends_on[step.id])}
            )
            for step in steps
        ],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


async def _run_response(session: AsyncSession, run: WorkflowRun) -> WorkflowRunResponse:
    step_runs = await repository.step_runs_for_runs(session, run_ids=[run.id])
    return WorkflowRunResponse.model_validate({**run.__dict__, "step_runs": step_runs})


@plans_router.post(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/tasks/{task_id}/workflow-plans",
    response_model=WorkflowPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan(
    tenant_id: UUID, workspace_id: UUID, task_id: UUID, data: WorkflowPlanCreate, session: Session
) -> WorkflowPlanResponse:
    return await _plan_response(
        session,
        await service.create_plan(
            session, tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id, data=data
        ),
    )


@plans_router.post(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/tasks/{task_id}/workflow-plans/{plan_id}/versions",
    response_model=WorkflowPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    plan_id: UUID,
    data: WorkflowPlanVersionCreate,
    session: Session,
) -> WorkflowPlanResponse:
    return await _plan_response(
        session,
        await service.create_version(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            plan_id=plan_id,
            data=data,
        ),
    )


@plans_router.get(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/tasks/{task_id}/workflow-plans",
    response_model=WorkflowPlanListResponse,
)
async def list_plans(
    tenant_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowPlanListResponse:
    plans = await service.list_plans(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    return WorkflowPlanListResponse(
        items=[await _plan_response(session, plan) for plan in plans], limit=limit, offset=offset
    )


@plans_router.get(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/workflow-plans/{plan_id}",
    response_model=WorkflowPlanResponse,
)
async def get_plan(
    tenant_id: UUID, workspace_id: UUID, plan_id: UUID, session: Session
) -> WorkflowPlanResponse:
    return await _plan_response(
        session,
        await service.get_plan(
            session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan_id
        ),
    )


@plans_router.post(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/workflow-plans/{plan_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    tenant_id: UUID, workspace_id: UUID, plan_id: UUID, data: WorkflowRunCreate, session: Session
) -> WorkflowRunResponse:
    del data
    return await _run_response(
        session,
        await service.create_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, plan_id=plan_id
        ),
    )


@plans_router.post(
    "/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}/tasks/{task_id}/development-workflows",
    response_model=DevelopmentWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_development_workflow(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    data: DevelopmentWorkflowCreate,
    session: Session,
) -> DevelopmentWorkflowResponse:
    plan, run = await service.create_development_workflow(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        data=data,
    )
    return DevelopmentWorkflowResponse(
        workflow_plan=await _plan_response(session, plan),
        workflow_run=await _run_response(session, run),
    )


@runs_router.get("", response_model=WorkflowRunListResponse)
async def list_runs(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    run_status: Annotated[WorkflowRunStatus | None, Query(alias="status")] = None,
) -> WorkflowRunListResponse:
    runs = await service.list_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=run_status,
    )
    return WorkflowRunListResponse(
        items=[await _run_response(session, run) for run in runs], limit=limit, offset=offset
    )


@runs_router.get("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def get_run(
    tenant_id: UUID, workspace_id: UUID, workflow_run_id: UUID, session: Session
) -> WorkflowRunResponse:
    return await _run_response(
        session,
        await service.get_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=workflow_run_id
        ),
    )
