"""Real PostgreSQL local identity and private project chat; deterministic local HTTP model."""

import asyncio
import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from test_development_workflow import QueueProvider, _manager, _qa, _worker

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
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
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.durable_dispatch import service as dispatch_service
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.operator import authenticate_operator
from novalton_api.modules.durable_dispatch.sessions import authenticate_session
from novalton_api.modules.financial.models import FinancialAuthorization, FinancialReservation
from novalton_api.modules.financial.service import reserve as reserve_financial
from novalton_api.modules.launch import routes as launch_routes
from novalton_api.modules.launch.models import LaunchAuthorization
from novalton_api.modules.local_auth.bootstrap import (
    BootstrapDenied,
    bootstrap_owner,
    recover_owner,
)
from novalton_api.modules.local_auth.models import LocalCredential, LocalLoginThrottle, LocalSession
from novalton_api.modules.local_auth.service import hash_password
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.projects.models import Project
from novalton_api.modules.provider_keys.models import ProviderKey
from novalton_api.modules.provider_keys.rotate import rotate_records
from novalton_api.modules.provider_keys.vault import Keyring, VaultUnavailable
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.tools.models import ToolCall
from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepHandoff,
    WorkflowStepRun,
)
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
    await session.execute(
        delete(AgentChallengeResolution).where(AgentChallengeResolution.tenant_id == scope.tenant)
    )
    await session.execute(
        delete(DispatchAttempt).where(
            DispatchAttempt.dispatch_id.in_(
                select(TaskDispatch.id).where(TaskDispatch.tenant_id == scope.tenant)
            )
        )
    )
    await session.execute(delete(TaskDispatch).where(TaskDispatch.tenant_id == scope.tenant))
    await session.execute(
        delete(LaunchAuthorization).where(LaunchAuthorization.tenant_id == scope.tenant)
    )
    run_ids = select(WorkflowRun.id).where(WorkflowRun.tenant_id == scope.tenant)
    plan_ids = select(WorkflowPlan.id).where(WorkflowPlan.tenant_id == scope.tenant)
    await session.execute(
        delete(WorkflowStepHandoff).where(WorkflowStepHandoff.workflow_run_id.in_(run_ids))
    )
    await session.execute(
        delete(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id.in_(run_ids))
    )
    await session.execute(delete(ToolCall).where(ToolCall.tenant_id == scope.tenant))
    await session.execute(
        update(AgentRun).where(AgentRun.tenant_id == scope.tenant).values(model_run_id=None)
    )
    await session.execute(delete(ModelRun).where(ModelRun.tenant_id == scope.tenant))
    await session.execute(delete(AgentRun).where(AgentRun.tenant_id == scope.tenant))
    await session.execute(delete(WorkflowRun).where(WorkflowRun.tenant_id == scope.tenant))
    await session.execute(
        delete(WorkflowStepDependency).where(WorkflowStepDependency.workflow_plan_id.in_(plan_ids))
    )
    await session.execute(delete(WorkflowStep).where(WorkflowStep.workflow_plan_id.in_(plan_ids)))
    await session.execute(delete(WorkflowPlan).where(WorkflowPlan.tenant_id == scope.tenant))
    await session.execute(delete(AgentDefinition).where(AgentDefinition.tenant_id == scope.tenant))
    await session.execute(
        delete(DispatchActivation).where(DispatchActivation.tenant_id == scope.tenant)
    )
    await session.execute(
        delete(ModelDefinition).where(
            ModelDefinition.provider_id == "local_cadrage",
            ModelDefinition.provider_model_id == f"launch-{scope.login}",
        )
    )
    await session.execute(
        delete(FinancialReservation).where(
            FinancialReservation.authorization_id.in_(
                select(FinancialAuthorization.id).where(
                    FinancialAuthorization.tenant_id == scope.tenant
                )
            )
        )
    )
    await session.execute(
        delete(FinancialAuthorization).where(FinancialAuthorization.tenant_id == scope.tenant)
    )
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


