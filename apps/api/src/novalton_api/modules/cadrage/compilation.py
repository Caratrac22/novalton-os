"""Fail-closed bridge from an approved cadrage snapshot to an inspectable proposal.

This module deliberately never calls workflow creation or durable dispatch.
"""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents import repository as agent_repository
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.cadrage.models import CadrageCompilation, CadrageConversation, CadragePlan
from novalton_api.modules.cadrage.service import current_specification
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.durable_dispatch.identity import WorkspaceOperatorPermission
from novalton_api.modules.durable_dispatch.models import DispatchActivation
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.projects.models import Project
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.workflows.repository import get_task_scope
from novalton_api.modules.workflows.schemas import DevelopmentWorkflowCreate
from novalton_api.modules.workflows.service import _trusted_definition


def compile_document(document: dict) -> tuple[str, dict]:
    """Accept only explicit confirmed inputs for the existing fixed I-028 graph."""
    values: dict[str, str] = {}
    diagnostics: list[str] = []
    for item in document.get("scope", []):
        if item.get("state") != "CONFIRMED":
            continue
        topic, value = item.get("topic"), item.get("value")
        if topic in values:
            diagnostics.append(f"duplicate_confirmed_topic:{topic}")
        elif isinstance(topic, str) and isinstance(value, str):
            values[topic] = value
    if values.get("execution.kind") != "development":
        diagnostics.append("unsupported_or_missing_execution_kind")
    criteria = [value for key, value in sorted(values.items()) if key.startswith("acceptance.")]
    if not values.get("objective"):
        diagnostics.append("missing_confirmed_objective")
    if not criteria:
        diagnostics.append("missing_confirmed_acceptance_criteria")
    if document.get("unresolved"):
        diagnostics.append("unresolved_specification_items")
    if not diagnostics:
        try:
            DevelopmentWorkflowCreate(objective=values["objective"], acceptance_criteria=criteria)
        except ValidationError:
            diagnostics.append("invalid_development_handoff")
    proposal = {
        "template": "fixed_i028_development" if not diagnostics else None,
        "inputs": {"objective": values.get("objective"), "acceptance_criteria": criteria}
        if not diagnostics
        else None,
        "steps": [
            {"key": "manager_plan", "depends_on": [], "capability": "implementation_planning"},
            {
                "key": "developer_execute",
                "depends_on": ["manager_plan"],
                "capability": "software_implementation",
            },
            {
                "key": "qa_validate",
                "depends_on": ["developer_execute"],
                "capability": "acceptance_validation",
            },
        ]
        if not diagnostics
        else [],
        "required_permissions": ["workspace.write", "activation.configure", "dispatch.enqueue"],
        "environment": "isolated_test_only",
        "providers": "unverified",
        "cost": "BILLING_UNVERIFIED; no expenditure authorized",
        "diagnostics": diagnostics,
        "launch_available": False,
    }
    return ("BLOCKED" if diagnostics else "PROPOSED"), proposal


async def compile_plan(
    session: AsyncSession,
    *,
    conversation: CadrageConversation,
    plan: CadragePlan,
    task_id: UUID,
    owner: UUID,
) -> CadrageCompilation:
    """Caller locks the conversation and plan; the unique key makes retries idempotent."""
    if plan.status != "APPROVED" or plan.decided_by != owner:
        raise ApplicationError("plan_not_approved", "Plan non approuvé", status_code=409)
    spec = await current_specification(session, conversation)
    if spec is None or spec.id != plan.specification_id or spec.version != plan.source_version:
        raise ApplicationError("plan_obsolete", "Plan dépassé", status_code=409)
    scope = await get_task_scope(
        session,
        tenant_id=conversation.tenant_id,
        workspace_id=conversation.workspace_id,
        task_id=task_id,
    )
    if scope is None or scope[0] != conversation.project_id:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    existing = await session.scalar(
        select(CadrageCompilation).where(
            CadrageCompilation.plan_id == plan.id, CadrageCompilation.task_id == task_id
        )
    )
    if existing:
        return existing
    status, document = compile_document(plan.document)
    row = CadrageCompilation(
        plan_id=plan.id,
        task_id=task_id,
        owner_id=owner,
        source_version=plan.source_version,
        proposal_version=1,
        status=status,
        document=document,
    )
    session.add(row)
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=conversation.tenant_id,
            workspace_id=conversation.workspace_id,
            action="cadrage.plan.compiled",
            actor_type="local_user",
            actor_id=str(owner),
            outcome="success",
            resource_type="project",
            resource_id=conversation.project_id,
            project_id=conversation.project_id,
            task_id=task_id,
            metadata={"plan_id": str(plan.id), "compilation_id": str(row.id), "status": status},
        ),
        commit=False,
    )
    await session.commit()
    return row


