"""Real PostgreSQL local identity and private project chat; deterministic local HTTP model."""

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select, update

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.cadrage import service as cadrage_service
from novalton_api.modules.cadrage.compilation import compile_document
from novalton_api.modules.cadrage.models import (
    CadrageCompilation,
    CadrageConversation,
    CadrageMessage,
    CadragePlan,
    CadrageSpecification,
)
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.local_auth.bootstrap import (
    BootstrapDenied,
    bootstrap_owner,
    recover_owner,
)
from novalton_api.modules.local_auth.models import LocalCredential, LocalLoginThrottle, LocalSession
from novalton_api.modules.local_auth.service import hash_password
from novalton_api.modules.projects.models import Project
from novalton_api.modules.provider_keys.models import ProviderKey
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


def db_call(operation):
    async def run():
        db = Database.from_settings(Settings.from_environment())
        try:
            async with db.session_factory() as session:
                return await operation(session)
        finally:
            await db.dispose()

    return asyncio.run(run())


@dataclass
class Scope:
    tenant: UUID
    workspace: UUID
    owner: UUID
    login: str


def settings_for_new_scope() -> tuple[Settings, str]:
    suffix = uuid4().hex[:12]
    return Settings.from_environment().model_copy(
        update={
            "bootstrap_tenant_id": uuid4(),
            "bootstrap_workspace_id": uuid4(),
            "bootstrap_tenant_slug": f"local-{suffix}",
            "bootstrap_workspace_slug": f"local-{suffix}",
        }
    ), f"owner-{suffix}"


async def wipe(session, scope: Scope) -> None:
    await session.execute(delete(RuntimeEvent).where(RuntimeEvent.tenant_id == scope.tenant))
    await session.execute(delete(ProviderKey).where(ProviderKey.tenant_id == scope.tenant))
    await session.execute(
        delete(CadrageCompilation).where(
            CadrageCompilation.plan_id.in_(
                select(CadragePlan.id)
                .join(CadrageConversation)
                .where(CadrageConversation.tenant_id == scope.tenant)
            )
        )
    )
    await session.execute(
        delete(CadragePlan).where(
            CadragePlan.conversation_id.in_(
                select(CadrageConversation.id).where(CadrageConversation.tenant_id == scope.tenant)
            )
        )
    )
    await session.execute(
        delete(CadrageSpecification).where(
            CadrageSpecification.conversation_id.in_(
                select(CadrageConversation.id).where(CadrageConversation.tenant_id == scope.tenant)
            )
        )
    )
    await session.execute(
        delete(CadrageMessage).where(
            CadrageMessage.conversation_id.in_(
                select(CadrageConversation.id).where(CadrageConversation.tenant_id == scope.tenant)
            )
        )
    )
    await session.execute(
        delete(CadrageConversation).where(CadrageConversation.tenant_id == scope.tenant)
    )
    await session.execute(delete(AuditRecord).where(AuditRecord.tenant_id == scope.tenant))
    await session.execute(delete(Project).where(Project.workspace_id == scope.workspace))
    await session.execute(delete(LocalSession).where(LocalSession.user_id == scope.owner))
    await session.execute(delete(LocalCredential).where(LocalCredential.user_id == scope.owner))
    await session.execute(
        delete(WorkspaceOperatorPermission).where(
            WorkspaceOperatorPermission.tenant_id == scope.tenant
        )
    )
    await session.execute(
        delete(TenantOperatorMembership).where(TenantOperatorMembership.tenant_id == scope.tenant)
    )
    await session.execute(delete(HumanOperator).where(HumanOperator.id == scope.owner))
    await session.execute(delete(Workspace).where(Workspace.id == scope.workspace))
    await session.execute(delete(Tenant).where(Tenant.id == scope.tenant))
    await session.execute(
        delete(LocalLoginThrottle).where(
            LocalLoginThrottle.login_sha256 == hashlib.sha256(scope.login.encode()).hexdigest()
        )
    )
    await session.commit()


@pytest.fixture
def initialized(monkeypatch):
    settings, name = settings_for_new_scope()
    password = "Sample-Passphrase-Only-For-Tests-42"

    async def setup(session):
        async with session.begin():
            owner = await bootstrap_owner(session, settings=settings, login=name, password=password)
            return Scope(
                settings.bootstrap_tenant_id, settings.bootstrap_workspace_id, owner.id, name
            )

    scope = db_call(setup)
    monkeypatch.setenv("NOVALTON_TEST_LEGACY_API_AUTH_BYPASS", "false")
    get_settings.cache_clear()
    try:
        yield scope, password, settings
    finally:
        db_call(lambda session: wipe(session, scope))
        get_settings.cache_clear()


