"""DB-backed I-042 service tests using disposable Dulwich repositories."""

import asyncio
import hashlib
import sys
from pathlib import Path
from uuid import UUID

import pytest
from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit, Tree
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.approvals import service as approvals_service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.git_changesets import local, service
from novalton_api.modules.git_changesets.models import GitCommitAction
from novalton_api.modules.git_changesets.schemas import GitCommitPrepare
from novalton_api.modules.policy.schemas import PolicyEffect, PolicyRuleCreate
from novalton_api.modules.tools.executor import ToolExecutionError
from novalton_api.modules.tools.models import ToolCall

sys.path.insert(0, str(Path(__file__).parent))

import test_development_workflow as workflow_tests  # noqa: E402
import test_git_changesets_local as local_tests  # noqa: E402


def _repository(tmp_path: Path) -> tuple[local.WorkspaceRoot, local.Repo, bytes]:
    return local_tests._repository(tmp_path)


async def _add_mutation_policy(scope: workflow_tests.Scope) -> None:
    database = Database.from_settings(Settings.from_environment())
    try:
        async with database.session_factory() as session:
            from novalton_api.modules.policy import service as policy_service

            await policy_service.create_rule(
                session,
                data=PolicyRuleCreate(
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    name="Confirm fixture mutation",
                    action_pattern="tool.workspace.replace_text",
                    effect=PolicyEffect.REQUIRE_CONFIRMATION,
                    actor_type="agent",
                    resource_type="task",
                ),
            )
    finally:
        await database.dispose()


@pytest.fixture
def i042_scope() -> workflow_tests.Scope:
    value = asyncio.run(workflow_tests._seed())
    yield value

    async def remove_actions() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory.begin() as session:
                await session.execute(
                    delete(GitCommitAction).where(GitCommitAction.tenant_id == value.tenant_id)
                )
        finally:
            await database.dispose()

    asyncio.run(remove_actions())
    asyncio.run(workflow_tests._cleanup(value))


def _complete_workflow(
    scope: workflow_tests.Scope, target: Path
) -> tuple[UUID, workflow_tests.QueueProvider]:
    provider = workflow_tests.QueueProvider(
        [
            workflow_tests._manager(),
            workflow_tests._worker()
            | {
                "status": "PARTIAL",
                "tool_proposals": [
                    {
                        "call_key": "replace_fixture",
                        "tool_name": "workspace.replace_text",
                        "arguments": {
                            "path": "fixture.txt",
                            "search": "before",
                            "replacement": "after",
                            "expected_matches": 1,
                        },
                    }
                ],
            },
            workflow_tests._worker(),
            workflow_tests._qa("PASS"),
        ]
    )
    body, advance = workflow_tests._create_vertical(scope, provider)
    workflow_tests._advance_fresh(provider, advance)
    waiting = workflow_tests._advance_fresh(provider, advance)
    assert waiting["outcome"] == "WAITING_FOR_HUMAN"

    async def approval_id() -> UUID:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                approval = await session.scalar(
                    select(ApprovalRequest).where(
                        ApprovalRequest.tenant_id == scope.tenant_id,
                        ApprovalRequest.status == "PENDING",
                    )
                )
                assert approval is not None
                return approval.id
        finally:
            await database.dispose()

    approval = asyncio.run(approval_id())
    approval_url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/approvals/{approval}/approve"
    )
    with TestClient(
        create_app(provider_registry=workflow_tests.ProviderRegistry((provider,)))
    ) as client:
        response = client.post(approval_url)
        assert response.status_code == 200, response.text
    final = workflow_tests._advance_fresh(provider, advance)
    assert final["workflow_status"] == "COMPLETED"
    assert target.read_text(encoding="utf-8") == "after\n"
    # The existing mutation fixture writes through a restrictive temporary file.
    # Restore the repository's tracked regular-file mode before testing I-042.
    target.chmod(0o644)
    return UUID(str(body["workflow_run"]["id"])), provider