async def preflight(
    session: AsyncSession,
    *,
    conversation: CadrageConversation,
    plan: CadragePlan,
    compilation: CadrageCompilation,
    operator: OperatorAuthority,
) -> dict:
    """Recompute revocable conditions at read time; no result grants launch authority."""
    spec = await current_specification(session, conversation)
    task = await session.get(Task, compilation.task_id)
    project = await session.get(Project, conversation.project_id)
    diagnostics = list(compilation.document["diagnostics"])
    if plan.status != "APPROVED" or spec is None or spec.id != plan.specification_id:
        diagnostics.append("plan_obsolete_or_not_approved")
    if (
        task is None
        or task.project_id != conversation.project_id
        or project is None
        or project.status != "ACTIVE"
    ):
        diagnostics.append("project_or_task_unavailable")
    proposal_diagnostics = list(diagnostics)
    if task is not None and task.status not in {"READY", "IN_PROGRESS"}:
        diagnostics.append("task_not_runnable")
    definitions = (
        (
            await agent_repository.latest_definition(
                session,
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                slug=manager_service.DEVELOPER_MANAGER_SLUG,
                exclude_archived=True,
            ),
            manager_service.DEVELOPER_MANAGER_NAME,
            1,
            manager_service.DEVELOPER_MANAGER_CATEGORY,
            manager_service.DEVELOPER_MANAGER_MISSION,
            manager_service.DEVELOPER_MANAGER_CAPABILITIES,
            [],
        ),
        (
            await agent_repository.latest_definition(
                session,
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                slug=developer_service.DEVELOPER_WORKER_SLUG,
                exclude_archived=True,
            ),
            developer_service.DEVELOPER_WORKER_NAME,
            developer_service.DEVELOPER_WORKER_VERSION,
            developer_service.DEVELOPER_WORKER_CATEGORY,
            developer_service.DEVELOPER_WORKER_MISSION,
            developer_service.DEVELOPER_WORKER_CAPABILITIES,
            developer_service.DEVELOPER_WORKER_PERMISSIONS,
        ),
        (
            await agent_repository.latest_definition(
                session,
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                slug=qa_service.QA_WORKER_SLUG,
                exclude_archived=True,
            ),
            qa_service.QA_WORKER_NAME,
            1,
            qa_service.QA_WORKER_CATEGORY,
            qa_service.QA_WORKER_MISSION,
            qa_service.QA_WORKER_CAPABILITIES,
            [],
        ),
    )
    agents_available = all(
        _trusted_definition(
            item,
            name=name,
            version=version,
            category=category,
            mission=mission,
            capabilities=capabilities,
            permissions=permissions,
        )
        and getattr(item, "status", None) == "ENABLED"
        for item, name, version, category, mission, capabilities, permissions in definitions
    )
    if not agents_available:
        diagnostics.append("trusted_agents_unavailable")
    activation = await session.scalar(
        select(DispatchActivation).where(
            DispatchActivation.tenant_id == conversation.tenant_id,
            DispatchActivation.workspace_id == conversation.workspace_id,
        )
    )
    if activation is None or not activation.enabled:
        diagnostics.append("dispatch_inactive")
    permissions = (
        await session.scalars(
            select(WorkspaceOperatorPermission.permission).where(
                WorkspaceOperatorPermission.user_id == operator.user_id,
                WorkspaceOperatorPermission.tenant_id == conversation.tenant_id,
                WorkspaceOperatorPermission.workspace_id == conversation.workspace_id,
                WorkspaceOperatorPermission.active.is_(True),
            )
        )
    ).all()
    required = {"workspace.write", "activation.configure", "dispatch.enqueue"}
    if not required.issubset(permissions):
        diagnostics.append("operator_permissions_missing")
    return {
        "ready_for_simulation": compilation.status == "PROPOSED" and not proposal_diagnostics,
        "checked_capabilities": {
            "trusted_agents_available": agents_available,
            "dispatch_enabled": bool(activation and activation.enabled),
            "dispatch_generation": activation.generation if activation else None,
            "operator_permissions_available": required.issubset(permissions),
        },
        "ready_for_launch": False,
        "ready_for_test_launch": False,
        "diagnostics": diagnostics
        + [
            "model_and_environment_unverified",
            "financial_authorization_unverified",
            "separate_human_launch_authorization_missing",
        ],
        "external_effects": False,
    }