def path(scope: Scope) -> str:
    return f"/api/v1/tenants/{scope.tenant}/workspaces/{scope.workspace}"


def test_privileged_recovery_revokes_sessions_and_preserves_grants(initialized):
    scope, password, settings = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        assert client.get(path(scope) + "/projects", headers=auth).status_code == 200

        async def failed(session):
            with pytest.raises(BootstrapDenied):
                async with session.begin():
                    await recover_owner(
                        session,
                        settings=settings,
                        login="missing-user",
                        password="New-Recovery-Password-42",
                    )

        db_call(failed)
        assert client.get(path(scope) + "/projects", headers=auth).status_code == 200

        async def recover(session):
            async with session.begin():
                await recover_owner(
                    session,
                    settings=settings,
                    login=scope.login,
                    password="New-Recovery-Password-42",
                )

        db_call(recover)
        assert client.get(path(scope) + "/projects", headers=auth).status_code == 401
        assert (
            client.post(
                "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
            ).status_code
            == 401
        )
        new = client.post(
            "/api/v1/local-auth/login",
            json={"login": scope.login, "password": "New-Recovery-Password-42"},
        )
        assert new.status_code == 200
        assert (
            client.get(
                path(scope) + "/projects",
                headers={"Authorization": f"Bearer {new.json()['token']}"},
            ).status_code
            == 200
        )