def test_prepare_and_apply_persist_one_exact_authorized_changeset(
    i042_scope: workflow_tests.Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, repo, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("dirty and staged\n", encoding="utf-8")
    unrelated_blob = Blob.from_string(unrelated.read_bytes())
    repo.object_store.add_object(unrelated_blob)
    index = Index(repo.index_path())
    stat = unrelated.stat()
    index[b"unrelated.txt"] = IndexEntry(
        (int(stat.st_ctime), 0),
        (int(stat.st_mtime), 0),
        stat.st_dev,
        stat.st_ino,
        0o100644,
        stat.st_uid,
        stat.st_gid,
        stat.st_size,
        unrelated_blob.id,
    )
    index.write()
    unrelated_index_entry = Index(repo.index_path())[b"unrelated.txt"]
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(root.path))
    get_settings.cache_clear()
    try:
        asyncio.run(_add_mutation_policy(i042_scope))
        run_id, provider = _complete_workflow(i042_scope, target)

        async def prepare_action() -> GitCommitAction:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    run = await session.get(workflow_tests.WorkflowRun, run_id)
                    assert run is not None
                    _, candidates = await service._mutations(session, run)
                    try:
                        local.prepare(root, candidates)
                    except ToolExecutionError as error:
                        pytest.fail(f"local adapter rejected valid fixture: {error.code}")
                    action = await service.prepare(
                        session,
                        tenant_id=i042_scope.tenant_id,
                        workspace_id=i042_scope.workspace_id,
                        workflow_run_id=run_id,
                        data=GitCommitPrepare(commit_message="feat: exact fixture"),
                    )
                    return action
            finally:
                await database.dispose()

        action = asyncio.run(prepare_action())
        assert action.status == "PENDING_APPROVAL"
        assert action.workflow_run_id == run_id
        assert action.project_id == i042_scope.project_id
        assert action.task_id == i042_scope.task_id
        assert action.branch_ref == "refs/heads/master"
        assert action.prepared_head_sha == repo.head().decode()
        assert len(action.source_tool_call_ids) == 1
        assert [item["path"] for item in action.prepared_paths] == ["fixture.txt"]
        assert action.policy_effect == "REQUIRE_CONFIRMATION"
        assert action.approval_request_id is not None
        assert len(action.action_fingerprint) == 64
        assert len(action.expected_commit_sha) == 40
        assert action.preview["diff_truncated"] is False
        assert action.preview["path_count"] == 1
        assert repo.head() == action.prepared_head_sha.encode()
        assert target.read_text(encoding="utf-8") == "after\n"
        assert Index(repo.index_path())[b"unrelated.txt"] == unrelated_index_entry

        async def persisted_state() -> tuple[
            GitCommitAction, list[ApprovalRequest], list[ToolCall]
        ]:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    stored = await session.get(GitCommitAction, action.id)
                    approvals = list(
                        await session.scalars(
                            select(ApprovalRequest).where(
                                ApprovalRequest.tenant_id == i042_scope.tenant_id,
                                ApprovalRequest.action == "git.commit_changeset",
                            )
                        )
                    )
                    calls = list(
                        await session.scalars(
                            select(ToolCall).where(ToolCall.id.in_(action.source_tool_call_ids))
                        )
                    )
                    assert stored is not None
                    return stored, approvals, calls
            finally:
                await database.dispose()

        stored, approvals, calls = asyncio.run(persisted_state())
        assert stored.action_fingerprint == action.action_fingerprint
        assert len(approvals) == 1
        assert approvals[0].status == "PENDING"
        assert approvals[0].mutation_fingerprint == action.action_fingerprint
        assert len(calls) == 1 and calls[0].status == "SUCCEEDED"
        assert "provider" not in str(stored.preview).lower()
        assert "credential" not in str(stored.preview).lower()
        assert "reasoning" not in str(stored.preview).lower()
        assert "dirty and staged" not in str(stored.preview)

        called_resume = False

        async def forbidden_resume(*_args: object, **_kwargs: object) -> None:
            nonlocal called_resume
            called_resume = True
            raise AssertionError("Git approval routed to I-041 resume")

        monkeypatch.setattr(
            "novalton_api.modules.approvals.mutation_resume.approve_and_resume", forbidden_resume
        )
        with TestClient(
            create_app(provider_registry=workflow_tests.ProviderRegistry((provider,)))
        ) as client:
            response = client.post(
                f"/api/v1/tenants/{i042_scope.tenant_id}/workspaces/{i042_scope.workspace_id}"
                f"/approvals/{action.approval_request_id}/approve"
            )
            assert response.status_code == 200, response.text
        assert called_resume is False
        assert repo.head() == action.expected_commit_sha.encode()
        commit = repo.object_store[repo.head()]
        assert isinstance(commit, Commit)
        tree = repo.object_store[commit.tree]
        assert isinstance(tree, Tree)
        assert b"fixture.txt" in tree
        assert b"unrelated.txt" not in tree
        assert unrelated.read_text(encoding="utf-8") == "dirty and staged\n"
        assert Index(repo.index_path())[b"unrelated.txt"] == unrelated_index_entry

        async def final_state() -> tuple[GitCommitAction, list[AuditRecord]]:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    stored = await session.get(GitCommitAction, action.id)
                    audits = list(
                        await session.scalars(
                            select(AuditRecord).where(
                                AuditRecord.resource_id == i042_scope.task_id,
                                AuditRecord.action == "git.commit_changeset",
                            )
                        )
                    )
                    assert stored is not None
                    return stored, audits
            finally:
                await database.dispose()

        applied, audits = asyncio.run(final_state())
        assert applied.status == "APPLIED"
        assert applied.resulting_commit_sha == action.expected_commit_sha
        assert len(audits) >= 2
        assert all("dirty and staged" not in str(item.metadata) for item in audits)
        assert all("credential" not in str(item.metadata).lower() for item in audits)

        with TestClient(
            create_app(provider_registry=workflow_tests.ProviderRegistry((provider,)))
        ) as client:
            replay = client.post(
                f"/api/v1/tenants/{i042_scope.tenant_id}/workspaces/{i042_scope.workspace_id}"
                f"/approvals/{action.approval_request_id}/approve"
            )
            assert replay.status_code == 200
        assert repo.head() == action.expected_commit_sha.encode()
    finally:
        get_settings.cache_clear()