def test_financial_authorization_requires_explicit_reauth_and_is_revocable(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Budget", "slug": "budget", "description": None},
        ).json()
        url = path(scope) + f"/projects/{project['id']}/financial-authorizations"
        payload = {
            "confirmation": "AUTHORIZE_ESTIMATED_EXPOSURE",
            "provider_id": "openrouter",
            "model_id": "test-model",
            "currency": "USD",
            "request_limit": 1,
            "token_limit": 100,
            "estimated_limit": "0.01",
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "current_password": password,
        }
        assert client.post(url, json=payload).status_code == 401
        assert (
            client.post(
                url, headers=auth, json={**payload, "current_password": "wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post(url, headers=auth, json={**payload, "confirmation": "yes"}).status_code
            == 422
        )
        created = client.post(url, headers=auth, json=payload)
        assert created.status_code == 201, created.text
        grant = created.json()
        assert grant["paid_generation_enabled"] is False
        assert grant["billing"] == "BILLING_UNVERIFIED"
        assert grant["currency"] == "USD"
        assert len(client.get(url, headers=auth).json()["items"]) == 1

        async def attempt(session, *, request_id, model="test-model", tokens=30):
            operator = await authenticate_session(
                session, token=token, tenant_id=scope.tenant, workspace_id=scope.workspace
            )
            result = await reserve_financial(
                session,
                operator=operator,
                authorization_id=UUID(grant["id"]),
                tenant_id=scope.tenant,
                workspace_id=scope.workspace,
                project_id=UUID(project["id"]),
                provider_id="openrouter",
                model_id=model,
                currency="USD",
                request_id=request_id,
                tokens=tokens,
                estimated_exposure=Decimal("0.004"),
            )
            await session.commit()
            return result.id

        async def wrong_model(session):
            with pytest.raises(ApplicationError):
                await attempt(session, request_id=uuid4(), model="foreign-model")

        db_call(wrong_model)

        async def denied_boundaries(session):
            operator = await authenticate_session(
                session, token=token, tenant_id=scope.tenant, workspace_id=scope.workspace
            )
            for authorization_id, project_id, tokens, estimate in (
                (uuid4(), UUID(project["id"]), 1, Decimal("0.001")),
                (UUID(grant["id"]), uuid4(), 1, Decimal("0.001")),
                (UUID(grant["id"]), UUID(project["id"]), 101, Decimal("0.001")),
                (UUID(grant["id"]), UUID(project["id"]), 1, Decimal("0.02")),
                (UUID(grant["id"]), UUID(project["id"]), 1, Decimal("0.00000000001")),
            ):
                with pytest.raises(ApplicationError):
                    await reserve_financial(
                        session,
                        operator=operator,
                        authorization_id=authorization_id,
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        project_id=project_id,
                        provider_id="openrouter",
                        model_id="test-model",
                        currency="USD",
                        request_id=uuid4(),
                        tokens=tokens,
                        estimated_exposure=estimate,
                    )

        db_call(denied_boundaries)
        assert (
            client.post(url, headers=auth, json={**payload, "currency": "EUR"}).status_code == 422
        )

        async def wrong_currency(session):
            operator = await authenticate_session(
                session, token=token, tenant_id=scope.tenant, workspace_id=scope.workspace
            )
            with pytest.raises(ApplicationError):
                await reserve_financial(
                    session,
                    operator=operator,
                    authorization_id=UUID(grant["id"]),
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                    project_id=UUID(project["id"]),
                    provider_id="openrouter",
                    model_id="test-model",
                    currency="EUR",
                    request_id=uuid4(),
                    tokens=1,
                    estimated_exposure=Decimal("0.001"),
                )

        db_call(wrong_currency)

        async def set_grant(session, active):
            await session.execute(
                update(WorkspaceOperatorPermission)
                .where(
                    WorkspaceOperatorPermission.user_id == scope.owner,
                    WorkspaceOperatorPermission.tenant_id == scope.tenant,
                    WorkspaceOperatorPermission.workspace_id == scope.workspace,
                    WorkspaceOperatorPermission.permission == "workspace.write",
                )
                .values(active=active, revoked_at=None if active else datetime.now(UTC))
            )
            await session.commit()

        db_call(lambda session: set_grant(session, False))

        async def revoked_grant(session):
            with pytest.raises(ApplicationError):
                await attempt(session, request_id=uuid4())

        db_call(revoked_grant)
        db_call(lambda session: set_grant(session, True))

        async def set_project_status(session, status):
            await session.execute(
                update(Project)
                .where(
                    Project.id == UUID(project["id"]),
                    Project.workspace_id == scope.workspace,
                )
                .values(status=status)
            )
            await session.commit()

        db_call(lambda session: set_project_status(session, "PAUSED"))

        async def paused_project(session):
            with pytest.raises(ApplicationError):
                await attempt(session, request_id=uuid4())

        db_call(paused_project)
        db_call(lambda session: set_project_status(session, "ACTIVE"))
        one = uuid4()
        first = db_call(lambda session: attempt(session, request_id=one))
        assert first == db_call(lambda session: attempt(session, request_id=one))

        async def quota(session):
            with pytest.raises(ApplicationError):
                await attempt(session, request_id=uuid4())

        db_call(quota)
        revoked = client.post(
            url + f"/{grant['id']}/revoke",
            headers=auth,
            json={"current_password": password},
        )
        assert revoked.status_code == 200 and revoked.json()["version"] == 2
        assert revoked.json()["revoked_at"] is not None

        async def late(session):
            with pytest.raises(ApplicationError):
                await attempt(session, request_id=one)

        db_call(late)


def test_financial_reservation_serializes_concurrent_requests(initialized):
    scope, password, _ = initialized
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Concurrence", "slug": "concurrence", "description": None},
        ).json()
        url = path(scope) + f"/projects/{project['id']}/financial-authorizations"
        grant = client.post(
            url,
            headers=auth,
            json={
                "confirmation": "AUTHORIZE_ESTIMATED_EXPOSURE",
                "provider_id": "openrouter",
                "model_id": "test-model",
                "currency": "USD",
                "request_limit": 1,
                "token_limit": 20,
                "estimated_limit": "0.01",
                "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "current_password": password,
            },
        )
        assert grant.status_code == 201, grant.text
        grant_id = UUID(grant.json()["id"])

        async def race():
            db = Database.from_settings(Settings.from_environment())
            async with db.session_factory() as auth_session:
                operator = await authenticate_session(
                    auth_session,
                    token=token,
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                )
                await auth_session.rollback()

            async def one():
                async with db.session_factory() as session:
                    try:
                        await reserve_financial(
                            session,
                            operator=operator,
                            authorization_id=grant_id,
                            tenant_id=scope.tenant,
                            workspace_id=scope.workspace,
                            project_id=UUID(project["id"]),
                            provider_id="openrouter",
                            model_id="test-model",
                            currency="USD",
                            request_id=uuid4(),
                            tokens=20,
                            estimated_exposure=Decimal("0.01"),
                        )
                        await session.commit()
                        return "reserved"
                    except ApplicationError:
                        await session.rollback()
                        return "denied"

            try:
                return await asyncio.gather(one(), one())
            finally:
                await db.dispose()

        assert sorted(asyncio.run(race())) == ["denied", "reserved"]
        assert client.get(url, headers=auth).json()["items"][0]["request_count"] == 1


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
        other_project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Autre projet", "slug": "other-compilation", "description": None},
        ).json()
        other_task = client.post(
            path(scope) + f"/projects/{other_project['id']}/tasks",
            headers=auth,
            json={"title": "Tâche hors projet"},
        ).json()
        assert (
            client.post(compile_url, headers=auth, json={"task_id": other_task["id"]}).status_code
            == 404
        )
        first = client.post(compile_url, headers=auth, json={"task_id": task["id"]})
        assert first.status_code == 201 and first.json()["status"] == "PROPOSED"
        repeated = client.post(compile_url, headers=auth, json={"task_id": task["id"]})
        assert repeated.json()["id"] == first.json()["id"]
        check_url = compile_url + f"/{first.json()['id']}/preflight"
        check = client.get(check_url, headers=auth).json()["preflight"]
        assert check["ready_for_simulation"] is True and check["ready_for_launch"] is False
        assert check["ready_for_test_launch"] is False
        assert "trusted_agents_unavailable" in check["diagnostics"]
        assert "dispatch_inactive" in check["diagnostics"]
        assert "task_not_runnable" in check["diagnostics"]
        assert check["checked_capabilities"]["dispatch_generation"] is None
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
        assert client.get(check_url, headers={"Authorization": "Bearer invalid"}).status_code == 401


