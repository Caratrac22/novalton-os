"""Trusted operator handoff and revocation against disposable PostgreSQL."""

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from test_development_workflow import QueueProvider, _manager
from test_durable_dispatch import (
    _TEST_PERMISSIONS,
    db_call,
    enqueue,
    operator_for,
    snapshot,
    tick,
)

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.durable_dispatch import provisioning, service
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.durable_dispatch.operator import authenticate_operator

pytest_plugins = ["test_durable_dispatch"]

_NEW_KEY = "mission-six-new-operator-credential-only"


def remove_successors(*identifiers):
    async def cleanup(session):
        await session.execute(
            delete(WorkspaceOperatorPermission).where(
                WorkspaceOperatorPermission.user_id.in_(identifiers)
            )
        )
        await session.execute(delete(HumanOperator).where(HumanOperator.id.in_(identifiers)))
        await session.commit()

    db_call(cleanup)


def test_atomic_handoff_rotates_identity_and_revokes_old_worker(scope, monkeypatch):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    old = operator_for(scope)
    successor_id = uuid4()
    try:
        successor = db_call(
            lambda session: provisioning.rotate_operator(
                session,
                operator=old,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                successor_id=successor_id,
                successor_label="new-operator",
                permissions=frozenset(_TEST_PERMISSIONS.split(",")),
            )
        )
        assert successor.id == successor_id
        with pytest.raises(ApplicationError) as denied:
            tick(scope, provider)
        assert denied.value.status_code == 403
        assert provider.calls == []

        monkeypatch.setenv(
            "NOVALTON_DISPATCH_OPERATOR_KEY_SHA256", hashlib.sha256(_NEW_KEY.encode()).hexdigest()
        )
        monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_ID", "new-operator")
        monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_USER_ID", str(successor_id))
        get_settings.cache_clear()
        with pytest.raises(ApplicationError):
            authenticate_operator("mission-four-dispatch-test-credential-only")
        new = authenticate_operator(_NEW_KEY)
        rows = db_call(
            lambda session: service.list_dispatches(
                session,
                operator=new,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
            )
        )
        assert [item.id for item in rows] == [row.id]
        assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
        assert db_call(
            lambda session: provisioning.revoke_permission(
                session,
                operator=new,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                subject_id=successor_id,
                permission="dispatch.enqueue",
            )
        )
        with pytest.raises(ApplicationError):
            db_call(
                lambda session: new.require_human(
                    session,
                    "dispatch.enqueue",
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
            )

        async def audit(session):
            return list(
                await session.scalars(
                    select(AuditRecord).where(
                        AuditRecord.tenant_id == scope.tenant_id,
                        AuditRecord.action.in_(
                            ["dispatch.operator.rotate", "dispatch.operator.permission.revoke"]
                        ),
                    )
                )
            )

        decisions = db_call(audit)
        assert len(decisions) == 2
        assert {item.actor_id for item in decisions} == {str(old.user_id), str(successor_id)}
    finally:
        remove_successors(successor_id)


def test_concurrent_rotation_has_one_successor_and_scope_is_not_forgeable(scope):
    actor = operator_for(scope)
    candidates = (uuid4(), uuid4())
    permissions = frozenset({"activation.configure", "dispatch.read"})
    try:
        with pytest.raises(ApplicationError):
            db_call(
                lambda session: provisioning.rotate_operator(
                    session,
                    operator=actor,
                    tenant_id=scope.tenant_id,
                    workspace_id=uuid4(),
                    successor_id=uuid4(),
                    successor_label="forged",
                    permissions=permissions,
                )
            )

        def rotate(identifier):
            try:
                return db_call(
                    lambda session: provisioning.rotate_operator(
                        session,
                        operator=actor,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        successor_id=identifier,
                        successor_label="successor",
                        permissions=permissions,
                    )
                ).id
            except ApplicationError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(rotate, candidates))
        assert sum(outcome in candidates for outcome in outcomes) == 1
        assert "dispatch_operator_forbidden" in outcomes
    finally:
        remove_successors(*candidates)


def test_provisioning_revocation_fences_late_generation(scope):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    complete = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await complete(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:
            assert db_call(
                lambda session: provisioning.revoke_permission(
                    session,
                    operator=operator_for(scope),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    subject_id=operator_for(scope).user_id,
                    permission="activation.configure",
                )
            )
        finally:
            released.set()
        with pytest.raises(ApplicationError) as interrupted:
            active.result(timeout=20)
        assert interrupted.value.status_code == 403

    dispatch, attempts, models = snapshot(scope, row.id)
    assert (dispatch.status, len(attempts), len(models), len(provider.calls)) == (
        "BLOCKED",
        1,
        1,
        1,
    )
    assert models[0].status == "SUCCEEDED"
    with pytest.raises(ApplicationError):
        tick(scope, provider)
    assert snapshot(scope, row.id)[0].attempt_count == 1
