"""Focused DB-backed I-043 publication persistence and authority tests.

These tests create uniquely owned rows and remove only rows belonging to their own tenant.  They
never assume that the canonical test database is globally empty.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.approvals import routes as approval_routes
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.git_changesets.models import GitCommitAction
from novalton_api.modules.github_publications import config as github_config
from novalton_api.modules.github_publications import service
from novalton_api.modules.github_publications.adapter import (
    RemoteCommit,
    RemotePullRequest,
    RemoteRef,
    RemoteTree,
)
from novalton_api.modules.github_publications.config import GitHubBinding
from novalton_api.modules.github_publications.models import GitHubPublicationAction
from novalton_api.modules.github_publications.schemas import GitHubPublicationCreate
from novalton_api.modules.policy.schemas import PolicyEffect
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workflows.models import WorkflowPlan, WorkflowRun
from novalton_api.modules.workspaces.models import Workspace

IDENTITY = "Novalton OS <novalton@local.invalid>"
STAMP = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
PARENT = "1" * 40
TREE = "2" * 40
COMMIT = "3" * 40
PARENT_TREE = "4" * 40
SECRET = "NOVALTON_SUPER_SECRET_TEST_TOKEN_9431"


def make_test_github_binding() -> GitHubBinding:
    return GitHubBinding(
        provider="github",
        api_base="https://api.github.com",
        owner="owner",
        repository="repo",
        base_branch="main",
        version="v1",
        key="key",
        workspace_root="/workspace",
    )


@pytest.fixture
def publication_scope():
    ids = {}

    async def seed() -> dict[str, UUID]:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory.begin() as session:
                tenant_id = uuid4()
                workspace_id = uuid4()
                project_id = uuid4()
                task_id = uuid4()
                foreign_project_id = uuid4()
                foreign_task_id = uuid4()
                plan_id = uuid4()
                run_id = uuid4()
                git_action_id = uuid4()
                tenant = Tenant(id=tenant_id, name="I043 publication", slug=f"i043-{uuid4().hex}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(
                    id=workspace_id,
                    tenant_id=tenant_id,
                    name="I043 workspace",
                    slug=f"i043-{uuid4().hex}",
                )
                session.add(workspace)
                await session.flush()
                project = Project(
                    id=project_id,
                    workspace_id=workspace_id,
                    name="I043 project",
                    slug=f"i043-{uuid4().hex}",
                )
                task = Task(id=task_id, project_id=project_id, title="I043 task")
                foreign_project = Project(
                    id=foreign_project_id,
                    workspace_id=workspace_id,
                    name="I043 foreign project",
                    slug=f"i043-{uuid4().hex}",
                )
                foreign_task = Task(
                    id=foreign_task_id, project_id=foreign_project_id, title="I043 foreign task"
                )
                session.add_all([project, task, foreign_project, foreign_task])
                await session.flush()
                plan = WorkflowPlan(
                    id=plan_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=task_id,
                    version=1,
                    title="I043 plan",
                )
                session.add(plan)
                await session.flush()
                run = WorkflowRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=task_id,
                    workflow_plan_id=plan_id,
                    plan_version=1,
                    status="COMPLETED",
                    started_at=STAMP,
                    completed_at=STAMP,
                )
                session.add(run)
                await session.flush()
                action = GitCommitAction(
                    id=git_action_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=task_id,
                    workflow_run_id=run_id,
                    repository_key=hashlib.sha256(b"/workspace").hexdigest(),
                    branch_ref="refs/heads/main",
                    prepared_head_sha=PARENT,
                    index_fingerprint="4" * 64,
                    source_tool_call_ids=[],
                    prepared_paths=[
                        {
                            "path": "fixture.txt",
                            "preimage_sha256": "5" * 64,
                            "candidate_sha256": "6" * 64,
                            "mode": 0o100644,
                            "head_blob_id": "7" * 40,
                            "candidate_blob_id": "8" * 40,
                        }
                    ],
                    preview={"path_count": 1},
                    commit_message="feat: exact",
                    author_identity=IDENTITY,
                    committer_identity=IDENTITY,
                    commit_timestamp=STAMP,
                    action_fingerprint="9" * 64,
                    policy_effect="REQUIRE_CONFIRMATION",
                    expected_commit_sha=COMMIT,
                    status="APPLIED",
                    resulting_commit_sha=COMMIT,
                )
                session.add(action)
                await session.flush()
                ids.update(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    task_id=task_id,
                    workflow_run_id=run_id,
                    git_action_id=git_action_id,
                    workflow_plan_id=plan_id,
                    foreign_project_id=foreign_project_id,
                    foreign_task_id=foreign_task_id,
                )
                return ids
        finally:
            await database.dispose()

    ids = asyncio.run(seed())
    yield ids

    async def cleanup() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory.begin() as session:
                await session.execute(
                    delete(GitHubPublicationAction).where(
                        GitHubPublicationAction.tenant_id == ids["tenant_id"]
                    )
                )
                await session.execute(
                    delete(AuditRecord).where(AuditRecord.tenant_id == ids["tenant_id"])
                )
                await session.execute(
                    delete(ApprovalRequest).where(ApprovalRequest.tenant_id == ids["tenant_id"])
                )
                await session.execute(
                    delete(GitCommitAction).where(GitCommitAction.tenant_id == ids["tenant_id"])
                )
                await session.execute(
                    delete(WorkflowRun).where(WorkflowRun.tenant_id == ids["tenant_id"])
                )
                await session.execute(
                    delete(WorkflowPlan).where(WorkflowPlan.tenant_id == ids["tenant_id"])
                )
                await session.execute(
                    delete(Task).where(
                        Task.project_id.in_([ids["project_id"], ids["foreign_project_id"]])
                    )
                )
                await session.execute(
                    delete(Project).where(Project.workspace_id == ids["workspace_id"])
                )
                await session.execute(
                    delete(Workspace).where(Workspace.tenant_id == ids["tenant_id"])
                )
                await session.execute(delete(Tenant).where(Tenant.id == ids["tenant_id"]))
        finally:
            await database.dispose()

    asyncio.run(cleanup())


def _patch_service(
    monkeypatch: pytest.MonkeyPatch,
    ids: dict[str, UUID],
    effect: PolicyEffect = PolicyEffect.REQUIRE_CONFIRMATION,
) -> None:
    commit = SimpleNamespace(
        id=ids["git_action_id"],
        status="APPLIED",
        resulting_commit_sha=COMMIT,
        repository_key=hashlib.sha256(b"/workspace").hexdigest(),
        branch_ref="refs/heads/main",
        prepared_head_sha=PARENT,
        project_id=ids["project_id"],
        task_id=ids["task_id"],
        workflow_run_id=ids["workflow_run_id"],
        commit_message="feat: exact",
        author_identity=IDENTITY,
        committer_identity=IDENTITY,
        commit_timestamp=STAMP,
        prepared_paths=[],
    )
    monkeypatch.setattr(service.git_repository, "get_scoped", lambda *a, **k: _value(commit))
    monkeypatch.setattr(
        service,
        "trusted_binding",
        make_test_github_binding,
    )
    monkeypatch.setattr(service, "_root", lambda: SimpleNamespace())
    monkeypatch.setattr(
        service.local,
        "read_publication_objects",
        lambda *a, **k: ({"tree_sha": TREE, "changes": []}, []),
    )
    monkeypatch.setattr(
        service.policy_service,
        "evaluate",
        lambda *a, **k: _value(SimpleNamespace(effect=effect, matched_rule_ids=[], reasons=[])),
    )


async def _value(value):
    return value


def test_prepare_persists_scoped_publication_and_safe_binding(
    publication_scope, monkeypatch
) -> None:
    ids = publication_scope
    _patch_service(monkeypatch, ids)

    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action = await service.prepare(
                    session,
                    tenant_id=ids["tenant_id"],
                    workspace_id=ids["workspace_id"],
                    git_commit_action_id=ids["git_action_id"],
                    data=GitHubPublicationCreate(title="Title", body="Complete body"),
                    adapter=FakeGitHub(),
                )
                assert action.status == "PENDING_APPROVAL"
                assert action.repository_identity == {
                    "provider": "github",
                    "api_base": "https://api.github.com",
                    "owner": "owner",
                    "repository": "repo",
                    "binding_key": "key",
                }
                assert action.base_branch == "main" and action.local_commit_sha == COMMIT
                assert action.branch_ref == f"novalton/{ids['git_action_id']}"
                approval = await session.get(ApprovalRequest, action.approval_request_id)
                assert approval is not None
                assert approval.requester_actor_id == f"github-publication:{action.id}"
                assert approval.resource_id == ids["task_id"]
                assert approval.project_id == ids["project_id"]
                assert approval.task_id == ids["task_id"]
                await session.commit()
                stored = await session.get(GitHubPublicationAction, action.id)
                assert stored is not None and stored.pr_body == "Complete body"
                assert (
                    "token" not in str(stored).casefold()
                    and "authorization" not in str(stored).casefold()
                )
        finally:
            await database.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "effect", [PolicyEffect.ALLOW, PolicyEffect.ALLOW_WITH_LOG, PolicyEffect.BLOCK]
)
def test_prepare_rejects_non_confirmation_policy(
    publication_scope, monkeypatch, effect: PolicyEffect
) -> None:
    _patch_service(monkeypatch, publication_scope, effect)
    with pytest.raises(ApplicationError) as error:

        async def run():
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    await service.prepare(
                        session,
                        tenant_id=publication_scope["tenant_id"],
                        workspace_id=publication_scope["workspace_id"],
                        git_commit_action_id=publication_scope["git_action_id"],
                        data=GitHubPublicationCreate(title="Title"),
                        adapter=FakeGitHub(),
                    )
            finally:
                await database.dispose()

        asyncio.run(run())
    assert error.value.code == "publication_policy_rejected"


def test_publication_model_has_only_scoped_unique_ownership_constraints() -> None:
    names = {constraint.name for constraint in GitHubPublicationAction.__table__.constraints}
    assert {
        "uq_github_publication_git_action",
        "uq_github_publication_approval",
        "ck_github_publication_policy",
    } <= names


class FakeGitHub:
    """Closed-world adapter used only by these tests; it has no HTTP implementation."""

    def __init__(
        self,
        *,
        base_sha: str = PARENT,
        parent_tree_sha: str = PARENT_TREE,
        new_commit_sha: str = COMMIT,
        new_tree_sha: str = TREE,
        branch_sha: str | None = None,
        pr: RemotePullRequest | None = None,
    ):
        self.base_sha = base_sha
        self.parent_tree_sha = parent_tree_sha
        self.new_commit_sha = new_commit_sha
        self.new_tree_sha = new_tree_sha
        self.branch_sha = branch_sha
        self.pr = pr
        self.calls: list[str] = []
        self.pr_number = 9431

    @classmethod
    def from_action(cls, action, **kwargs):
        return cls(
            base_sha=action.prepared_remote_base_sha,
            parent_tree_sha=action.changeset_proof["parent_tree_sha"],
            new_commit_sha=action.local_commit_sha,
            new_tree_sha=action.local_tree_sha,
            **kwargs,
        )

    async def repository_metadata(self):
        self.calls.append("repository_metadata")
        return {
            "provider": "github",
            "owner": "owner",
            "repository": "repo",
            "default_branch": "main",
        }

    async def base_ref(self, branch):
        self.calls.append(f"base_ref:{branch}")
        return RemoteRef(self.base_sha)

    async def commit(self, sha):
        self.calls.append(f"commit:{sha}")
        if sha == self.new_commit_sha:
            return RemoteCommit(
                sha,
                self.new_tree_sha,
                PARENT,
                "feat: exact",
                IDENTITY,
                IDENTITY,
                int(STAMP.timestamp()),
                int(STAMP.timestamp()),
                int(STAMP.timestamp()),
                0,
                0,
            )
        return RemoteCommit(
            sha,
            self.parent_tree_sha,
            PARENT,
            "feat: exact",
            IDENTITY,
            IDENTITY,
            int(STAMP.timestamp()),
            int(STAMP.timestamp()),
            int(STAMP.timestamp()),
            0,
            0,
        )

    async def tree(self, sha):
        self.calls.append(f"tree:{sha}")
        return RemoteTree(TREE)

    async def create_blob(self, content, sha):
        self.calls.append("create_blob")
        return sha

    async def create_tree(self, base_tree_sha, entries, sha):
        self.calls.append("create_tree")
        return sha

    async def create_commit(self, **kwargs):
        self.calls.append("create_commit")
        return RemoteCommit(
            kwargs["sha"],
            kwargs["tree_sha"],
            kwargs["parent_sha"],
            kwargs["message"],
            kwargs["author"],
            kwargs["committer"],
            kwargs["timestamp"],
            kwargs["timestamp"],
            kwargs["timestamp"],
            0,
            0,
        )

    async def branch_ref(self, ref):
        self.calls.append(f"branch_ref:{ref}")
        return None if self.branch_sha is None else RemoteRef(self.branch_sha)

    async def create_branch(self, ref, sha):
        self.calls.append("create_branch")
        self.branch_sha = sha
        return RemoteRef(sha)

    async def find_pull_request(self, *, head, base):
        self.calls.append("find_pull_request")
        return self.pr

    async def create_pull_request(self, **kwargs):
        self.calls.append("create_pull_request")
        self.pr = RemotePullRequest(
            self.pr_number,
            "https://github.com/owner/repo/pull/9431",
            COMMIT,
            kwargs["title"],
            kwargs["body"],
            kwargs["head"],
            kwargs["base"],
        )
        return self.pr


def _proof() -> dict[str, object]:
    return {
        "parent_tree_sha": PARENT_TREE,
        "tree_sha": TREE,
        "changes": [],
        "message": "feat: exact",
        "author": IDENTITY,
        "committer": IDENTITY,
        "timestamp": STAMP.timestamp(),
    }


async def _persist_publication(session, ids: dict[str, UUID], *, status="PENDING_APPROVAL"):
    approval = ApprovalRequest(
        tenant_id=ids["tenant_id"],
        workspace_id=ids["workspace_id"],
        action="github.publication.create",
        requester_actor_type="service",
        requester_actor_id="github-publication:test",
        resource_type="task",
        resource_id=ids["task_id"],
        project_id=ids["project_id"],
        task_id=ids["task_id"],
        policy_effect="REQUIRE_CONFIRMATION",
        matched_rule_ids=[],
        policy_reasons=[],
    )
    session.add(approval)
    await session.flush()
    action = GitHubPublicationAction(
        tenant_id=ids["tenant_id"],
        workspace_id=ids["workspace_id"],
        project_id=ids["project_id"],
        task_id=ids["task_id"],
        workflow_run_id=ids["workflow_run_id"],
        git_commit_action_id=ids["git_action_id"],
        approval_request_id=approval.id,
        binding_version="v1",
        repository_identity={
            "provider": "github",
            "api_base": "https://api.github.com",
            "owner": "owner",
            "repository": "repo",
            "binding_key": "key",
        },
        base_branch="main",
        prepared_remote_base_sha=PARENT,
        branch_ref=f"novalton/{ids['git_action_id']}",
        local_parent_sha=PARENT,
        local_tree_sha=TREE,
        local_commit_sha=COMMIT,
        changeset_proof=_proof(),
        pr_title="Title",
        pr_body="Complete body",
        pr_body_hash=hashlib.sha256(b"Complete body").hexdigest(),
        publication_fingerprint=hashlib.sha256(b"publication").hexdigest(),
        policy_effect="REQUIRE_CONFIRMATION",
        status=status,
    )
    session.add(action)
    await session.flush()
    approval.requester_actor_id = f"github-publication:{action.id}"
    await session.commit()
    await session.refresh(action)
    return action, approval


def test_prepare_has_zero_remote_writes_and_body_fingerprint(publication_scope, monkeypatch):
    calls: list[str] = []
    _patch_service(monkeypatch, publication_scope)
    monkeypatch.setattr(service, "_root", lambda: SimpleNamespace())

    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                approval = ApprovalRequest(
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    action="github.publication.create",
                    requester_actor_type="service",
                    requester_actor_id="github-publication",
                    resource_type="task",
                    resource_id=publication_scope["task_id"],
                    project_id=publication_scope["project_id"],
                    task_id=publication_scope["task_id"],
                    policy_effect="REQUIRE_CONFIRMATION",
                    matched_rule_ids=[],
                    policy_reasons=[],
                )

                async def create(*_args, **_kwargs):
                    session.add(approval)
                    await session.flush()
                    return approval

                monkeypatch.setattr(service.approvals_service, "create_approval", create)
                action = await service.prepare(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    git_commit_action_id=publication_scope["git_action_id"],
                    data=GitHubPublicationCreate(title="Title", body="Complete body"),
                    adapter=FakeGitHub(),
                )
                assert (
                    action.status == "PENDING_APPROVAL"
                    and action.approval_request_id == approval.id
                )
                assert not calls
                assert SECRET not in action.publication_fingerprint
                assert SECRET not in repr(action.repository_identity)
        finally:
            await database.dispose()

    asyncio.run(run())


def test_prepare_approval_failure_leaves_no_orphan_publication(publication_scope, monkeypatch):
    _patch_service(monkeypatch, publication_scope)

    async def fail_create(*_args, **_kwargs):
        raise ApplicationError(
            "approval_persistence_failed", "approval unavailable", status_code=500
        )

    monkeypatch.setattr(service.approvals_service, "create_approval", fail_create)

    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError) as error:
                    await service.prepare(
                        session,
                        tenant_id=publication_scope["tenant_id"],
                        workspace_id=publication_scope["workspace_id"],
                        git_commit_action_id=publication_scope["git_action_id"],
                        data=GitHubPublicationCreate(title="Title", body="Complete body"),
                        adapter=FakeGitHub(),
                    )
                assert error.value.code == "approval_persistence_failed"
                await session.rollback()
                persisted = await session.scalar(
                    select(GitHubPublicationAction).where(
                        GitHubPublicationAction.git_commit_action_id
                        == publication_scope["git_action_id"]
                    )
                )
                assert persisted is None
        finally:
            await database.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("status", ["FAILED", "PENDING_APPROVAL", "REJECTED"])
def test_prepare_rejects_ineligible_git_commit_action(publication_scope, monkeypatch, status):
    _patch_service(monkeypatch, publication_scope)
    monkeypatch.setattr(
        service.git_repository,
        "get_scoped",
        lambda *a, **k: _value(
            SimpleNamespace(
                status=status, resulting_commit_sha=None, id=publication_scope["git_action_id"]
            )
        ),
    )
    with pytest.raises(ApplicationError, match="GitHub publication is unavailable") as error:
        asyncio.run(_prepare_without_db(publication_scope))
    assert error.value.code == "git_commit_not_approved"


async def _prepare_without_db(ids):
    database = Database.from_settings(Settings.from_environment())
    try:
        async with database.session_factory() as session:
            return await service.prepare(
                session,
                tenant_id=ids["tenant_id"],
                workspace_id=ids["workspace_id"],
                git_commit_action_id=ids["git_action_id"],
                data=GitHubPublicationCreate(title="Title"),
                adapter=FakeGitHub(),
            )
    finally:
        await database.dispose()


@pytest.mark.parametrize("wrong_scope", ["tenant_id", "workspace_id"])
def test_publish_is_fail_closed_for_foreign_scope(publication_scope, monkeypatch, wrong_scope):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                foreign = uuid4()
                kwargs = {
                    "tenant_id": publication_scope["tenant_id"],
                    "workspace_id": publication_scope["workspace_id"],
                    "approval_id": approval.id,
                }
                kwargs[wrong_scope] = foreign
                with pytest.raises(ApplicationError) as error:
                    await service.publish(session, **kwargs, adapter=FakeGitHub.from_action(action))
                assert error.value.code == "resource_not_found"
                assert action.status == "PENDING_APPROVAL"
        finally:
            await database.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("field", ["project_id", "task_id"])
def test_publish_rejects_foreign_persisted_scope_linkage(publication_scope, monkeypatch, field):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                await service.approvals_service.approve(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                )
                if field == "project_id":
                    approval.project_id = publication_scope["foreign_project_id"]
                else:
                    approval.task_id = publication_scope["foreign_task_id"]
                await session.commit()
                _patch_publish(monkeypatch)
                with pytest.raises(ApplicationError) as error:
                    await service.publish(
                        session,
                        tenant_id=publication_scope["tenant_id"],
                        workspace_id=publication_scope["workspace_id"],
                        approval_id=approval.id,
                        adapter=FakeGitHub.from_action(action),
                    )
                assert error.value.code == "approval_not_satisfied"
                await session.refresh(action)
                assert action.status == "PENDING_APPROVAL"
        finally:
            await database.dispose()

    asyncio.run(run())


def _patch_publish(monkeypatch, *, qa=None):
    monkeypatch.setattr(
        service,
        "trusted_binding",
        make_test_github_binding,
    )
    monkeypatch.setattr(service, "_root", lambda: SimpleNamespace())
    monkeypatch.setattr(service.local, "read_publication_objects", lambda *a, **k: (_proof(), []))
    monkeypatch.setattr(
        service.policy_service,
        "evaluate",
        lambda *a, **k: _value(SimpleNamespace(effect=PolicyEffect.REQUIRE_CONFIRMATION)),
    )
    monkeypatch.setattr(
        service.git_service,
        "_workflow",
        lambda *a, **k: _value(
            SimpleNamespace(tenant_id=k["tenant_id"], workspace_id=k["workspace_id"])
        ),
    )
    if qa is None:
        monkeypatch.setattr(service.git_service, "_qa_eligible", lambda *a, **k: _value(None))
    else:

        async def reject(*_args, **_kwargs):
            raise ApplicationError(qa, "ineligible", status_code=409)

        monkeypatch.setattr(service.git_service, "_qa_eligible", reject)


@pytest.mark.parametrize("mode", ["success", "stale", "branch_conflict", "pr_conflict"])
def test_publish_reconciliation_outcomes_are_persisted(publication_scope, monkeypatch, mode):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                await service.approvals_service.approve(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                )
                adapter = FakeGitHub.from_action(
                    action,
                    branch_sha=("9" * 40 if mode == "branch_conflict" else None),
                )
                if mode == "pr_conflict":
                    adapter.pr = RemotePullRequest(
                        7,
                        "https://github.com/owner/repo/pull/7",
                        COMMIT,
                        "wrong",
                        "wrong",
                        action.branch_ref,
                        "main",
                    )
                _patch_publish(monkeypatch)
                if mode == "stale":
                    monkeypatch.setattr(
                        adapter, "base_ref", lambda branch: _value(RemoteRef("9" * 40))
                    )
                if mode == "success":
                    result = await service.publish(
                        session,
                        tenant_id=publication_scope["tenant_id"],
                        workspace_id=publication_scope["workspace_id"],
                        approval_id=approval.id,
                        adapter=adapter,
                    )
                    assert (
                        result.status == "PUBLISHED"
                        and result.remote_commit_sha == COMMIT
                        and result.pr_number == 9431
                    )
                else:
                    with pytest.raises(ApplicationError) as error:
                        await service.publish(
                            session,
                            tenant_id=publication_scope["tenant_id"],
                            workspace_id=publication_scope["workspace_id"],
                            approval_id=approval.id,
                            adapter=adapter,
                        )
                    expected = {
                        "stale": "stale_base",
                        "branch_conflict": "branch_conflict",
                        "pr_conflict": "pr_conflict",
                    }[mode]
                    assert error.value.code == expected
                    await session.refresh(action)
                    assert action.status == ("STALE" if mode == "stale" else "CONFLICT")
                    assert action.remote_commit_sha is None and action.pr_number is None
        finally:
            await database.dispose()

    asyncio.run(run())


def test_publish_retry_converges_without_duplicate_branch_or_pr(publication_scope, monkeypatch):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                await service.approvals_service.approve(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                )
                _patch_publish(monkeypatch)
                adapter = FakeGitHub.from_action(action)
                await service.publish(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                    adapter=adapter,
                )
                first_calls = list(adapter.calls)
                result = await service.publish(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                    adapter=adapter,
                )
                assert result.status == "PUBLISHED" and result.id == action.id
                assert adapter.calls == first_calls
                assert (
                    adapter.calls.count("create_branch") == 1
                    and adapter.calls.count("create_pull_request") == 1
                )
        finally:
            await database.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("partial", ["branch", "pr"])
def test_publish_retries_partial_remote_success(publication_scope, monkeypatch, partial):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(
                    session, publication_scope, status="PUBLISHING"
                )
                await service.approvals_service.approve(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                )
                adapter = FakeGitHub.from_action(action, branch_sha=COMMIT)
                if partial == "pr":
                    adapter.pr = RemotePullRequest(
                        9431,
                        "https://github.com/owner/repo/pull/9431",
                        COMMIT,
                        action.pr_title,
                        action.pr_body,
                        action.branch_ref,
                        action.base_branch,
                    )
                _patch_publish(monkeypatch)
                result = await service.publish(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                    adapter=adapter,
                )
                assert result.status == "PUBLISHED" and result.pr_number == 9431
                assert adapter.calls.count("create_branch") == 0
                assert adapter.calls.count("create_pull_request") == (0 if partial == "pr" else 1)
        finally:
            await database.dispose()

    asyncio.run(run())


def test_i043_approval_route_continues_publication_only(publication_scope, monkeypatch):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                _patch_publish(monkeypatch)
                adapter = FakeGitHub.from_action(action)
                called = {"git": 0, "mutation": 0}

                async def forbidden_git(*_args, **_kwargs):
                    called["git"] += 1
                    raise AssertionError("I-043 approval routed to I-042")

                async def forbidden_mutation(*_args, **_kwargs):
                    called["mutation"] += 1
                    raise AssertionError("I-043 approval routed to I-041")

                monkeypatch.setattr(approval_routes.git_service, "approve_and_apply", forbidden_git)
                monkeypatch.setattr(
                    approval_routes.mutation_resume, "approve_and_resume", forbidden_mutation
                )
                request = SimpleNamespace(
                    app=SimpleNamespace(state=SimpleNamespace(github_publication_adapter=adapter))
                )
                response = await approval_routes.approve(
                    publication_scope["tenant_id"],
                    publication_scope["workspace_id"],
                    approval.id,
                    session,
                    request,
                )
                assert response.id == approval.id
                await session.refresh(action)
                assert action.status == "PUBLISHED"
                assert called == {"git": 0, "mutation": 0}
        finally:
            await database.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("qa_code", ["git_qa_ineligible", "git_challenge_unresolved"])
def test_publish_fails_closed_for_qa_and_unresolved_challenge(
    publication_scope, monkeypatch, qa_code
):
    async def run():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                action, approval = await _persist_publication(session, publication_scope)
                await service.approvals_service.approve(
                    session,
                    tenant_id=publication_scope["tenant_id"],
                    workspace_id=publication_scope["workspace_id"],
                    approval_id=approval.id,
                )
                _patch_publish(monkeypatch, qa=qa_code)
                with pytest.raises(ApplicationError) as error:
                    await service.publish(
                        session,
                        tenant_id=publication_scope["tenant_id"],
                        workspace_id=publication_scope["workspace_id"],
                        approval_id=approval.id,
                        adapter=FakeGitHub.from_action(action),
                    )
                assert error.value.code == qa_code
                assert action.status == "PENDING_APPROVAL"
        finally:
            await database.dispose()

    asyncio.run(run())


def test_secret_free_persistence_and_token_independent_fingerprint(publication_scope, monkeypatch):
    _patch_service(monkeypatch, publication_scope)
    monkeypatch.setattr(
        github_config,
        "get_settings",
        lambda: SimpleNamespace(github_publication_pat=SecretStr(SECRET)),
    )
    credential = github_config.resolve_github_credential()
    assert credential.get_secret_value() == SECRET
    assert repr(credential) == "SecretStr('**********')"
    assert SECRET not in repr(GitHubPublicationAction.__table__.columns)
    assert "token" not in {column.name for column in GitHubPublicationAction.__table__.columns}
    payload = "|".join(
        [
            COMMIT,
            "main",
            f"novalton/{publication_scope['git_action_id']}",
            "Title",
            hashlib.sha256(b"Complete body").hexdigest(),
            "v1",
            "key",
        ]
    )
    assert hashlib.sha256(payload.encode()).hexdigest() != SECRET


def test_publication_constraints_cover_commit_approval_and_policy_ownership():
    names = {constraint.name for constraint in GitHubPublicationAction.__table__.constraints}
    assert "uq_github_publication_git_action" in names
    assert "uq_github_publication_approval" in names
    assert "ck_github_publication_policy" in names