def test_specification_versions_are_scoped_immutable_and_optimistic(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Document", "slug": "document", "description": None},
        )
        assert project.status_code == 201
        base = path(scope) + f"/projects/{project.json()['id']}/conversations"
        conversation = client.post(base, headers=auth, json={"title": "Objectif"}).json()["id"]
        specs = base + f"/{conversation}/specifications"
        first = client.put(
            specs,
            headers=auth,
            json={
                "expected_version": 0,
                "summary": "Recherche documentaire",
                "items": [
                    {
                        "topic": "objective",
                        "value": "Comparer des sources",
                        "provenance": "USER",
                        "state": "CONFIRMED",
                    }
                ],
            },
        )
        assert first.status_code == 200 and first.json()["version"] == 1
        assert (
            client.put(
                specs,
                headers=auth,
                json={
                    "expected_version": 0,
                    "summary": "Écrasement obsolète",
                    "items": [],
                },
            ).status_code
            == 409
        )
        second = client.put(
            specs,
            headers=auth,
            json={
                "expected_version": 1,
                "summary": "Comparaison de sources vérifiées",
                "items": [
                    {
                        "topic": "objective",
                        "value": "Comparer des sources vérifiées",
                        "provenance": "USER",
                        "state": "CONFIRMED",
                    }
                ],
            },
        )
        assert second.status_code == 200 and second.json()["version"] == 2
        assert (
            client.get(specs + "/1", headers=auth).json()["document"]["summary"]
            == "Recherche documentaire"
        )
        assert [item["version"] for item in client.get(specs, headers=auth).json()["items"]] == [
            2,
            1,
        ]
        plan_url = base + f"/{conversation}/plans"
        plan = client.post(plan_url, headers=auth, json={"expected_specification_version": 2})
        assert plan.status_code == 201 and plan.json()["status"] == "DRAFT"
        decision_url = plan_url + f"/{plan.json()['id']}/decision"
        assert (
            client.post(decision_url, headers=auth, json={"decision": "APPROVED"}).status_code
            == 409
        )
        ready = client.post(decision_url, headers=auth, json={"decision": "READY_FOR_REVIEW"})
        assert ready.status_code == 200
        approved = client.post(decision_url, headers=auth, json={"decision": "APPROVED"})
        assert approved.status_code == 200 and approved.json()["decided_by"] == str(scope.owner)
        assert (
            client.post(decision_url, headers=auth, json={"decision": "APPROVED"}).status_code
            == 409
        )
        assert (
            client.put(
                specs,
                headers=auth,
                json={
                    "expected_version": 2,
                    "summary": "Changement de périmètre",
                    "items": [],
                },
            ).status_code
            == 200
        )
        assert client.get(plan_url, headers=auth).json()["items"][0]["status"] == "SUPERSEDED"
        assert (
            client.post(decision_url, headers=auth, json={"decision": "APPROVED"}).status_code
            == 409
        )
        assert client.get(specs, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.get(base + f"/{uuid4()}/specifications", headers=auth).status_code == 404


def test_compiler_refuses_vague_injected_and_duplicate_inputs():
    scope = [{"topic": "objective", "value": "Créer un site", "state": "CONFIRMED"}]
    status, result = compile_document({"scope": scope, "unresolved": []})
    assert status == "BLOCKED" and result["steps"] == []
    assert "unsupported_or_missing_execution_kind" in result["diagnostics"]
    scope += [
        {"topic": "execution.kind", "value": "development", "state": "CONFIRMED"},
        {"topic": "acceptance.1", "value": "curl https://evil.test", "state": "CONFIRMED"},
        {"topic": "objective", "value": "Autre objectif", "state": "CONFIRMED"},
    ]
    status, result = compile_document({"scope": scope, "unresolved": []})
    assert status == "BLOCKED" and "duplicate_confirmed_topic:objective" in result["diagnostics"]
    assert "invalid_development_handoff" in result["diagnostics"] or result["steps"] == []


def test_approved_plan_compilation_is_idempotent_scoped_and_revoked(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Compilation", "slug": "compilation", "description": None},
        ).json()
        task = client.post(
            path(scope) + f"/projects/{project['id']}/tasks",
            headers=auth,
            json={"title": "Implémenter"},
        ).json()
        base = path(scope) + f"/projects/{project['id']}/conversations"
        conversation = client.post(base, headers=auth, json={"title": "Projet"}).json()["id"]
        specs = base + f"/{conversation}/specifications"

        def item(topic, value):
            return {"topic": topic, "value": value, "provenance": "USER", "state": "CONFIRMED"}

        document = {
            "expected_version": 0,
            "summary": "Construire une fonctionnalité",
            "items": [
                item("objective", "Construire un formulaire"),
                item("execution.kind", "development"),
                item("acceptance.1", "Le formulaire valide les champs"),
            ],
        }
        assert client.put(specs, headers=auth, json=document).status_code == 200
        plan_url = base + f"/{conversation}/plans"
        plan = client.post(
            plan_url, headers=auth, json={"expected_specification_version": 1}
        ).json()
        compile_url = plan_url + f"/{plan['id']}/compilations"
        assert (
            client.post(compile_url, headers=auth, json={"task_id": task["id"]}).status_code == 409
        )
        decision = plan_url + f"/{plan['id']}/decision"
        assert (
            client.post(decision, headers=auth, json={"decision": "READY_FOR_REVIEW"}).status_code
            == 200
        )
        assert client.post(decision, headers=auth, json={"decision": "APPROVED"}).status_code == 200
        unknown = client.post(compile_url, headers=auth, json={"task_id": str(uuid4())})
        assert unknown.status_code == 404
        first = client.post(compile_url, headers=auth, json={"task_id": task["id"]})
        assert first.status_code == 201 and first.json()["status"] == "PROPOSED"
        repeated = client.post(compile_url, headers=auth, json={"task_id": task["id"]})
        assert repeated.json()["id"] == first.json()["id"]
        check_url = compile_url + f"/{first.json()['id']}/preflight"
        check = client.get(check_url, headers=auth).json()["preflight"]
        assert check["ready_for_simulation"] is True and check["ready_for_launch"] is False
        assert client.get(compile_url + f"/{uuid4()}/preflight", headers=auth).status_code == 404
        document["expected_version"] = 1
        document["summary"] = "Nouvelle version"
        assert client.put(specs, headers=auth, json=document).status_code == 200
        assert (
            client.post(compile_url, headers=auth, json={"task_id": task["id"]}).status_code == 409
        )
        check = client.get(check_url, headers=auth).json()["preflight"]
        assert check["ready_for_simulation"] is False
        assert "plan_obsolete_or_not_approved" in check["diagnostics"]


def test_personal_provider_key_is_encrypted_isolated_and_revocable(initialized, monkeypatch):
    scope, password, _ = initialized
    monkeypatch.setenv(
        "NOVALTON_BYOK_KEYRING", json.dumps({"v1": base64.b64encode(b"x" * 32).decode()})
    )
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v1")
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        url = path(scope) + "/provider-keys/openrouter"
        secret = "fake-test-secret-never-reveal"
        assert (
            client.put(url, json={"secret": secret, "current_password": password}).status_code
            == 401
        )
        assert (
            client.put(
                url, headers=auth, json={"secret": secret, "current_password": "wrong"}
            ).status_code
            == 401
        )
        saved = client.put(url, headers=auth, json={"secret": secret, "current_password": password})
        assert saved.status_code == 200 and saved.json()["enabled"] is False
        assert secret not in saved.text
        listing = client.get(path(scope) + "/provider-keys", headers=auth)
        assert listing.status_code == 200 and secret not in listing.text
        assert (
            client.get(
                f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace}/provider-keys",
                headers=auth,
            ).status_code
            == 403
        )

        async def encrypted(session):
            record = await session.scalar(
                select(ProviderKey).where(ProviderKey.owner_id == scope.owner)
            )
            assert record is not None and secret.encode() not in record.ciphertext
            assert record.key_id == "v1"

        db_call(encrypted)
        assert (
            client.patch(
                url, headers=auth, json={"enabled": True, "current_password": password}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                url, headers=auth, json={"enabled": False, "current_password": password}
            ).status_code
            == 200
        )
        assert (
            client.request(
                "DELETE", url, headers=auth, json={"current_password": password}
            ).status_code
            == 204
        )
        assert client.get(path(scope) + "/provider-keys", headers=auth).json()["items"] == []


