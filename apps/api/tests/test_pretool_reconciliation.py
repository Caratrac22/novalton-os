"""Initial AgentRun crash recovery without replaying model or tool activity."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from novalton_api.core import database  # noqa: F401
from novalton_api.modules.approvals import mutation_resume


@pytest.mark.parametrize(
    "case",
    [
        "stale",
        "young",
        "late_tool",
        "completed_agent",
        "agent_changed",
        "step_changed",
        "created",
        "created_started",
    ],
)
def test_initial_agent_reconciliation_is_terminal_and_race_safe(monkeypatch, case):
    now = datetime.now(UTC)
    tenant_id, workspace_id, run_id, agent_id, step_id = (uuid4() for _ in range(5))
    agent = SimpleNamespace(
        id=agent_id,
        status="RUNNING",
        started_at=now - timedelta(hours=2),
        created_at=now - timedelta(hours=2),
    )
    step = SimpleNamespace(id=step_id, agent_run_id=agent_id, status="RUNNING")
    if case == "young":
        agent.started_at = now - timedelta(minutes=5)
    if case == "completed_agent":
        agent.status = "SUCCEEDED"
    if case in {"created", "created_started"}:
        agent.status, agent.started_at = "CREATED", None
    fresh_agent = SimpleNamespace(**vars(agent))
    fresh_step = SimpleNamespace(**vars(step))
    if case == "agent_changed":
        fresh_agent.status = "WAITING_FOR_APPROVAL"
    if case == "created_started":
        fresh_agent.status, fresh_agent.started_at = "RUNNING", now
    if case == "step_changed":
        fresh_step.status = "WAITING_FOR_APPROVAL"
    tool = SimpleNamespace(id=uuid4(), status="RUNNING", result_metadata={})
    calls = [tool] if case == "late_tool" else []
    # The pre-claim read observes no tool. Under AgentRun row lock, a
    # competing provider can still have committed a new ToolCall.
    results = iter([[step], [], calls, []])
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=lambda *_: next(results)),
        scalar=AsyncMock(side_effect=[agent, fresh_agent, fresh_step]),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    transitions = []

    async def changed(*args, **kwargs):
        transitions.append(kwargs)
        return object()

    monkeypatch.setattr(mutation_resume.agent_repository, "transition_run", changed)
    monkeypatch.setattr(mutation_resume.workflow_repository, "transition_step_run", changed)
    monkeypatch.setattr(mutation_resume.workflow_repository, "transition_run", changed)
    result = asyncio.run(
        mutation_resume.reconcile_stale_continuation(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_run_id=run_id,
            now=now,
        )
    )
    expected = case in {"stale", "created"}
    assert result is expected
    assert session.commit.await_count == int(expected)
    assert len(transitions) == (3 if expected else 0)
    if case == "created":
        assert transitions[0]["values"]["status"] == "CANCELLED"
        assert transitions[0]["values"]["failure_code"] is None
        assert all(
            t["values"]["failure_code"] == "tool_continuation_interrupted" for t in transitions[1:]
        )
    elif expected:
        assert all(
            t["values"]["failure_code"] == "tool_continuation_interrupted" for t in transitions
        )
