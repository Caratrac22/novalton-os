"""Fail-closed accounting decision, serialized on the authorization row.

Reservations are monotonic because a timeout or lost response can still be
billed. This is an estimated exposure constraint, not a billing guarantee.
No current generation path calls this service; paid integration stays closed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.financial.models import FinancialAuthorization, FinancialReservation


def denied() -> ApplicationError:
    return ApplicationError(
        "financial_authorization_denied", "Autorisation financière indisponible", status_code=403
    )


async def scoped_authorization(
    session: AsyncSession,
    *,
    authorization_id: UUID,
    owner_id: UUID,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    lock: bool = False,
) -> FinancialAuthorization:
    query = select(FinancialAuthorization).where(
        FinancialAuthorization.id == authorization_id,
        FinancialAuthorization.owner_id == owner_id,
        FinancialAuthorization.tenant_id == tenant_id,
        FinancialAuthorization.workspace_id == workspace_id,
        FinancialAuthorization.project_id == project_id,
    )
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise denied()
    return row


async def reserve(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    authorization_id: UUID,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    provider_id: str,
    model_id: str,
    request_id: UUID,
    tokens: int,
    estimated_exposure: Decimal | None,
) -> FinancialReservation:
    """Caller must commit the reservation before provider I/O and never refund ambiguity.

    A transaction waiting on this row sees the latest counters or revocation.
    Idempotent retries return their existing reservation only while authorized.
    """
    if (
        tokens <= 0
        or estimated_exposure is None
        or not estimated_exposure.is_finite()
        or estimated_exposure <= 0
        or estimated_exposure.as_tuple().exponent < -10
    ):
        raise denied()
    await operator.require_human(
        session, "workspace.write", tenant_id=tenant_id, workspace_id=workspace_id
    )
    row = await scoped_authorization(
        session,
        authorization_id=authorization_id,
        owner_id=operator.user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        lock=True,
    )
    if (
        row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
        or row.provider_id != provider_id
        or row.model_id != model_id
    ):
        raise denied()
    existing = await session.scalar(
        select(FinancialReservation).where(
            FinancialReservation.authorization_id == row.id,
            FinancialReservation.request_id == request_id,
        )
    )
    if existing is not None:
        if existing.tokens != tokens or existing.estimate != estimated_exposure:
            raise denied()
        return existing
    if (
        row.request_count >= row.request_limit
        or row.reserved_tokens + tokens > row.token_limit
        or row.reserved_estimate + estimated_exposure > row.estimated_limit
    ):
        raise denied()
    row.request_count += 1
    row.reserved_tokens += tokens
    row.reserved_estimate += estimated_exposure
    reservation = FinancialReservation(
        authorization_id=row.id,
        request_id=request_id,
        tokens=tokens,
        estimate=estimated_exposure,
    )
    session.add(reservation)
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
            action="financial.request.reserved",
            actor_type="local_user",
            actor_id=str(operator.user_id),
            outcome="success",
            metadata={"financial_policy_id": str(row.id), "reservation_id": str(reservation.id)},
        ),
        commit=False,
    )
    return reservation