def test_mutation_chain_and_scope_are_authoritative(
    i042_scope: workflow_tests.Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _repository(tmp_path)
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(root.path))
    get_settings.cache_clear()
    try:
        asyncio.run(_add_mutation_policy(i042_scope))
        run_id, _ = _complete_workflow(i042_scope, tmp_path / "fixture.txt")

        async def inspect() -> None:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    run = await session.get(workflow_tests.WorkflowRun, run_id)
                    assert run is not None
                    source_ids, candidates = await service._mutations(session, run)
                    assert len(source_ids) == 1
                    assert candidates == [
                        {
                            "path": "fixture.txt",
                            "preimage_sha256": hashlib.sha256(b"before\n").hexdigest(),
                            "candidate_sha256": hashlib.sha256(b"after\n").hexdigest(),
                        }
                    ]
                    call = await session.get(ToolCall, UUID(source_ids[0]))
                    assert call is not None
                    call.candidate_sha256 = "0" * 64
                    with pytest.raises(ApplicationError) as error:
                        await service.prepare(
                            session,
                            tenant_id=i042_scope.tenant_id,
                            workspace_id=i042_scope.workspace_id,
                            workflow_run_id=run_id,
                            data=GitCommitPrepare(commit_message="should fail"),
                        )
                    assert error.value.code == "git_stale_worktree"
            finally:
                await database.dispose()

        asyncio.run(inspect())
    finally:
        get_settings.cache_clear()


def _prepare_pending_action(
    scope: workflow_tests.Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[local.WorkspaceRoot, local.Repo, Path, GitCommitAction]:
    root, repo, _ = _repository(tmp_path)
    target = tmp_path / "fixture.txt"
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(root.path))
    get_settings.cache_clear()
    asyncio.run(_add_mutation_policy(scope))
    run_id, _ = _complete_workflow(scope, target)

    async def prepare_action() -> GitCommitAction:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                return await service.prepare(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    workflow_run_id=run_id,
                    data=GitCommitPrepare(commit_message="feat: stale-state fixture"),
                )
        finally:
            await database.dispose()

    return root, repo, target, asyncio.run(prepare_action())


@pytest.mark.parametrize("stale_state", ["head", "worktree", "index", "source"])
def test_apply_fails_closed_for_each_independent_stale_state(
    i042_scope: workflow_tests.Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_state: str,
) -> None:
    root, repo, target, action = _prepare_pending_action(i042_scope, tmp_path, monkeypatch)
    if stale_state == "head":
        old_head = repo.head()
        alternate = Commit()
        alternate.tree = repo[old_head].tree
        alternate.parents = [old_head]
        alternate.author = b"external <external@local.invalid>"
        alternate.committer = alternate.author
        alternate.message = b"external"
        alternate.author_time = alternate.commit_time = 1
        alternate.author_timezone = alternate.commit_timezone = 0
        repo.object_store.add_object(alternate)
        assert repo.refs.set_if_equals(b"refs/heads/master", old_head, alternate.id)
    elif stale_state == "worktree":
        target.write_text("tampered\n", encoding="utf-8")
    elif stale_state == "index":
        index = Index(repo.index_path())
        blob = Blob.from_string(b"staged elsewhere\n")
        repo.object_store.add_object(blob)
        entry = index[b"fixture.txt"]
        index[b"fixture.txt"] = IndexEntry(
            entry.ctime,
            entry.mtime,
            entry.dev,
            entry.ino,
            entry.mode,
            entry.uid,
            entry.gid,
            entry.size,
            blob.id,
            entry.flags,
            entry.extended_flags,
        )
        index.write()
    else:

        async def corrupt_source() -> None:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory.begin() as session:
                    call = await session.get(ToolCall, UUID(action.source_tool_call_ids[0]))
                    assert call is not None
                    call.candidate_sha256 = "0" * 64
            finally:
                await database.dispose()

        asyncio.run(corrupt_source())

    async def approve_and_apply() -> ApplicationError:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await approvals_service.approve(
                    session,
                    tenant_id=i042_scope.tenant_id,
                    workspace_id=i042_scope.workspace_id,
                    approval_id=action.approval_request_id,
                )
                with pytest.raises(ApplicationError) as error:
                    await service.approve_and_apply(
                        session,
                        tenant_id=i042_scope.tenant_id,
                        workspace_id=i042_scope.workspace_id,
                        approval_id=action.approval_request_id,
                    )
                return error.value
        finally:
            await database.dispose()

    error = asyncio.run(approve_and_apply())
    assert (
        error.code
        == {
            "head": "git_stale_head",
            "worktree": "git_stale_worktree",
            "index": "git_stale_index",
            "source": "git_stale_changeset",
        }[stale_state]
    )
    assert repo.head() != action.expected_commit_sha.encode()
