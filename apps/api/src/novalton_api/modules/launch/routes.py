"""Human test decision and atomic, non-executing workflow creation."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.cadrage.compilation import compile_document
from novalton_api.modules.cadrage.models import CadrageCompilation, CadragePlan
from novalton_api.modules.cadrage.plan import get_plan
from novalton_api.modules.cadrage.service import current_specification, get_conversation
from novalton_api.modules.durable_dispatch.identity import TenantOperatorMembership
from novalton_api.modules.durable_dispatch.models import DispatchActivation
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.saas_access import require_saas_access
from novalton_api.modules.financial.routes import reauth
from novalton_api.modules.launch.models import LaunchAuthorization
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.workflows.schemas import DevelopmentWorkflowCreate
from novalton_api.modules.workflows.service import create_development_workflow

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}/conversations/{conversation_id}/plans/{plan_id}/compilations/{compilation_id}/launch-authorizations",
    tags=["launch-authorizations"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]
Human = Annotated[OperatorAuthority | None, Depends(require_saas_access)]
PERMISSIONS = ["activation.configure", "dispatch.enqueue", "workspace.write"]


class AuthorizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: Literal["AUTHORIZE_DISPOSABLE_TEST_LAUNCH"]
    request_id: UUID = Field(strict=False)
    environment: Literal["DISPOSABLE_TEST"]
    provider_id: Literal["local"]
    model_id: str = Field(min_length=1, max_length=256)
    max_model_calls: int = Field(ge=1, le=100)
    max_duration_seconds: int = Field(ge=1, le=3600)
    current_password: str = Field(min_length=1, max_length=128)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=1, max_length=128)


class CreateWorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: Literal["CREATE_DISPOSABLE_TEST_WORKFLOW"]
    request_id: UUID = Field(strict=False)
    current_password: str = Field(min_length=1, max_length=128)


def _owner(operator: OperatorAuthority | None) -> OperatorAuthority:
    if operator is None:
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    return operator


async def _exclusive_human(
    session: AsyncSession,
    operator: OperatorAuthority | None,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    permissions: list[str],
) -> OperatorAuthority:
    owner = _owner(operator)
    # require_saas_access takes shared locks in the request transaction. Two
    # concurrent mutations cannot both upgrade them to exclusive locks. Release
    # the read transaction, then recheck the complete authority under exclusive
    # locks before any decision is read or written.
    await session.rollback()
    for permission in permissions:
        await owner.require_human(
            session, permission, tenant_id=tenant_id, workspace_id=workspace_id, exclusive=True
        )
    role = await session.scalar(
        select(TenantOperatorMembership.role).where(
            TenantOperatorMembership.user_id == owner.user_id,
            TenantOperatorMembership.tenant_id == tenant_id,
        )
    )
    if role == "VIEWER":
        raise ApplicationError("saas_forbidden", "Workspace access denied", status_code=403)
    return owner


def _missing() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _conflict() -> ApplicationError:
    return ApplicationError(
        "launch_authorization_conflict", "Proposition modifiée ou indisponible", status_code=409
    )


def _fingerprint(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    plan: CadragePlan,
    compilation: CadrageCompilation,
    data: AuthorizeInput,
) -> str:
    payload = {
        "tenant_id": str(tenant_id),
        "workspace_id": str(workspace_id),
        "project_id": str(project_id),
        "plan_id": str(plan.id),
        "plan_document": plan.document,
        "source_version": plan.source_version,
        "compilation_id": str(compilation.id),
        "task_id": str(compilation.task_id),
        "proposal_version": compilation.proposal_version,
        "proposal_document": compilation.document,
        "environment": data.environment,
        "provider_id": data.provider_id,
        "model_id": data.model_id,
        "permissions": PERMISSIONS,
        "max_model_calls": data.max_model_calls,
        "max_duration_seconds": data.max_duration_seconds,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def public(row: LaunchAuthorization) -> dict[str, object]:
    return {
        "id": row.id,
        "version": row.version,
        "plan_id": row.plan_id,
        "compilation_id": row.compilation_id,
        "task_id": row.task_id,
        "source_version": row.source_version,
        "proposal_version": row.proposal_version,
        "fingerprint": row.fingerprint,
        "environment": row.environment,
        "provider_id": row.provider_id,
        "model_id": row.model_id,
        "permissions": row.permissions,
        "max_model_calls": row.max_model_calls,
        "max_duration_seconds": row.max_duration_seconds,
        "financial_authorization_id": row.financial_authorization_id,
        "approved_at": row.approved_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "workflow_created": row.workflow_run_id is not None,
        "workflow_plan_id": row.workflow_plan_id,
        "workflow_run_id": row.workflow_run_id,
        "dispatch_generation": row.dispatch_generation,
    }


async def _scoped(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    owner_id: UUID,
    lock: bool,
) -> tuple[CadragePlan, CadrageCompilation]:
    conversation = await get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=owner_id,
        lock=lock,
    )
    plan = await get_plan(session, conversation=conversation, plan_id=plan_id, lock=lock)
    query = select(CadrageCompilation).where(
        CadrageCompilation.id == compilation_id,
        CadrageCompilation.plan_id == plan.id,
        CadrageCompilation.owner_id == owner_id,
    )
    if lock:
        query = query.with_for_update()
    compilation = await session.scalar(query.execution_options(populate_existing=True))
    if compilation is None:
        raise _missing()
    return plan, compilation


@router.post("", status_code=201)
async def authorize(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    data: AuthorizeInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = await _exclusive_human(
        session,
        operator,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        permissions=PERMISSIONS,
    )
    await reauth(session, owner, authorization, data.current_password)
    plan, compilation = await _scoped(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        compilation_id=compilation_id,
        owner_id=owner.user_id,
        lock=True,
    )
    from novalton_api.modules.cadrage.models import CadrageConversation

    conversation = await session.get(CadrageConversation, conversation_id)
    spec = await current_specification(session, conversation)
    expected_status, expected_document = compile_document(plan.document)
    task = await session.scalar(
        select(Task)
        .where(Task.id == compilation.task_id, Task.project_id == project_id)
        .with_for_update()
    )
    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if (
        plan.status != "APPROVED"
        or plan.decided_by != owner.user_id
        or spec is None
        or spec.id != plan.specification_id
        or spec.version != plan.source_version
        or compilation.source_version != plan.source_version
        or compilation.status != "PROPOSED"
        or expected_status != "PROPOSED"
        or compilation.document != expected_document
        or project is None
        or project.status != "ACTIVE"
        or task is None
        or task.status not in {"READY", "IN_PROGRESS"}
    ):
        raise _conflict()
    fingerprint = _fingerprint(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        plan=plan,
        compilation=compilation,
        data=data,
    )
    existing = await session.scalar(
        select(LaunchAuthorization).where(
            LaunchAuthorization.owner_id == owner.user_id,
            LaunchAuthorization.request_id == data.request_id,
        )
    )
    if existing is not None:
        if (
            existing.tenant_id != tenant_id
            or existing.workspace_id != workspace_id
            or existing.project_id != project_id
            or existing.fingerprint != fingerprint
            or existing.revoked_at is not None
            or existing.expires_at <= datetime.now(UTC)
        ):
            raise _conflict()
        return public(existing)
    now = datetime.now(UTC)
    row = LaunchAuthorization(
        owner_id=owner.user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=compilation.task_id,
        plan_id=plan.id,
        compilation_id=compilation.id,
        request_id=data.request_id,
        source_version=plan.source_version,
        proposal_version=compilation.proposal_version,
        fingerprint=fingerprint,
        environment=data.environment,
        provider_id=data.provider_id,
        model_id=data.model_id,
        permissions=PERMISSIONS,
        max_model_calls=data.max_model_calls,
        max_duration_seconds=data.max_duration_seconds,
        financial_authorization_id=None,
        version=1,
        approved_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    session.add(row)
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=compilation.task_id,
            resource_type="project",
            resource_id=project_id,
            action="launch.authorization.created",
            actor_type="local_user",
            actor_id=str(owner.user_id),
            outcome="success",
            metadata={"launch_policy_id": str(row.id), "version": 1},
        ),
        commit=False,
    )
    await session.commit()
    return public(row)


@router.post("/{launch_authorization_id}/workflow", status_code=201)
async def create_authorized_workflow(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    launch_authorization_id: UUID,
    data: CreateWorkflowInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Create graph, run, handoff, audit and binding in one transaction; never execute."""
    settings = get_settings()
    if (
        settings.environment != "test"
        or (await session.scalar(select(text("current_database()")))) != "novalton_test"
    ):
        raise ApplicationError("disposable_test_required", "Profil de test requis", status_code=403)
    owner = await _exclusive_human(
        session,
        operator,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        permissions=PERMISSIONS,
    )
    await reauth(session, owner, authorization, data.current_password)
    plan, compilation = await _scoped(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        compilation_id=compilation_id,
        owner_id=owner.user_id,
        lock=True,
    )
    task = await session.scalar(
        select(Task)
        .where(Task.id == compilation.task_id, Task.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = await session.scalar(
        select(LaunchAuthorization)
        .where(
            LaunchAuthorization.id == launch_authorization_id,
            LaunchAuthorization.owner_id == owner.user_id,
            LaunchAuthorization.tenant_id == tenant_id,
            LaunchAuthorization.workspace_id == workspace_id,
            LaunchAuthorization.project_id == project_id,
            LaunchAuthorization.plan_id == plan_id,
            LaunchAuthorization.compilation_id == compilation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _missing()
    from novalton_api.modules.cadrage.models import CadrageConversation

    conversation = await session.get(CadrageConversation, conversation_id)
    spec = await current_specification(session, conversation)
    expected_status, expected_document = compile_document(plan.document)
    if (
        row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
        or row.environment != "DISPOSABLE_TEST"
        or row.provider_id != "local"
        or row.financial_authorization_id is not None
        or row.task_id != compilation.task_id
        or row.source_version != plan.source_version
        or row.proposal_version != compilation.proposal_version
        or row.permissions != PERMISSIONS
        or plan.status != "APPROVED"
        or plan.decided_by != owner.user_id
        or spec is None
        or spec.id != plan.specification_id
        or spec.version != plan.source_version
        or compilation.source_version != plan.source_version
        or compilation.status != "PROPOSED"
        or expected_status != "PROPOSED"
        or compilation.document != expected_document
        or project is None
        or project.status != "ACTIVE"
        or task is None
        or task.status not in {"READY", "IN_PROGRESS"}
        or settings.local_model_base_url is None
        or settings.local_model_id != row.model_id
    ):
        raise _conflict()
    fingerprint = _fingerprint(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        plan=plan,
        compilation=compilation,
        data=AuthorizeInput(
            confirmation="AUTHORIZE_DISPOSABLE_TEST_LAUNCH",
            request_id=row.request_id,
            environment="DISPOSABLE_TEST",
            provider_id="local",
            model_id=row.model_id,
            max_model_calls=row.max_model_calls,
            max_duration_seconds=row.max_duration_seconds,
            current_password=data.current_password,
        ),
    )
    if row.fingerprint != fingerprint:
        raise _conflict()
    if row.workflow_run_id is not None:
        if row.launch_request_id != data.request_id:
            raise _conflict()
        return public(row)
    activation = await session.scalar(
        select(DispatchActivation)
        .where(
            DispatchActivation.tenant_id == tenant_id,
            DispatchActivation.workspace_id == workspace_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    model = await session.scalar(
        select(ModelDefinition)
        .where(
            ModelDefinition.provider_id == "local_cadrage",
            ModelDefinition.provider_model_id == row.model_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        not settings.durable_dispatch_enabled
        or activation is None
        or not activation.enabled
        or model is None
        or model.status != "AVAILABLE"
        or model.execution_target_class != "LOCAL"
    ):
        raise _conflict()
    inputs = compilation.document["inputs"]
    graph, run = await create_development_workflow(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=compilation.task_id,
        data=DevelopmentWorkflowCreate(**inputs),
        commit=False,
    )
    row.workflow_plan_id = graph.id
    row.workflow_run_id = run.id
    row.launch_request_id = data.request_id
    row.dispatch_generation = activation.generation
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=compilation.task_id,
            resource_type="project",
            resource_id=project_id,
            action="launch.workflow.created",
            actor_type="local_user",
            actor_id=str(owner.user_id),
            outcome="success",
            metadata={"launch_policy_id": str(row.id), "workflow_run_id": str(run.id)},
        ),
        commit=False,
    )
    await session.commit()
    return public(row)


@router.get("")
async def listing(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    owner = _owner(operator)
    await _scoped(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        compilation_id=compilation_id,
        owner_id=owner.user_id,
        lock=False,
    )
    rows = (
        await session.scalars(
            select(LaunchAuthorization)
            .where(
                LaunchAuthorization.owner_id == owner.user_id,
                LaunchAuthorization.tenant_id == tenant_id,
                LaunchAuthorization.workspace_id == workspace_id,
                LaunchAuthorization.project_id == project_id,
                LaunchAuthorization.plan_id == plan_id,
                LaunchAuthorization.compilation_id == compilation_id,
            )
            .order_by(LaunchAuthorization.created_at.desc())
            .limit(50)
        )
    ).all()
    return {"items": [public(row) for row in rows]}


@router.post("/{launch_authorization_id}/revoke")
async def revoke(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    launch_authorization_id: UUID,
    data: RevokeInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = await _exclusive_human(
        session,
        operator,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        permissions=["workspace.write"],
    )
    await reauth(session, owner, authorization, data.current_password)
    await _scoped(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        compilation_id=compilation_id,
        owner_id=owner.user_id,
        lock=True,
    )
    row = await session.scalar(
        select(LaunchAuthorization)
        .where(
            LaunchAuthorization.id == launch_authorization_id,
            LaunchAuthorization.owner_id == owner.user_id,
            LaunchAuthorization.tenant_id == tenant_id,
            LaunchAuthorization.workspace_id == workspace_id,
            LaunchAuthorization.project_id == project_id,
            LaunchAuthorization.plan_id == plan_id,
            LaunchAuthorization.compilation_id == compilation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _missing()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        row.version += 1
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=row.task_id,
                resource_type="project",
                resource_id=project_id,
                action="launch.authorization.revoked",
                actor_type="local_user",
                actor_id=str(owner.user_id),
                outcome="success",
                metadata={"launch_policy_id": str(row.id), "version": row.version},
            ),
            commit=False,
        )
    await session.commit()
    return public(row)
