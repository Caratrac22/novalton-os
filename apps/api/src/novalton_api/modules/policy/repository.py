"""SQL owned by the policy module."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.tenants.models import Tenant


async def tenant_exists(session: AsyncSession, *, tenant_id: UUID) -> bool:
    return await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is not None


async def create_rule(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID | None,
    name: str,
    enabled: bool,
    action_pattern: str,
    effect: str,
    actor_type: str | None,
    resource_type: str | None,
    conditions_json: list[dict[str, object]],
) -> PolicyRule:
    rule = PolicyRule(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name=name,
        enabled=enabled,
        action_pattern=action_pattern,
        effect=effect,
        actor_type=actor_type,
        resource_type=resource_type,
        conditions_json=conditions_json,
    )
    session.add(rule)
    await session.flush()
    return rule


async def list_applicable_rules(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> list[PolicyRule]:
    result = await session.scalars(
        select(PolicyRule)
        .where(
            PolicyRule.tenant_id == tenant_id,
            PolicyRule.enabled.is_(True),
            or_(PolicyRule.workspace_id.is_(None), PolicyRule.workspace_id == workspace_id),
        )
        .order_by(PolicyRule.created_at.asc(), PolicyRule.id.asc())
    )
    return list(result)