@pytest.mark.parametrize("mode", ["qa_pass", "revoke_mid", "cancel_mid"])
def test_separate_launch_decision_creates_inert_workflow_and_revokes(
    initialized, monkeypatch, mode
):
    scope, password, _ = initialized
    model_id = f"launch-{scope.login}"
    monkeypatch.setenv("NOVALTON_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("NOVALTON_LOCAL_MODEL_ID", model_id)
    monkeypatch.setenv("NOVALTON_DURABLE_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_USER_ID", str(scope.owner))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_TENANT_ID", str(scope.tenant))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_WORKSPACE_ID", str(scope.workspace))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_ID", scope.login)
    operator_key = "disposable-test-dispatch-key-only"
    monkeypatch.setenv(
        "NOVALTON_DISPATCH_OPERATOR_KEY_SHA256", hashlib.sha256(operator_key.encode()).hexdigest()
    )
    monkeypatch.setenv(
        "NOVALTON_DISPATCH_OPERATOR_PERMISSIONS",
        "activation.configure,dispatch.enqueue,dispatch.read,dispatch.cancel,dispatch.resolve",
    )
    monkeypatch.setenv("NOVALTON_MODEL_ROUTER_FORCE_MODEL", f"local_cadrage::{model_id}")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        project = client.post(
            path(scope) + "/projects",
            headers=auth,
            json={"name": "Launch test", "slug": "launch-test", "description": None},
        ).json()
        task = client.post(
            path(scope) + f"/projects/{project['id']}/tasks",
            headers=auth,
            json={"title": "Borne jetable"},
        ).json()
        base = path(scope) + f"/projects/{project['id']}/conversations"
        conversation = client.post(base, headers=auth, json={"title": "Décision"}).json()["id"]
        specs = base + f"/{conversation}/specifications"
        document = {
            "expected_version": 0,
            "summary": "Un formulaire jetable",
            "items": [
                {"topic": key, "value": value, "provenance": "USER", "state": "CONFIRMED"}
                for key, value in (
                    ("objective", "Créer un formulaire"),
                    ("execution.kind", "development"),
                    ("acceptance.1", "Les champs sont vérifiés"),
                )
            ],
        }
        assert client.put(specs, headers=auth, json=document).status_code == 200
        plan_url = base + f"/{conversation}/plans"
        plan = client.post(
            plan_url, headers=auth, json={"expected_specification_version": 1}
        ).json()
        decision = plan_url + f"/{plan['id']}/decision"
        assert (
            client.post(decision, headers=auth, json={"decision": "READY_FOR_REVIEW"}).status_code
            == 200
        )
        assert client.post(decision, headers=auth, json={"decision": "APPROVED"}).status_code == 200
        compilation = client.post(
            plan_url + f"/{plan['id']}/compilations", headers=auth, json={"task_id": task["id"]}
        ).json()
        url = plan_url + f"/{plan['id']}/compilations/{compilation['id']}/launch-authorizations"
        request = {
            "confirmation": "AUTHORIZE_DISPOSABLE_TEST_LAUNCH",
            "request_id": str(uuid4()),
            "environment": "DISPOSABLE_TEST",
            "provider_id": "local",
            "model_id": model_id,
            "max_model_calls": 3,
            "max_duration_seconds": 180,
            "current_password": password,
        }
        assert client.post(url, json=request).status_code == 401
        assert client.post(url, headers=auth, json=request).status_code == 403

        async def grant(session):
            for permission in ("activation.configure", "dispatch.enqueue", "dispatch.cancel"):
                session.add(
                    WorkspaceOperatorPermission(
                        user_id=scope.owner,
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        permission=permission,
                        active=True,
                    )
                )
            await session.commit()

        db_call(grant)
        assert client.post(url, headers=auth, json=request).status_code == 409  # BACKLOG

        async def ready(session):
            await session.execute(
                update(Task).where(Task.id == UUID(task["id"])).values(status="READY")
            )
            await session.commit()

        db_call(ready)
        assert client.post(
            url, headers=auth, json=request | {"current_password": "wrong"}
        ).status_code in {401, 403}
        assert (
            client.post(url, headers=auth, json=request | {"confirmation": "YES"}).status_code
            == 422
        )
        created = client.post(url, headers=auth, json=request)
        assert created.status_code == 201, created.text
        assert created.json()["workflow_created"] is False
        assert created.json()["financial_authorization_id"] is None
        assert client.post(url, headers=auth, json=request).json()["id"] == created.json()["id"]
        assert (
            client.post(url, headers=auth, json=request | {"model_id": "changed"}).status_code
            == 409
        )
        assert client.get(url, headers=auth).json()["items"][0]["id"] == created.json()["id"]
        assert (
            client.get(url.replace(str(compilation["id"]), str(uuid4())), headers=auth).status_code
            == 404
        )

        async def no_run(session):
            return await session.scalar(
                select(WorkflowRun.id).where(WorkflowRun.tenant_id == scope.tenant)
            )

        assert db_call(no_run) is None
        launch_url = url + f"/{created.json()['id']}/workflow"
        launch_request = {
            "confirmation": "CREATE_DISPOSABLE_TEST_WORKFLOW",
            "request_id": str(uuid4()),
            "current_password": password,
        }
        assert client.post(launch_url, headers=auth, json=launch_request).status_code == 409

        async def enable_local(session):
            session.add(
                DispatchActivation(
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                    enabled=True,
                    generation=1,
                )
            )
            session.add(
                ModelDefinition(
                    provider_id="local_cadrage",
                    provider_model_id=model_id,
                    display_name="Disposable local test",
                    status="AVAILABLE",
                    execution_target_class="LOCAL",
                    free_allowlisted=True,
                    context_window=128_000,
                    reasoning=True,
                    coding=True,
                    structured_output=True,
                    contract_enforcement_grade="PROVIDER_ENFORCED",
                    enforcement_metadata_source="disposable_test",
                    input_price_per_million=Decimal(0),
                    output_price_per_million=Decimal(0),
                    currency="USD",
                )
            )
            for service in (manager_service, developer_service, qa_service):
                prefix = (
                    "DEVELOPER_MANAGER"
                    if service is manager_service
                    else ("DEVELOPER_WORKER" if service is developer_service else "QA_WORKER")
                )
                session.add(
                    AgentDefinition(
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        name=getattr(service, f"{prefix}_NAME"),
                        slug=getattr(service, f"{prefix}_SLUG"),
                        version=developer_service.DEVELOPER_WORKER_VERSION
                        if service is developer_service
                        else 1,
                        status="ENABLED",
                        category=getattr(service, f"{prefix}_CATEGORY"),
                        mission=getattr(service, f"{prefix}_MISSION"),
                        capabilities=getattr(service, f"{prefix}_CAPABILITIES"),
                        permissions=developer_service.DEVELOPER_WORKER_PERMISSIONS
                        if service is developer_service
                        else [],
                    )
                )
            await session.commit()

        db_call(enable_local)
        assert (
            client.post(
                launch_url,
                headers=auth,
                json=launch_request | {"confirmation": "YES"},
            ).status_code
            == 422
        )
        original_append = launch_routes.append_record

        async def reject_binding_audit(session, *, data, commit=False):
            if data.action == "launch.workflow.created":
                raise RuntimeError("injected binding audit failure")
            return await original_append(session, data=data, commit=commit)

        monkeypatch.setattr(launch_routes, "append_record", reject_binding_audit)
        assert client.post(launch_url, headers=auth, json=launch_request).status_code == 500
        monkeypatch.setattr(launch_routes, "append_record", original_append)
        assert db_call(no_run) is None

        async def no_binding(session):
            return await session.scalar(
                select(LaunchAuthorization.workflow_run_id).where(
                    LaunchAuthorization.id == UUID(created.json()["id"])
                )
            )

        assert db_call(no_binding) is None
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(launch_url, headers=auth, json=launch_request), range(2)
                )
            )
        assert all(response.status_code == 201 for response in responses), [
            response.text for response in responses
        ]
        assert responses[0].json()["workflow_run_id"] == responses[1].json()["workflow_run_id"]
        launched = responses[0]
        run_id = launched.json()["workflow_run_id"]
        assert launched.json()["workflow_created"] is True
        assert (
            client.post(launch_url, headers=auth, json=launch_request).json()["workflow_run_id"]
            == run_id
        )
        assert (
            client.post(
                launch_url, headers=auth, json=launch_request | {"request_id": str(uuid4())}
            ).status_code
            == 409
        )
        assert (
            client.post(path(scope) + f"/workflow-runs/{run_id}/advance", headers=auth).status_code
            == 409
        )

        async def created_graph(session):
            return (
                await session.scalar(
                    select(WorkflowRun.status).where(WorkflowRun.id == UUID(run_id))
                ),
                await session.scalar(
                    select(WorkflowStepHandoff.id).where(
                        WorkflowStepHandoff.workflow_run_id == UUID(run_id)
                    )
                ),
            )

        status, handoff_id = db_call(created_graph)
        assert status == "CREATED" and handoff_id is not None
        dispatch_url = url + f"/{created.json()['id']}/dispatch"
        dispatch_request = {
            "confirmation": "ENQUEUE_DISPOSABLE_TEST_WORKFLOW",
            "request_id": str(uuid4()),
            "current_password": password,
        }
        assert client.post(dispatch_url, json=dispatch_request).status_code == 401
        assert (
            client.post(
                dispatch_url, headers=auth, json=dispatch_request | {"confirmation": "YES"}
            ).status_code
            == 422
        )
        queued = client.post(dispatch_url, headers=auth, json=dispatch_request)
        assert queued.status_code == 201, queued.text
        assert queued.json()["status"] == "READY"
        assert client.get(
            f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace}/projects/{project['id']}/"
            f"conversations/{conversation}/plans/{plan['id']}/compilations/{compilation['id']}/"
            f"launch-authorizations/{created.json()['id']}/dispatch",
            headers=auth,
        ).status_code in {403, 404}
        repeated = client.post(dispatch_url, headers=auth, json=dispatch_request)
        assert (
            repeated.status_code == 201
            and repeated.json()["dispatch_id"] == queued.json()["dispatch_id"]
        )
        assert (
            client.post(
                dispatch_url, headers=auth, json=dispatch_request | {"request_id": str(uuid4())}
            ).status_code
            == 409
        )

        provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
        provider.provider_id = "local_cadrage"
        for expected in (
            ("DEVELOPER_MANAGER",)
            if mode != "qa_pass"
            else ("DEVELOPER_MANAGER", "DEVELOPER_WORKER", "QA_WORKER")
        ):
            result = db_call(
                lambda session: dispatch_service.run_once(
                    session,
                    registry=ProviderRegistry((provider,)),
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                    owner=uuid4(),
                )
            )
            assert result is not None, expected
        if mode == "qa_pass":
            assert len(provider.calls) == 3
            assert (
                db_call(
                    lambda session: dispatch_service.run_once(
                        session,
                        registry=ProviderRegistry((provider,)),
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        owner=uuid4(),
                    )
                )
                is None
            )

        async def completed(session):
            return (
                await session.scalar(
                    select(WorkflowRun.status).where(WorkflowRun.id == UUID(run_id))
                ),
                await session.scalar(
                    select(TaskDispatch.status).where(
                        TaskDispatch.id == UUID(queued.json()["dispatch_id"])
                    )
                ),
                list(
                    await session.scalars(
                        select(ModelRun.status).where(ModelRun.tenant_id == scope.tenant)
                    )
                ),
            )

        if mode == "qa_pass":
            run_status, dispatch_status, model_statuses = db_call(completed)
            assert run_status == "COMPLETED" and dispatch_status == "DONE"
            assert model_statuses == ["SUCCEEDED"] * 3
            tracked = client.get(dispatch_url, headers=auth)
            assert tracked.status_code == 200 and tracked.json()["qa_verdict"] == "PASS"
            assert [step["status"] for step in tracked.json()["steps"]] == ["COMPLETED"] * 3
            assert (
                client.get(
                    dispatch_url.replace(str(created.json()["id"]), str(uuid4())), headers=auth
                ).status_code
                == 404
            )
        if mode == "cancel_mid":
            cancelled = db_call(
                lambda session: dispatch_service.cancel_dispatch(
                    session,
                    operator=authenticate_operator(operator_key),
                    tenant_id=scope.tenant,
                    workspace_id=scope.workspace,
                    dispatch_id=UUID(queued.json()["dispatch_id"]),
                )
            )
            assert cancelled.status == "CANCELLED"
            assert (
                db_call(
                    lambda session: dispatch_service.run_once(
                        session,
                        registry=ProviderRegistry((provider,)),
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        owner=uuid4(),
                    )
                )
                is None
            )
            assert len(provider.calls) == 1
        revoked = client.post(
            url + f"/{created.json()['id']}/revoke",
            headers=auth,
            json={"current_password": password},
        )
        assert revoked.status_code == 200 and revoked.json()["version"] == 2
        if mode == "revoke_mid":
            with pytest.raises(ApplicationError) as failure:
                db_call(
                    lambda session: dispatch_service.run_once(
                        session,
                        registry=ProviderRegistry((provider,)),
                        tenant_id=scope.tenant,
                        workspace_id=scope.workspace,
                        owner=uuid4(),
                    )
                )
            assert failure.value.code == "launch_execution_unverified"
            run_status, dispatch_status, model_statuses = db_call(completed)
            assert run_status == "RUNNING" and dispatch_status == "BLOCKED"
            assert model_statuses == ["SUCCEEDED"] and len(provider.calls) == 1
        assert client.post(dispatch_url, headers=auth, json=dispatch_request).status_code == 409
        assert client.post(url, headers=auth, json=request).status_code == 409
        document["expected_version"] = 1
        document["summary"] = "Cahier mis à jour"
        assert client.put(specs, headers=auth, json=document).status_code == 200
        assert (
            client.post(url, headers=auth, json=request | {"request_id": str(uuid4())}).status_code
            == 409
        )


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


