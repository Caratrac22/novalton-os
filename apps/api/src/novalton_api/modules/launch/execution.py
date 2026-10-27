"""Test-only authority for a cadrage-bound dispatch and each durable effect."""

from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.identity import WorkspaceOperatorPermission
from novalton_api.modules.durable_dispatch.models import DispatchActivation, TaskDispatch
from novalton_api.modules.launch.models import LaunchAuthorization
from novalton_api.modules.model_catalog.models import ModelDefinition

# Set only by the reauthenticated launch route around one enqueue call.
enqueue_decision: ContextVar[UUID | None] = ContextVar("launch_enqueue_decision", default=None)


def denied() -> ApplicationError:
    return ApplicationError(
        "launch_execution_unverified", "Disposable execution authority unavailable", status_code=409
    )


async def bound_authorization(
    session: AsyncSession, workflow_run_id: UUID
) -> LaunchAuthorization | None:
    return await session.scalar(
        select(LaunchAuthorization)
        .where(LaunchAuthorization.workflow_run_id == workflow_run_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )


async def require_execution(
    session: AsyncSession,
    authorization: LaunchAuthorization,
    *,
    dispatch: TaskDispatch | None = None,
    model: ModelDefinition | None = None,
    require_claim: bool = True,
) -> None:
    """Recheck revocation, generation, scope and the exact zero-price local model.

    Called before enqueue, before every advance, and at every model/tool
    reservation. No transaction spans provider I/O, so a late provider result
    must cross this fence again before it can create a downstream effect.
    """
    from novalton_api.modules.durable_dispatch.authority import current_claim

    settings = get_settings()
    claim = current_claim.get()
    now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
    if (
        settings.environment != "test"
        or (await session.scalar(select(text("current_database()")))) != "novalton_test"
        or not settings.durable_dispatch_enabled
        or settings.local_model_base_url is None
        or settings.local_model_id != authorization.model_id
        or authorization.environment != "DISPOSABLE_TEST"
        or authorization.provider_id != "local"
        or authorization.financial_authorization_id is not None
        or authorization.workflow_run_id is None
        or authorization.revoked_at is not None
        or authorization.expires_at <= now
        or authorization.approved_at + timedelta(seconds=authorization.max_duration_seconds) <= now
        or settings.durable_dispatch_operator_user_id != authorization.owner_id
    ):
        raise denied()
    activation = await session.scalar(
        select(DispatchActivation)
        .where(
            DispatchActivation.tenant_id == authorization.tenant_id,
            DispatchActivation.workspace_id == authorization.workspace_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        activation is None
        or not activation.enabled
        or activation.generation != authorization.dispatch_generation
        or (
            require_claim
            and (
                claim is None
                or claim.workflow_run_id != authorization.workflow_run_id
                or claim.activation_generation != activation.generation
            )
        )
    ):
        raise denied()
    grants = set(
        await session.scalars(
            select(WorkspaceOperatorPermission.permission).where(
                WorkspaceOperatorPermission.user_id == authorization.owner_id,
                WorkspaceOperatorPermission.tenant_id == authorization.tenant_id,
                WorkspaceOperatorPermission.workspace_id == authorization.workspace_id,
                WorkspaceOperatorPermission.active.is_(True),
                WorkspaceOperatorPermission.permission.in_(authorization.permissions),
            )
        )
    )
    if set(authorization.permissions) != {
        "workspace.write",
        "activation.configure",
        "dispatch.enqueue",
    } or grants != set(authorization.permissions):
        raise denied()
    if dispatch is not None and (
        dispatch.workflow_run_id != authorization.workflow_run_id
        or dispatch.tenant_id != authorization.tenant_id
        or dispatch.workspace_id != authorization.workspace_id
        or dispatch.project_id != authorization.project_id
        or dispatch.task_id != authorization.task_id
        or dispatch.max_attempts != 3
        or dispatch.max_model_calls != authorization.max_model_calls
        or dispatch.allow_unknown_cost
        or dispatch.max_estimated_exposure is not None
        or dispatch.deadline
        > authorization.approved_at + timedelta(seconds=authorization.max_duration_seconds)
    ):
        raise denied()
    if model is not None and (
        model.provider_id != "local_cadrage"
        or model.provider_model_id != authorization.model_id
        or model.status != "AVAILABLE"
        or model.execution_target_class != "LOCAL"
        or not model.free_allowlisted
        or model.input_price_per_million != Decimal(0)
        or model.output_price_per_million != Decimal(0)
        or model.currency != "USD"
    ):
        raise denied()
