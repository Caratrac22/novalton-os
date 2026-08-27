import asyncio
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.main import create_app
from novalton_api.modules.memories.models import MemoryProvenance, MemoryRecord
from novalton_api.modules.memories.schemas import MemoryCreate
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workflows.models import WorkflowPlan, WorkflowRun
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    workflow_run_id: UUID


@dataclass(frozen=True)
class ApiContext:
    client: TestClient
    first: Scope
    second: Scope


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "FACT",
        "knowledge_state": "CONFIRMED_FACT",
        "statement": "The workspace uses a bounded memory record.",
        "confidence": 0.75,
        "importance": 3,
        "valid_from": "2026-08-27T10:00:00Z",
        "provenance": [{"source_type": "USER_STATEMENT", "source_reference_id": "s-1"}],
    }
    payload.update(overrides)
    return payload


def _collection(scope: Scope) -> str:
    return f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/memories"


def _memory(scope: Scope, memory_id: str | UUID) -> str:
    return f"{_collection(scope)}/{memory_id}"


def _retrieve(scope: Scope) -> str:
    return f"{_collection(scope)}/retrieve"


async def _seed() -> tuple[Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes: list[Scope] = []
            for marker in ("first", "second"):
                tenant = Tenant(name=f"Memory {marker}", slug=f"memory-{marker}-{uuid4().hex[:8]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(tenant_id=tenant.id, name=marker, slug=marker)
                session.add(workspace)
                await session.flush()
                project = Project(workspace_id=workspace.id, name=marker, slug=marker)
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title=marker)
                session.add(task)
                await session.flush()
                plan = WorkflowPlan(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    project_id=project.id,
                    task_id=task.id,
                    version=1,
                    title=f"{marker} plan",
                )
                session.add(plan)
                await session.flush()
                run = WorkflowRun(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    project_id=project.id,
                    task_id=task.id,
                    workflow_plan_id=plan.id,
                    plan_version=1,
                    status="CREATED",
                )
                session.add(run)
                await session.flush()
                scopes.append(Scope(tenant.id, workspace.id, project.id, task.id, run.id))
            return scopes[0], scopes[1]
    finally:
        await database.dispose()


async def _cleanup(scopes: tuple[Scope, Scope]) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            workspace_ids = [scope.workspace_id for scope in scopes]
            tenant_ids = [scope.tenant_id for scope in scopes]
            await session.execute(
                delete(MemoryProvenance).where(
                    MemoryProvenance.memory_id.in_(
                        select(MemoryRecord.id).where(MemoryRecord.workspace_id.in_(workspace_ids))
                    )
                )
            )
            await session.execute(
                delete(MemoryRecord).where(MemoryRecord.workspace_id.in_(workspace_ids))
            )
            await session.execute(delete(WorkflowRun).where(WorkflowRun.tenant_id.in_(tenant_ids)))
            await session.execute(
                delete(WorkflowPlan).where(WorkflowPlan.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                delete(Task).where(Task.project_id.in_([s.project_id for s in scopes]))
            )
            await session.execute(delete(Project).where(Project.workspace_id.in_(workspace_ids)))
            await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
    finally:
        await database.dispose()


@pytest.fixture
def api() -> Iterator[ApiContext]:
    scopes = asyncio.run(_seed())
    with TestClient(create_app()) as client:
        yield ApiContext(client, *scopes)
    asyncio.run(_cleanup(scopes))


def test_memory_create_fact_and_decision_and_independent_state(api: ApiContext) -> None:
    fact = api.client.post(_collection(api.first), json=_valid_payload())
    decision = api.client.post(
        _collection(api.first),
        json=_valid_payload(
            kind="DECISION", knowledge_state="HYPOTHESIS", statement="Use the memory API."
        ),
    )
    assert fact.status_code == 201
    assert decision.status_code == 201
    assert fact.json()["kind"] == "FACT"
    assert fact.json()["knowledge_state"] == "CONFIRMED_FACT"
    assert decision.json()["kind"] == "DECISION"
    assert decision.json()["knowledge_state"] == "HYPOTHESIS"


def test_memory_get_and_scoped_list(api: ApiContext) -> None:
    created = api.client.post(_collection(api.first), json=_valid_payload()).json()
    assert api.client.get(_memory(api.first, created["id"])).json() == created
    assert [item["id"] for item in api.client.get(_collection(api.first)).json()["items"]] == [
        created["id"]
    ]
    assert api.client.get(_collection(api.second)).json()["items"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "UNKNOWN"),
        ("knowledge_state", "UNKNOWN"),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("importance", 0),
        ("importance", 6),
    ],
)
def test_memory_enum_and_numeric_bounds_rejected(
    api: ApiContext, field: str, value: object
) -> None:
    response = api.client.post(_collection(api.first), json=_valid_payload(**{field: value}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_memory_schema_temporal_and_provenance_rules_are_non_db() -> None:
    valid_from = datetime(2026, 8, 27, 10, tzinfo=UTC)
    MemoryCreate.model_validate(
        _valid_payload(
            valid_from=valid_from,
            valid_to=datetime(2026, 8, 27, 11, tzinfo=UTC),
            confidence=0,
            importance=1,
        )
    )
    MemoryCreate.model_validate(_valid_payload(valid_from=valid_from, confidence=1, importance=5))
    for valid_to in (
        datetime(2026, 8, 27, 10, tzinfo=UTC),
        datetime(2026, 8, 27, 9, tzinfo=UTC),
    ):
        with pytest.raises(ValidationError, match="valid_to must be later"):
            MemoryCreate.model_validate(_valid_payload(valid_from=valid_from, valid_to=valid_to))
    with pytest.raises(ValidationError):
        MemoryCreate.model_validate(_valid_payload(provenance=[]))


def test_memory_provenance_one_and_multiple_rows_round_trip(api: ApiContext) -> None:
    response = api.client.post(
        _collection(api.first),
        json=_valid_payload(
            provenance=[
                {"source_type": "USER_STATEMENT", "source_reference_id": "one"},
                {"source_type": "DOCUMENT", "source_reference_id": "two"},
            ]
        ),
    )
    assert response.status_code == 201
    assert [
        (p["source_type"], p["source_reference_id"]) for p in response.json()["provenance"]
    ] == [
        ("USER_STATEMENT", "one"),
        ("DOCUMENT", "two"),
    ]


def test_memory_link_scope_validation(api: ApiContext) -> None:
    for field, value, extra in (
        ("project_id", api.second.project_id, {}),
        ("task_id", api.second.task_id, {"project_id": str(api.first.project_id)}),
        ("workflow_run_id", api.second.workflow_run_id, {}),
    ):
        response = api.client.post(
            _collection(api.first),
            json=_valid_payload(**{field: str(value), **extra}),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource_not_found"
    mismatch = api.client.post(
        _collection(api.first),
        json=_valid_payload(project_id=str(api.first.project_id), task_id=str(api.second.task_id)),
    )
    assert mismatch.status_code == 404


def test_memory_tenant_workspace_mismatch_and_cross_workspace_get(api: ApiContext) -> None:
    created = api.client.post(_collection(api.first), json=_valid_payload()).json()
    mismatch = api.client.get(
        _memory(api.first, created["id"]).replace(
            str(api.first.tenant_id), str(api.second.tenant_id)
        )
    )
    assert mismatch.status_code == 404
    assert api.client.get(_memory(api.second, created["id"])).status_code == 404
    assert api.client.get(_collection(api.second)).json()["items"] == []


def test_memory_deterministic_pagination_and_order(api: ApiContext) -> None:
    ids = [
        api.client.post(
            _collection(api.first), json=_valid_payload(statement=f"memory {i}")
        ).json()["id"]
        for i in range(3)
    ]
    page = api.client.get(_collection(api.first), params={"limit": 2, "offset": 1}).json()
    repeat = api.client.get(_collection(api.first), params={"limit": 2, "offset": 1}).json()
    assert [item["id"] for item in page["items"]] == ids[1:]
    assert [item["id"] for item in repeat["items"]] == ids[1:]


def test_memory_historical_states_are_retrievable_without_provider(api: ApiContext) -> None:
    response = api.client.post(
        _collection(api.first),
        json=_valid_payload(kind="NOTE", knowledge_state="OBSOLETE", lifecycle="ARCHIVED"),
    )
    assert response.status_code == 201
    body = response.json()
    retrieved = api.client.get(_memory(api.first, body["id"]))
    assert retrieved.status_code == 200
    assert retrieved.json()["knowledge_state"] == "OBSOLETE"
    assert retrieved.json()["lifecycle"] == "ARCHIVED"


def test_memory_source_reference_bounds_and_statement_not_logged(
    api: ApiContext, caplog: pytest.LogCaptureFixture
) -> None:
    for value in ("", "x" * 257):
        assert (
            api.client.post(
                _collection(api.first),
                json=_valid_payload(
                    provenance=[{"source_type": "DOCUMENT", "source_reference_id": value}]
                ),
            ).status_code
            == 422
        )
    statement = "private memory statement that must not enter logs"
    with caplog.at_level(logging.INFO, logger="novalton_api.modules.memories.service"):
        response = api.client.post(_collection(api.first), json=_valid_payload(statement=statement))
    assert response.status_code == 201
    assert statement not in caplog.text


def test_memory_temporal_values_accept_timezone_and_reject_naive() -> None:
    payload = _valid_payload(valid_from=datetime.now(UTC))
    MemoryCreate.model_validate(payload)
    with pytest.raises(ValidationError, match="timezone"):
        MemoryCreate.model_validate(_valid_payload(valid_from=datetime(2026, 8, 27, 10)))


def test_memory_retrieval_is_separate_from_inventory_listing(api: ApiContext) -> None:
    created = api.client.post(
        _collection(api.first),
        json=_valid_payload(statement="retrieval context", lifecycle="ARCHIVED"),
    ).json()

    listed = api.client.get(_collection(api.first))
    retrieved = api.client.post(_retrieve(api.first), json={"as_of": "2026-08-27T12:00:00Z"})

    assert [item["id"] for item in listed.json()["items"]] == [created["id"]]
    assert retrieved.status_code == 200
    assert retrieved.json()["items"] == []


def test_memory_retrieval_captures_one_current_utc_timestamp(api: ApiContext) -> None:
    valid_from = datetime.now(UTC) - timedelta(seconds=1)
    created = api.client.post(
        _collection(api.first),
        json=_valid_payload(valid_from=valid_from.isoformat()),
    ).json()

    response = api.client.post(_retrieve(api.first), json={})

    assert response.status_code == 200
    assert response.json()["as_of"].endswith("Z")
    assert [item["id"] for item in response.json()["items"]] == [created["id"]]


def test_memory_retrieval_scope_and_link_filters_do_not_leak(api: ApiContext) -> None:
    own = api.client.post(
        _collection(api.first),
        json=_valid_payload(
            statement="first scope retrieval",
            project_id=str(api.first.project_id),
            task_id=str(api.first.task_id),
            workflow_run_id=str(api.first.workflow_run_id),
        ),
    ).json()
    api.client.post(
        _collection(api.second), json=_valid_payload(statement="second scope retrieval")
    )
    as_of = "2026-08-27T12:00:00Z"

    response = api.client.post(
        _retrieve(api.first),
        json={
            "as_of": as_of,
            "project_id": str(api.first.project_id),
            "task_id": str(api.first.task_id),
            "workflow_run_id": str(api.first.workflow_run_id),
        },
    )
    foreign_filter = api.client.post(
        _retrieve(api.first), json={"as_of": as_of, "project_id": str(api.second.project_id)}
    )
    tenant_mismatch = api.client.post(
        _retrieve(api.first).replace(str(api.first.tenant_id), str(api.second.tenant_id)),
        json={"as_of": as_of},
    )

    assert [item["id"] for item in response.json()["items"]] == [own["id"]]
    assert foreign_filter.json()["items"] == []
    assert tenant_mismatch.status_code == 404


def test_memory_retrieval_temporal_and_admissibility_defaults(api: ApiContext) -> None:
    payloads = [
        _valid_payload(statement="valid confirmed", importance=2),
        _valid_payload(statement="future confirmed", valid_from="2026-08-28T10:00:00Z"),
        _valid_payload(
            statement="expired confirmed", valid_to="2026-08-27T11:00:00Z", importance=5
        ),
        _valid_payload(statement="obsolete", knowledge_state="OBSOLETE", importance=5),
        _valid_payload(statement="hypothesis", knowledge_state="HYPOTHESIS", importance=4),
        _valid_payload(statement="inference", knowledge_state="INFERENCE", importance=3),
    ]
    for payload in payloads:
        assert api.client.post(_collection(api.first), json=payload).status_code == 201

    default = api.client.post(_retrieve(api.first), json={"as_of": "2026-08-27T11:00:00Z"})
    historical = api.client.post(
        _retrieve(api.first),
        json={
            "as_of": "2026-08-27T11:00:00Z",
            "knowledge_states": ["OBSOLETE"],
        },
    )
    boundary = api.client.post(_retrieve(api.first), json={"as_of": "2026-08-27T11:00:00Z"})

    assert [item["statement"] for item in default.json()["items"]] == [
        "hypothesis",
        "inference",
        "valid confirmed",
    ]
    assert historical.json()["items"][0]["statement"] == "obsolete"
    assert all(item["statement"] != "expired confirmed" for item in boundary.json()["items"])
    assert {item["knowledge_state"] for item in default.json()["items"]} >= {
        "HYPOTHESIS",
        "INFERENCE",
    }


def test_memory_retrieval_thresholds_ordering_and_contract(api: ApiContext) -> None:
    low = api.client.post(
        _collection(api.first),
        json=_valid_payload(statement="low value", confidence=0.4, importance=2),
    ).json()
    high = api.client.post(
        _collection(api.first),
        json=_valid_payload(statement="high value", confidence=0.9, importance=5),
    ).json()
    response = api.client.post(
        _retrieve(api.first),
        json={"as_of": "2026-08-27T12:00:00Z", "min_confidence": 0.8, "min_importance": 4},
    )

    assert [item["id"] for item in response.json()["items"]] == [high["id"]]
    item = response.json()["items"][0]
    assert item["provenance"] == high["provenance"]
    assert item["knowledge_state"] == "CONFIRMED_FACT"
    assert item["lexical_relevance"] is None
    assert low["id"] not in [entry["id"] for entry in response.json()["items"]]


def test_memory_retrieval_lexical_search_is_safe_and_deterministic(api: ApiContext) -> None:
    first = api.client.post(
        _collection(api.first),
        json=_valid_payload(statement="Paris budget décision", importance=3),
    ).json()
    second = api.client.post(
        _collection(api.first),
        json=_valid_payload(statement="Paris budget approval", importance=5),
    ).json()
    api.client.post(
        _collection(api.first), json=_valid_payload(statement="unrelated roadmap", importance=5)
    )
    body = {"as_of": "2026-08-27T12:00:00Z", "query": "Paris budget"}
    response = api.client.post(_retrieve(api.first), json=body)
    repeated = api.client.post(_retrieve(api.first), json=body)
    punctuation = api.client.post(
        _retrieve(api.first), json={"as_of": body["as_of"], "query": "Paris & !budget"}
    )
    multilingual = api.client.post(
        _retrieve(api.first), json={"as_of": body["as_of"], "query": "décision"}
    )

    assert [item["id"] for item in response.json()["items"]] == [second["id"], first["id"]]
    assert [item["id"] for item in repeated.json()["items"]] == [second["id"], first["id"]]
    assert all(item["lexical_relevance"] is not None for item in response.json()["items"])
    assert punctuation.status_code == 200
    assert multilingual.json()["items"][0]["id"] == first["id"]


def test_memory_retrieval_validation_and_safe_logs(
    api: ApiContext, caplog: pytest.LogCaptureFixture
) -> None:
    query = "private retrieval query"
    statement = "private retrieval statement"
    api.client.post(_collection(api.first), json=_valid_payload(statement=statement))
    with caplog.at_level(logging.INFO, logger="novalton_api.modules.memories.service"):
        response = api.client.post(
            _retrieve(api.first), json={"as_of": "2026-08-27T12:00:00Z", "query": query}
        )

    assert response.status_code == 200
    assert query not in caplog.text
    assert statement not in caplog.text
    assert api.client.post(_retrieve(api.first), json={"limit": 51}).status_code == 422
    assert (
        api.client.post(_retrieve(api.first), json={"as_of": "2026-08-27T12:00:00"}).status_code
        == 422
    )
