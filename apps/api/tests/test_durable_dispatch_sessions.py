"""Signed human session and SQLAlchemy reuse against disposable PostgreSQL."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from test_development_workflow import _cleanup, _seed
from test_durable_dispatch import db_call, operator_for

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.durable_dispatch import oidc_keys, provisioning, service
from novalton_api.modules.durable_dispatch.identity import (
    FederatedOperatorIdentity,
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.durable_dispatch.models import DispatchActivation
from novalton_api.modules.durable_dispatch.saas_access import require_saas_access
from novalton_api.modules.durable_dispatch.sessions import authenticate_session
from novalton_api.modules.projects.models import Project

pytest_plugins = ["test_durable_dispatch"]


def test_rotating_jwks_still_requires_bound_human_and_workspace(scope, federated, monkeypatch):
    monkeypatch.delenv("NOVALTON_OPERATOR_OIDC_PUBLIC_KEY_PEM")
    monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_JWKS_URI", "https://identity.example.test/jwks")
    get_settings.cache_clear()

    async def keys(_uri):
        return {"current": federated.public_key}

    monkeypatch.setattr(oidc_keys, "_fetch", keys)
    monkeypatch.setattr(oidc_keys, "_cached_uri", None)
    token = federated(kid="current")
    base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch"
    with TestClient(create_app()) as client:
        assert (
            client.get(f"{base}/requests", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )
        assert (
            client.get(
                f"{base}/requests", headers={"Authorization": f"Bearer {federated(kid='other')}"}
            ).status_code
            == 401
        )
        monkeypatch.setattr(oidc_keys, "_cached_until", 0)

        async def revoked(_uri):
            return {}

        monkeypatch.setattr(oidc_keys, "_fetch", revoked)
        assert (
            client.get(f"{base}/requests", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )


@pytest.fixture
def federated(scope, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    public_pem = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    issuer = "https://identity.example.test/"
    monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_ISSUER", issuer)
    monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_AUDIENCE", "novalton-operator")
    monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_PUBLIC_KEY_PEM", public_pem)
    get_settings.cache_clear()
    subject_id = operator_for(scope).user_id
    db_call(
        lambda session: provisioning.bind_federated_subject(
            session,
            operator=operator_for(scope),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            subject_id=subject_id,
            issuer=issuer,
            subject="human-123",
        )
    )

    def token(*, offset=0, audience="novalton-operator", subject="human-123", human=True, kid=None):
        now = int(datetime.now(UTC).timestamp())
        claims = {
            "iss": issuer,
            "sub": subject,
            "aud": audience,
            "iat": now + offset - 120,
            "exp": now + offset + 1800,
        }
        if human:
            claims["auth_time"] = now + offset - 130
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid} if kid else None)

    token.public_key = private.public_key()

    yield token
    db_call(lambda session: _remove_binding(session, subject_id))
    get_settings.cache_clear()


async def _remove_binding(session, user_id):
    await session.execute(
        delete(FederatedOperatorIdentity).where(FederatedOperatorIdentity.user_id == user_id)
    )
    await session.commit()


def test_signed_session_requires_exact_binding_scope_and_valid_claims(scope, federated):
    base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch"
    with TestClient(create_app()) as client:
        valid = {"Authorization": "Bearer " + federated()}
        assert client.get(f"{base}/requests", headers=valid).status_code == 200
        assert (
            client.get(
                f"{base}/requests", headers={"X-User-Id": str(operator_for(scope).user_id)}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests",
                headers={"Authorization": "Bearer " + federated(subject="other")},
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests",
                headers={"Authorization": "Bearer " + federated(audience="other")},
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests", headers={"Authorization": "Bearer " + federated(offset=-3600)}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests", headers={"Authorization": "Bearer " + federated(offset=3600)}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests", headers={"Authorization": "Bearer " + federated(human=False)}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace_id}/dispatch/requests",
                headers=valid,
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{uuid4()}/dispatch/requests",
                headers=valid,
            ).status_code
            == 403
        )


def test_federated_workflow_evidence_requires_read_authority(scope, federated):
    from test_development_workflow import QueueProvider
    from test_durable_dispatch import enqueue

    row, _, _ = enqueue(scope, QueueProvider([]))
    base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch"
    with TestClient(create_app()) as client:
        headers = {"Authorization": "Bearer " + federated()}
        response = client.get(f"{base}/requests/{row.id}/workflow", headers=headers)
        assert response.status_code == 200
        assert response.json()["workflow_run"]["id"] == str(row.workflow_run_id)
        assert client.get(f"{base}/requests/{uuid4()}/workflow", headers=headers).status_code == 404
        assert (
            client.get(
                f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace_id}"
                f"/dispatch/requests/{row.id}/workflow",
                headers=headers,
            ).status_code
            == 403
        )


def test_signed_human_operates_completed_workflow_and_loses_authority(scope, federated):
    """Exercise signed identity, real API routes, PostgreSQL and all three agent steps."""
    from test_development_workflow import QueueProvider, _manager, _qa, _worker
    from test_durable_dispatch import enqueue, other_task, snapshot, tick

    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    completed, _, _ = enqueue(scope, provider, max_attempts=3, max_model_calls=3)
    base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch"
    headers = {"Authorization": f"Bearer {federated()}"}
    with TestClient(create_app()) as client:
        assert str(completed.id) in {
            item["id"] for item in client.get(f"{base}/requests", headers=headers).json()
        }
        assert [tick(scope, provider).outcome.value for _ in range(3)] == [
            "STEP_COMPLETED",
            "STEP_COMPLETED",
            "WORKFLOW_COMPLETED",
        ]
        dispatch, attempts, models = snapshot(scope, completed.id)
        assert dispatch.status == "DONE"
        assert len(attempts) == len(models) == len(provider.calls) == 3
        assert [model.status for model in models] == ["SUCCEEDED"] * 3
        view = client.get(f"{base}/requests/{completed.id}/workflow", headers=headers)
        assert view.status_code == 200
        assert view.json()["workflow_run"]["status"] == "COMPLETED"
        assert len(view.json()["step_details"]) == 3
        evidence = client.get(f"{base}/requests/{completed.id}/cost-evidence", headers=headers)
        assert evidence.status_code == 200 and len(evidence.json()) == 3
        assert all(not item["provider_billing_verified"] for item in evidence.json())
        history = client.get(f"{base}/requests/{completed.id}/attempts", headers=headers)
        assert history.status_code == 200 and len(history.json()) == 3
        pending, _, _ = enqueue(other_task(scope), QueueProvider([]), max_attempts=3)
        cancel_path = f"{base}/requests/{pending.id}/cancel"
        assert client.post(cancel_path, headers=headers).status_code == 200
        assert client.post(cancel_path, headers=headers).status_code == 200
        assert (
            client.get(f"{base}/requests/{pending.id}/workflow", headers=headers).status_code == 200
        )
        assert (
            client.get(
                f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace_id}/dispatch/requests",
                headers=headers,
            ).status_code
            == 403
        )
        db_call(
            lambda session: provisioning.revoke_federated_subject(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                subject_id=operator_for(scope).user_id,
            )
        )
        assert client.get(f"{base}/requests", headers=headers).status_code == 401
        assert client.post(cancel_path, headers=headers).status_code == 401


def test_bound_session_fenced_after_revocation_with_reused_session(scope, federated):
    async def work():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                actor = await authenticate_session(
                    session,
                    token=federated(),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
                await service.list_dispatches(
                    session,
                    operator=actor,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
                await session.commit()
                before = await session.get(DispatchActivation, scope.workspace_id)
                assert before is not None and before.enabled
                generation = before.generation
                await provisioning.revoke_federated_subject(
                    session,
                    operator=operator_for(scope),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    subject_id=operator_for(scope).user_id,
                )
                activation = await session.get(DispatchActivation, scope.workspace_id)
                assert activation is not None and not activation.enabled
                assert activation.generation == generation + 1
                with pytest.raises(ApplicationError) as denied:
                    await service.list_dispatches(
                        session,
                        operator=actor,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                    )
                assert denied.value.status_code == 403
        finally:
            await database.dispose()

    asyncio.run(work())


def test_permission_revoke_fences_reused_federated_session(scope, federated):
    async def work():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                actor = await authenticate_session(
                    session,
                    token=federated(),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
                await service.list_dispatches(
                    session,
                    operator=actor,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )
                await session.commit()
                assert await provisioning.revoke_permission(
                    session,
                    operator=operator_for(scope),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    subject_id=operator_for(scope).user_id,
                    permission="dispatch.read",
                )
                with pytest.raises(ApplicationError) as denied:
                    await service.list_dispatches(
                        session,
                        operator=actor,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                    )
                assert denied.value.status_code == 403
        finally:
            await database.dispose()

    asyncio.run(work())


def test_concurrent_session_decision_serializes_revoke(scope, federated):
    acquired, release, revoked = threading.Event(), threading.Event(), threading.Event()

    def decision():
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    actor = await authenticate_session(
                        session,
                        token=federated(),
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                    )
                    await actor.require_human(
                        session,
                        "dispatch.read",
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                    )
                    acquired.set()
                    await asyncio.to_thread(release.wait, 10)
                    await session.commit()
            finally:
                await database.dispose()

        asyncio.run(execute())

    def revoke():
        assert acquired.wait(10)
        db_call(
            lambda session: provisioning.revoke_federated_subject(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                subject_id=operator_for(scope).user_id,
            )
        )
        revoked.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(decision)
        second = pool.submit(revoke)
        try:
            assert acquired.wait(10)
            time.sleep(0.15)
            assert not revoked.is_set()
        finally:
            release.set()
        first.result(timeout=15)
        second.result(timeout=15)
    with TestClient(create_app()) as client:
        assert (
            client.get(
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch/requests",
                headers={"Authorization": "Bearer " + federated()},
            ).status_code
            == 401
        )


def test_saas_routes_require_human_grants_and_isolate_sql_scopes(scope, federated, monkeypatch):
    """Direct HTTP, two humans/tenants, real rows, pagination, revocation on test PostgreSQL."""
    other = asyncio.run(_seed())
    other_user = uuid4()
    extra_ids = [uuid4() for _ in range(105)]
    from novalton_api.modules.workspaces.models import Workspace

    async def provision(session):
        session.add(HumanOperator(id=other_user, label="human-b", active=True))
        await session.flush()
        session.add(
            TenantOperatorMembership(
                user_id=other_user, tenant_id=other.tenant_id, role="MEMBER", active=True
            )
        )
        session.add(
            FederatedOperatorIdentity(
                user_id=other_user,
                issuer="https://identity.example.test/",
                subject="human-b",
                active=True,
            )
        )
        session.add_all(
            [
                WorkspaceOperatorPermission(
                    user_id=operator_for(scope).user_id,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    permission=permission,
                    active=True,
                )
                for permission in ("workspace.read", "workspace.write")
            ]
        )
        session.add_all(
            [
                WorkspaceOperatorPermission(
                    user_id=other_user,
                    tenant_id=other.tenant_id,
                    workspace_id=other.workspace_id,
                    permission=permission,
                    active=True,
                )
                for permission in ("workspace.read", "workspace.write")
            ]
        )
        session.add(Workspace(tenant_id=scope.tenant_id, name="Ungrant workspace", slug="ungrant"))
        session.add_all(
            [
                Project(
                    id=identifier,
                    workspace_id=scope.workspace_id,
                    name=f"Additional {index}",
                    slug=f"additional-{index}",
                    status="ACTIVE",
                )
                for index, identifier in enumerate(extra_ids)
            ]
        )
        await session.commit()

    async def cleanup(session):
        await session.execute(delete(Project).where(Project.id.in_(extra_ids)))
        await session.execute(
            delete(Workspace).where(
                Workspace.tenant_id == scope.tenant_id, Workspace.slug == "ungrant"
            )
        )
        await session.execute(
            delete(WorkspaceOperatorPermission).where(
                WorkspaceOperatorPermission.user_id == other_user
            )
        )
        await session.execute(
            delete(WorkspaceOperatorPermission).where(
                WorkspaceOperatorPermission.user_id == operator_for(scope).user_id,
                WorkspaceOperatorPermission.permission.in_(["workspace.read", "workspace.write"]),
            )
        )
        await session.execute(
            delete(FederatedOperatorIdentity).where(FederatedOperatorIdentity.user_id == other_user)
        )
        await session.execute(
            delete(TenantOperatorMembership).where(TenantOperatorMembership.user_id == other_user)
        )
        await session.execute(delete(HumanOperator).where(HumanOperator.id == other_user))
        await session.commit()

    try:
        db_call(provision)
        ungranted = db_call(
            lambda session: session.scalar(
                select(Workspace.id).where(
                    Workspace.tenant_id == scope.tenant_id, Workspace.slug == "ungrant"
                )
            )
        )
        monkeypatch.setenv("NOVALTON_TEST_LEGACY_API_AUTH_BYPASS", "false")
        get_settings.cache_clear()
        base_a = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        base_b = f"/api/v1/tenants/{other.tenant_id}/workspaces/{other.workspace_id}"
        valid_a = {"Authorization": "Bearer " + federated()}
        valid_b = {"Authorization": "Bearer " + federated(subject="human-b")}

        async def stream_entry(session):
            request = Request(
                {"type": "http", "method": "GET", "path": f"{base_a}/events/stream", "headers": []}
            )
            await require_saas_access(
                request, scope.tenant_id, scope.workspace_id, session, valid_a["Authorization"]
            )
            return session.in_transaction()

        assert db_call(stream_entry) is False
        with TestClient(create_app()) as client:
            assert client.get(f"{base_a}/projects").status_code == 401
            assert (
                client.post(
                    f"{base_a}/projects", json={"name": "forged", "slug": "forged"}
                ).status_code
                == 401
            )
            assert client.get(f"{base_a}/events/stream").status_code == 401
            assert (
                client.get(
                    f"{base_a}/projects", headers={"X-Workspace-ID": str(scope.workspace_id)}
                ).status_code
                == 401
            )
            assert (
                client.get(
                    f"{base_a}/projects",
                    headers={"Authorization": "Bearer " + federated(offset=-3600)},
                ).status_code
                == 401
            )
            page = client.get(
                f"{base_a}/projects", headers=valid_a, params={"limit": 20, "offset": 100}
            )
            assert page.status_code == 200 and len(page.json()["items"]) == 6
            first = client.get(
                f"{base_a}/projects", headers=valid_a, params={"limit": 100, "offset": 0}
            )
            assert not {row["id"] for row in first.json()["items"]} & {
                row["id"] for row in page.json()["items"]
            }
            assert client.get(f"{base_b}/projects", headers=valid_a).status_code == 403
            assert (
                client.get(
                    f"/api/v1/tenants/{scope.tenant_id}/workspaces/{ungranted}/projects",
                    headers=valid_a,
                ).status_code
                == 403
            )
            assert (
                client.get(
                    f"{base_b}/projects",
                    headers={**valid_a, "X-Workspace-ID": str(other.workspace_id)},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    f"{base_b}/projects", headers=valid_a, json={"name": "forged", "slug": "forged"}
                ).status_code
                == 403
            )
            assert (
                client.get(f"{base_b}/projects/{other.project_id}", headers=valid_b).status_code
                == 200
            )
            assert (
                client.get(f"{base_a}/projects/{other.project_id}", headers=valid_a).status_code
                == 404
            )
            assert (
                client.get(
                    f"{base_a}/projects/{scope.project_id}/tasks/{other.task_id}", headers=valid_a
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"{base_b}/projects/{other.project_id}/tasks/{other.task_id}", headers=valid_b
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{base_b}/projects/{other.project_id}/tasks/{other.task_id}",
                    headers=valid_a,
                    json={"title": "forged"},
                ).status_code
                == 403
            )
            assert client.get(f"{base_b}/workflow-runs", headers=valid_a).status_code == 403
            assert client.get(f"{base_a}/workflow-runs", headers=valid_a).status_code == 200
            assert (
                client.get(
                    f"{base_a}/workflow-runs",
                    headers=valid_a,
                    params={"task_id": str(other.task_id)},
                ).json()["items"]
                == []
            )
            assert (
                client.patch(
                    f"{base_a}/projects/{scope.project_id}",
                    headers=valid_a,
                    json={"name": "A authorized"},
                ).status_code
                == 200
            )

            # A grant removed after a page load fences the next mutation and read.
            async def revoke(session):
                await session.execute(
                    update(WorkspaceOperatorPermission)
                    .where(
                        WorkspaceOperatorPermission.user_id == operator_for(scope).user_id,
                        WorkspaceOperatorPermission.tenant_id == scope.tenant_id,
                        WorkspaceOperatorPermission.workspace_id == scope.workspace_id,
                        WorkspaceOperatorPermission.permission.in_(
                            ["workspace.read", "workspace.write"]
                        ),
                    )
                    .values(active=False, revoked_at=datetime.now(UTC))
                )
                await session.commit()

            db_call(revoke)
            assert (
                client.patch(
                    f"{base_a}/projects/{scope.project_id}",
                    headers=valid_a,
                    json={"name": "denied"},
                ).status_code
                == 403
            )
            assert client.get(f"{base_a}/projects", headers=valid_a).status_code == 403
            assert client.get(f"{base_b}/projects", headers=valid_b).status_code == 200

            async def make_viewer(session):
                await session.execute(
                    update(TenantOperatorMembership)
                    .where(
                        TenantOperatorMembership.user_id == other_user,
                        TenantOperatorMembership.tenant_id == other.tenant_id,
                    )
                    .values(role="VIEWER")
                )
                await session.commit()

            db_call(make_viewer)
            assert client.get(f"{base_b}/projects", headers=valid_b).status_code == 200
            assert (
                client.patch(
                    f"{base_b}/projects/{other.project_id}",
                    headers=valid_b,
                    json={"name": "denied viewer"},
                ).status_code
                == 403
            )
    finally:
        monkeypatch.setenv("NOVALTON_TEST_LEGACY_API_AUTH_BYPASS", "true")
        get_settings.cache_clear()
        db_call(cleanup)
        asyncio.run(_cleanup(other))
