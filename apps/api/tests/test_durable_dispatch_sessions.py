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
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_durable_dispatch import db_call, operator_for

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.durable_dispatch import provisioning, service
from novalton_api.modules.durable_dispatch.identity import FederatedOperatorIdentity
from novalton_api.modules.durable_dispatch.models import DispatchActivation
from novalton_api.modules.durable_dispatch.sessions import authenticate_session

pytest_plugins = ["test_durable_dispatch"]


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

    def token(*, offset=0, audience="novalton-operator", subject="human-123", human=True):
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
        return jwt.encode(claims, private, algorithm="RS256")

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