def test_byok_rotation_and_backup_restore_require_both_key_versions(initialized, monkeypatch):
    scope, password, _ = initialized
    old = base64.b64encode(b"a" * 32).decode()
    new = base64.b64encode(b"b" * 32).decode()
    monkeypatch.setenv("NOVALTON_BYOK_KEYRING", json.dumps({"v1": old}))
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v1")
    secret = "synthetic-rotation-only-no-provider-call"
    with TestClient(create_app()) as client:
        token = client.post(
            "/api/v1/local-auth/login", json={"login": scope.login, "password": password}
        ).json()["token"]
        saved = client.put(
            path(scope) + "/provider-keys/openrouter",
            headers={"Authorization": f"Bearer {token}"},
            json={"secret": secret, "current_password": password},
        )
        assert saved.status_code == 200 and secret not in saved.text

    async def backup(session):
        row = await session.scalar(select(ProviderKey).where(ProviderKey.owner_id == scope.owner))
        assert row is not None
        return row.key_id, row.nonce, row.ciphertext

    old_record = db_call(backup)
    monkeypatch.setenv("NOVALTON_BYOK_KEYRING", json.dumps({"v1": old, "v2": new}))
    monkeypatch.setenv("NOVALTON_BYOK_ACTIVE_KEY_ID", "v2")
    ring = Keyring.from_environment()

    async def rotate(session):
        async with session.begin():
            assert await rotate_records(session, ring) == 1

    db_call(rotate)
    current_record = db_call(backup)
    assert current_record[0] == "v2" and current_record[2] != old_record[2]
    scope_args = dict(
        owner=scope.owner, tenant=scope.tenant, workspace=scope.workspace, provider="openrouter"
    )
    assert ring.decrypt(*current_record, **scope_args) == secret
    assert ring.decrypt(*old_record, **scope_args) == secret
    with pytest.raises(VaultUnavailable):
        ring.decrypt(*current_record, **(scope_args | {"workspace": uuid4()}))
    with pytest.raises(VaultUnavailable):
        Keyring("v1", {"v1": b"a" * 32}).decrypt(*current_record, **scope_args)

    async def restore_backup(session):
        async with session.begin():
            row = await session.scalar(
                select(ProviderKey).where(ProviderKey.owner_id == scope.owner).with_for_update()
            )
            assert row is not None
            row.key_id, row.nonce, row.ciphertext = old_record

    db_call(restore_backup)
    assert db_call(backup) == old_record
    assert ring.decrypt(*db_call(backup), **scope_args) == secret
    with pytest.raises(VaultUnavailable):
        db_call(lambda session: rotate_records(session, Keyring("v2", {"v2": b"b" * 32})))
    assert db_call(backup) == old_record


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