def test_sensitive_key_reauthentication_is_rate_limited(initialized, monkeypatch):
    scope, password, _ = initialized
    monkeypatch.setenv(
        "NOVALTON_BYOK_KEYRING", json.dumps({"v1": base64.b64encode(b"x" * 32).decode()})
    )
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v1")
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        url = path(scope) + "/provider-keys/openrouter"
        for _ in range(5):
            assert (
                client.put(
                    url,
                    headers=auth,
                    json={"secret": "fake-secret-test", "current_password": "invalid"},
                ).status_code
                == 401
            )
        assert (
            client.put(
                url, headers=auth, json={"secret": "fake-secret-test", "current_password": password}
            ).status_code
            == 401
        )


def test_local_owner_auth_and_durable_scoped_chat(initialized):
    scope, password, settings = initialized
    with TestClient(create_app()) as client:
        assert client.get(path(scope) + "/projects").status_code == 401
        assert (
            client.post(
                "/api/v1/local-auth/login", json={"login": "absent", "password": password}
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        )
        assert response.status_code == 200
        token = response.json()["token"]
        assert token.startswith("nvl_") and password not in response.text
        assert response.json()["scopes"] == [
            {"tenant_id": str(scope.tenant), "workspace_id": str(scope.workspace)}
        ]
        auth = {"Authorization": f"Bearer {token}"}
        assert client.get(path(scope) + "/projects", headers=auth).status_code == 200
        assert (
            client.get(
                f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace}/projects", headers=auth
            ).status_code
            == 403
        )
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Site web", "slug": "site", "description": None},
        )
        assert project.status_code == 201
        base = path(scope) + f"/projects/{project.json()['id']}/conversations"
        assert client.post(base, headers=auth, json={"title": "  "}).status_code == 422
        conversation = client.post(base, headers=auth, json={"title": "Site pour artisans"})
        assert conversation.status_code == 201
        endpoint = base + f"/{conversation.json()['id']}/messages"
        request_id = str(uuid4())
        first = client.post(
            endpoint,
            headers=auth,
            json={"content": "Je voudrais un site web", "client_request_id": request_id},
        )
        assert first.status_code == 201 and first.json()["assistant_status"] == "MODEL_UNAVAILABLE"
        duplicate = client.post(
            endpoint,
            headers=auth,
            json={"content": "Je voudrais un site web", "client_request_id": request_id},
        )
        assert duplicate.status_code == 201 and duplicate.json()["created"] is False
        assert (
            client.post(
                endpoint, headers=auth, json={"content": "Autre", "client_request_id": request_id}
            ).status_code
            == 409
        )
        assert (
            client.post(
                endpoint,
                headers=auth,
                json={"content": "x" * 4001, "client_request_id": str(uuid4())},
            ).status_code
            == 422
        )
        listed = client.get(endpoint, headers=auth, params={"after": 0, "limit": 1})
        assert listed.status_code == 200 and len(listed.json()["items"]) == 1
        assert listed.json()["items"][0]["content"] == "Je voudrais un site web"
        assert client.get(endpoint, headers=auth, params={"after": 1}).json()["items"] == []
        assert client.get(base, headers=auth).json()["items"][0]["id"] == conversation.json()["id"]

        # Second human shares the project workspace but not the owner's private conversation.
        async def add_reader(session):
            other = HumanOperator(label="reader-" + uuid4().hex[:8], active=True)
            session.add(other)
            await session.flush()
            session.add(
                TenantOperatorMembership(
                    user_id=other.id, tenant_id=scope.tenant, role="VIEWER", active=True
                )
            )
            session.add(
                WorkspaceOperatorPermission(
                    user_id=other.id,
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                    permission="workspace.read",
                    active=True,
                )
            )
            session.add(
                LocalCredential(
                    user_id=other.id,
                    login="reader-" + uuid4().hex[:12],
                    password_hash=hash_password(password),
                    changed_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return other.id, (await session.get(LocalCredential, other.id)).login

        reader_id, reader_login = db_call(add_reader)
        try:
            second = client.post(
                "/api/v1/local-auth/login", json={"login": reader_login, "password": password}
            )
            assert second.status_code == 200
            reader = {"Authorization": f"Bearer {second.json()['token']}"}
            assert client.get(path(scope) + "/projects", headers=reader).status_code == 200
            assert client.get(base, headers=reader).json()["items"] == []
            assert client.get(endpoint, headers=reader).status_code == 404
            assert client.post(base, headers=reader, json={"title": "Interdit"}).status_code == 403
        finally:

            async def remove_reader(session):
                await session.execute(delete(LocalSession).where(LocalSession.user_id == reader_id))
                await session.execute(
                    delete(LocalCredential).where(LocalCredential.user_id == reader_id)
                )
                await session.execute(
                    delete(WorkspaceOperatorPermission).where(
                        WorkspaceOperatorPermission.user_id == reader_id
                    )
                )
                await session.execute(
                    delete(TenantOperatorMembership).where(
                        TenantOperatorMembership.user_id == reader_id
                    )
                )
                await session.execute(delete(HumanOperator).where(HumanOperator.id == reader_id))
                await session.execute(
                    delete(LocalLoginThrottle).where(
                        LocalLoginThrottle.login_sha256
                        == hashlib.sha256(reader_login.encode()).hexdigest()
                    )
                )
                await session.commit()

            db_call(remove_reader)

        async def revoke_write(session):
            await session.execute(
                update(WorkspaceOperatorPermission)
                .where(
                    WorkspaceOperatorPermission.user_id == scope.owner,
                    WorkspaceOperatorPermission.permission == "workspace.write",
                )
                .values(active=False, revoked_at=datetime.now(UTC))
            )
            await session.commit()

        db_call(revoke_write)
        assert (
            client.post(
                endpoint,
                headers=auth,
                json={"content": "Refusé", "client_request_id": str(uuid4())},
            ).status_code
            == 403
        )

        async def restore_write(session):
            await session.execute(
                update(WorkspaceOperatorPermission)
                .where(
                    WorkspaceOperatorPermission.user_id == scope.owner,
                    WorkspaceOperatorPermission.permission == "workspace.write",
                )
                .values(active=True, revoked_at=None)
            )
            await session.commit()

        db_call(restore_write)

        assert (
            client.post(
                f"/api/v1/tenants/{scope.tenant}/workspaces/{uuid4()}/account/password",
                headers=auth,
                json={"current": password, "replacement": "Wrong-Scope-Passphrase-47"},
            ).status_code
            == 403
        )

        changed = client.post(
            path(scope) + "/account/password",
            headers=auth,
            json={"current": password, "replacement": "Changed-Passphrase-For-Tests-47"},
        )
        assert changed.status_code == 204
        assert client.get(path(scope) + "/projects", headers=auth).status_code == 401
        assert (
            client.post(
                "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
            ).status_code
            == 401
        )
        newer = client.post(
            "/api/v1/local-auth/login",
            json={"login": scope.login, "password": "Changed-Passphrase-For-Tests-47"},
        )
        assert newer.status_code == 200
        fresh = {"Authorization": f"Bearer {newer.json()['token']}"}
        assert (
            client.get(endpoint, headers=fresh).json()["items"][0]["content"]
            == "Je voudrais un site web"
        )
        assert client.post("/api/v1/local-auth/logout", headers=fresh).status_code == 204
        assert client.get(path(scope) + "/projects", headers=fresh).status_code == 401


def test_two_local_accounts_isolate_tenants_and_private_conversations(initialized):
    first, password, _ = initialized
    settings, name = settings_for_new_scope()

    async def add_second(session):
        tenant = Tenant(
            id=settings.bootstrap_tenant_id,
            slug=settings.bootstrap_tenant_slug,
            name=settings.bootstrap_tenant_name,
        )
        session.add(tenant)
        await session.flush()
        session.add(
            Workspace(
                id=settings.bootstrap_workspace_id,
                tenant_id=tenant.id,
                slug=settings.bootstrap_workspace_slug,
                name=settings.bootstrap_workspace_name,
            )
        )
        user = HumanOperator(label=name, active=True)
        session.add(user)
        await session.flush()
        session.add(
            LocalCredential(
                user_id=user.id,
                login=name,
                password_hash=hash_password(password),
                changed_at=datetime.now(UTC),
            )
        )
        session.add(
            TenantOperatorMembership(
                user_id=user.id, tenant_id=tenant.id, role="MEMBER", active=True
            )
        )
        for permission in ("workspace.read", "workspace.write"):
            session.add(
                WorkspaceOperatorPermission(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    workspace_id=settings.bootstrap_workspace_id,
                    permission=permission,
                    active=True,
                )
            )
        await session.commit()
        return Scope(tenant.id, settings.bootstrap_workspace_id, user.id, name)

    second = db_call(add_second)
    try:
        with TestClient(create_app()) as client:

            def authenticate(scope):
                response = client.post(
                    "/api/v1/local-auth/login",
                    json={"login": scope.login, "password": password},
                )
                assert response.status_code == 200
                return {"Authorization": f"Bearer {response.json()['token']}"}

            a, b = authenticate(first), authenticate(second)
            project = client.post(
                path(second) + "/projects",
                headers=b,
                json={"name": "Privé B", "slug": "private-b", "description": None},
            )
            assert project.status_code == 201
            base = path(second) + f"/projects/{project.json()['id']}/conversations"
            conversation = client.post(base, headers=b, json={"title": "Objectif B"})
            assert conversation.status_code == 201
            specs = base + f"/{conversation.json()['id']}/specifications"
            created = client.put(
                specs,
                headers=b,
                json={
                    "expected_version": 0,
                    "summary": "Privé à B",
                    "items": [
                        {
                            "topic": "objective",
                            "value": "Document B",
                            "provenance": "USER",
                            "state": "CONFIRMED",
                        }
                    ],
                },
            )
            assert created.status_code == 200
            plans = base + f"/{conversation.json()['id']}/plans"
            assert (
                client.post(
                    plans, headers=b, json={"expected_specification_version": 1}
                ).status_code
                == 201
            )
            assert client.get(path(second) + "/projects", headers=a).status_code == 403
            assert client.get(base, headers=a).status_code == 403
            assert client.get(base + f"/{conversation.json()['id']}", headers=a).status_code == 403
            assert client.get(specs, headers=a).status_code == 403
            assert client.get(plans, headers=a).status_code == 403
            assert client.get(path(second) + "/provider-keys", headers=a).status_code == 403
            assert client.post(base, headers=a, json={"title": "Intrusion"}).status_code == 403
            assert client.get(path(first) + "/projects", headers=b).status_code == 403

            async def revoke_second(session):
                await session.execute(
                    update(WorkspaceOperatorPermission)
                    .where(
                        WorkspaceOperatorPermission.user_id == second.owner,
                        WorkspaceOperatorPermission.permission == "workspace.write",
                    )
                    .values(active=False, revoked_at=datetime.now(UTC))
                )
                await session.commit()

            db_call(revoke_second)
            assert (
                client.post(base, headers=b, json={"title": "Après révocation"}).status_code == 403
            )
            assert (
                client.put(
                    specs,
                    headers=b,
                    json={
                        "expected_version": 1,
                        "summary": "Après révocation",
                        "items": [],
                    },
                ).status_code
                == 403
            )
            assert (
                client.post(
                    plans, headers=b, json={"expected_specification_version": 1}
                ).status_code
                == 403
            )
            assert client.get(base, headers=b).status_code == 200
    finally:
        db_call(lambda session: wipe(session, second))


def test_concurrent_messages_reserve_one_model_reply(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login",
            json={"login": scope.login, "password": password},
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Concurrence", "slug": "concurrency", "description": None},
        ).json()
        base = path(scope) + f"/projects/{project['id']}/conversations"
        conversation = client.post(base, headers=auth, json={"title": "Test simultané"}).json()

        async def race():
            db = Database.from_settings(Settings.from_environment())

            async def contender(content):
                async with db.session_factory() as session:
                    row = await cadrage_service.get_conversation(
                        session,
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        project_id=UUID(project["id"]),
                        owner_id=scope.owner,
                        conversation_id=UUID(conversation["id"]),
                        lock=True,
                    )
                    return await cadrage_service.append_user_message(
                        session,
                        conversation=row,
                        content=content,
                        request_id=uuid4(),
                        reserve_for_model=True,
                    )

            try:
                return await asyncio.gather(
                    contender("Première demande"),
                    contender("Deuxième demande"),
                    return_exceptions=True,
                )
            finally:
                await db.dispose()

        results = asyncio.run(race())
        assert sum(isinstance(item, tuple) for item in results) == 1
        denied = next(item for item in results if isinstance(item, Exception))
        assert isinstance(denied, ApplicationError) and denied.status_code == 409
        rows = client.get(base + f"/{conversation['id']}/messages", headers=auth).json()["items"]
        assert len(rows) == 1 and rows[0]["role"] == "USER"


def test_bootstrap_one_owner_and_transaction_failure(monkeypatch):
    settings, name = settings_for_new_scope()
    password = "First-Owner-Passphrase-For-Tests"

    async def race():
        db = Database.from_settings(Settings.from_environment())

        async def contender():
            try:
                async with db.session_factory.begin() as session:
                    owner = await bootstrap_owner(
                        session, settings=settings, login=name, password=password
                    )
                    return owner.id
            except BootstrapDenied:
                return None

        try:
            return await asyncio.gather(contender(), contender())
        finally:
            await db.dispose()

    # A failed audit append rolls back scope, credential and grants together.
    from novalton_api.modules.local_auth import bootstrap as bootstrap_module

    original_append = bootstrap_module.append_record

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(bootstrap_module, "append_record", fail_audit)

    async def failed_once(session):
        async with session.begin():
            await bootstrap_owner(session, settings=settings, login=name, password=password)

    with pytest.raises(RuntimeError):
        db_call(failed_once)
    assert db_call(lambda session: session.get(Tenant, settings.bootstrap_tenant_id)) is None
    monkeypatch.setattr(bootstrap_module, "append_record", original_append)
    winners = asyncio.run(race())
    assert sum(item is not None for item in winners) == 1
    scope = Scope(
        settings.bootstrap_tenant_id,
        settings.bootstrap_workspace_id,
        next(item for item in winners if item is not None),
        name,
    )
    db_call(lambda session: wipe(session, scope))


def test_repeated_login_and_expired_session(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        for _ in range(5):
            assert (
                client.post(
                    "/api/v1/local-auth/login",
                    json={"login": scope.login, "password": "bad-password"},
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
            ).status_code
            == 401
        )

    # Reset only the test throttle and create a valid session to expire in SQL.
    async def reset_throttle(session):
        await session.execute(
            delete(LocalLoginThrottle).where(
                LocalLoginThrottle.login_sha256 == hashlib.sha256(scope.login.encode()).hexdigest()
            )
        )
        await session.commit()

    db_call(reset_throttle)
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]

        async def expire(session):
            await session.execute(
                update(LocalSession)
                .where(LocalSession.user_id == scope.owner)
                .values(
                    created_at=datetime.now(UTC) - timedelta(hours=2),
                    expires_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await session.commit()

        db_call(expire)
        assert (
            client.get(
                path(scope) + "/projects", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )


def test_local_provider_endpoint_rejects_ssrf_and_half_configuration():
    for url in (
        "http://169.254.169.254/v1",
        "http://127.0.0.1:8000/v1",
        "http://localhost:1234/v1",
        "https://example.com/v1",
    ):
        with pytest.raises(ValidationError):
            Settings(local_model_base_url=url, local_model_id="model")
    with pytest.raises(ValidationError):
        Settings(local_model_base_url="http://127.0.0.1:1234/v1")
    assert (
        Settings(
            local_model_base_url="http://127.0.0.1:11434/v1", local_model_id="ollama-model"
        ).local_model_id
        == "ollama-model"
    )


def test_local_http_model_two_adaptive_turns_and_malformed_reply(initialized, monkeypatch):
    scope, password, _ = initialized
    monkeypatch.setenv("NOVALTON_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("NOVALTON_LOCAL_MODEL_ID", "local-test")
    get_settings.cache_clear()
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1" and request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        seen.append(body)
        assert sum(item["role"] == "system" for item in body["messages"]) == 1
        user_messages = [
            item["content"]
            for item in body["messages"]
            if item["role"] == "user" and not item["content"].startswith("Titre du projet (")
        ]
        if "malformed" in user_messages[-1]:
            content = "not JSON"
        elif len(user_messages) == 1:
            content = json.dumps(
                {
                    "reply": "Quel public visez-vous ?",
                    "questions": ["Qui visitera le site ?"],
                    "unresolved": ["public"],
                    "proposals": [{"topic": "objective", "value": "Site vitrine"}],
                }
            )
        else:
            content = json.dumps(
                {
                    "reply": "Vous ciblez des artisans.",
                    "questions": ["Quelles pages faut-il ?"],
                    "unresolved": ["pages"],
                    "proposals": [{"topic": "objective", "value": "Site marchand"}],
                }
            )
        return httpx.Response(
            200,
            json={
                "model": "local-test",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )

    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(provider_id="local_cadrage", base_url="http://127.0.0.1:1234/v1"),
        transport=httpx.MockTransport(respond),
    )
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry([provider]))) as client:
            token = client.post(
                "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
            ).json()["token"]
            auth = {"Authorization": f"Bearer {token}"}
            project = client.post(
                path(scope) + "/projects",
                headers=auth,
                json={"name": "Web", "slug": "web", "description": None},
            ).json()
            base = path(scope) + f"/projects/{project['id']}/conversations"
            conversation = client.post(base, headers=auth, json={"title": "Site"}).json()
            endpoint = base + f"/{conversation['id']}/messages"
            first_id = str(uuid4())
            first = client.post(
                endpoint,
                headers=auth,
                json={"content": "Je veux un site web", "client_request_id": first_id},
            )
            assert first.status_code == 201 and first.json()["assistant_status"] == "AVAILABLE"
            assert "Qui visitera" in first.json()["assistant"]["content"]
            repeated = client.post(
                endpoint,
                headers=auth,
                json={"content": "Je veux un site web", "client_request_id": first_id},
            )
            assert repeated.json()["created"] is False and len(seen) == 1
            second = client.post(
                endpoint,
                headers=auth,
                json={"content": "Des artisans", "client_request_id": str(uuid4())},
            )
            assert (
                second.status_code == 201
                and "Quelles pages" in second.json()["assistant"]["content"]
            )
            assert len(seen) == 2 and "Je veux un site web" in str(seen[1]["messages"])
            specs = client.get(base + f"/{conversation['id']}/specifications", headers=auth)
            assert specs.status_code == 200
            entries = specs.json()["items"][0]["document"]["items"]
            assert entries[0]["state"] == "PROPOSED"
            assert entries[1]["topic"] == "conflict.objective" and entries[1]["state"] == "CONFLICT"
            bad = client.post(
                endpoint,
                headers=auth,
                json={"content": "malformed", "client_request_id": str(uuid4())},
            )
            assert bad.status_code == 201 and bad.json()["assistant_status"] == "PROVIDER_ERROR"
        with TestClient(create_app(provider_registry=ProviderRegistry([provider]))) as reopened:
            token = reopened.post(
                "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
            ).json()["token"]
            rows = reopened.get(endpoint, headers={"Authorization": f"Bearer {token}"}).json()[
                "items"
            ]
            assert [item["role"] for item in rows] == [
                "USER",
                "ASSISTANT",
                "USER",
                "ASSISTANT",
                "USER",
            ]
    finally:
        asyncio.run(provider.aclose())
        get_settings.cache_clear()
