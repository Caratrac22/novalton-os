"""Human decision about an immutable specification-derived plan; no dispatch calls."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.cadrage.models import CadrageConversation, CadragePlan
from novalton_api.modules.cadrage.service import current_specification


def missing() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def snapshot(document: dict) -> dict:
    """A traceable draft based only on confirmed content, never invented resources."""
    confirmed = [entry for entry in document["items"] if entry["state"] == "CONFIRMED"]
    open_items = [entry for entry in document["items"] if entry["state"] != "CONFIRMED"]
    return {
        "objective": document["summary"],
        "scope": confirmed,
        "steps": [
            "Valider le périmètre et les critères de réussite avec le propriétaire",
            "Détailler les livrables confirmés et leurs dépendances",
            "Soumettre toute exécution aux autorisations gouvernées distinctes",
        ],
        "unresolved": open_items,
        "resources": [],
        "agents": [],
        "permissions": [],
        "budget": "Non vérifié ; aucune dépense autorisée par ce plan",
        "origin": "Assemblage déterministe des informations confirmées ; à relire humainement",
    }


async def create_plan(
    session: AsyncSession, *, conversation: CadrageConversation, expected_version: int, owner: UUID
) -> CadragePlan:
    spec = await current_specification(session, conversation)
    if spec is None or spec.version != expected_version:
        raise ApplicationError(
            "specification_conflict", "Cahier des charges obsolète", status_code=409
        )
    if not spec.document["summary"].strip() or not any(
        item["state"] == "CONFIRMED" for item in spec.document["items"]
    ):
        raise ApplicationError("plan_incomplete", "Confirmez d'abord l'objectif", status_code=409)
    existing = await session.scalar(
        select(CadragePlan).where(CadragePlan.specification_id == spec.id)
    )
    if existing:
        return existing
    plan = CadragePlan(
        conversation_id=conversation.id,
        specification_id=spec.id,
        source_version=spec.version,
        document=snapshot(spec.document),
        status="DRAFT",
    )
    session.add(plan)
    await session.flush()
    await _audit(session, conversation, owner, "cadrage.plan.create", plan)
    await session.commit()
    return plan


async def get_plan(
    session: AsyncSession, *, conversation: CadrageConversation, plan_id: UUID, lock: bool = False
) -> CadragePlan:
    query = select(CadragePlan).where(
        CadragePlan.id == plan_id, CadragePlan.conversation_id == conversation.id
    )
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise missing()
    return row


async def _audit(
    session: AsyncSession,
    conversation: CadrageConversation,
    owner: UUID,
    action: str,
    plan: CadragePlan,
) -> None:
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=conversation.tenant_id,
            workspace_id=conversation.workspace_id,
            action=action,
            actor_type="local_user",
            actor_id=str(owner),
            outcome="success",
            resource_type="project",
            resource_id=conversation.project_id,
            project_id=conversation.project_id,
            metadata={"plan_id": str(plan.id), "specification_version": plan.source_version},
        ),
        commit=False,
    )


async def decide(
    session: AsyncSession,
    *,
    conversation: CadrageConversation,
    plan: CadragePlan,
    owner: UUID,
    decision: str,
) -> CadragePlan:
    spec = await current_specification(session, conversation)
    if spec is None or spec.id != plan.specification_id or plan.status == "SUPERSEDED":
        raise ApplicationError("plan_obsolete", "Plan dépassé", status_code=409)
    if decision == "READY_FOR_REVIEW":
        if plan.status != "DRAFT" or plan.document["unresolved"]:
            raise ApplicationError(
                "plan_incomplete", "Résolvez les points incertains", status_code=409
            )
    elif decision in {"APPROVED", "REJECTED", "NEEDS_CHANGES"}:
        if plan.status != "READY_FOR_REVIEW":
            raise ApplicationError("plan_not_ready", "Plan non soumis à la revue", status_code=409)
        plan.decided_by, plan.decided_at = owner, datetime.now(UTC)
    else:
        raise ApplicationError("invalid_decision", "Décision invalide", status_code=422)
    plan.status = decision
    await _audit(session, conversation, owner, f"cadrage.plan.{decision.lower()}", plan)
    await session.commit()
    return plan
