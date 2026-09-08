"""Provider-free publication orchestration tests using a deterministic fake remote."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

# Load the declarative base/model registry before service imports; this is the
# same application import order used by the API entrypoint.
from novalton_api import main as _app_main  # noqa: F401
from novalton_api.modules.github_publications import service
from novalton_api.modules.github_publications.adapter import (
    GitHubOperationalError,
    RemoteCommit,
)
from novalton_api.modules.github_publications.config import GitHubBinding

IDENTITY = "Novalton OS <novalton@local.invalid>"
STAMP = datetime(2026, 9, 2, 12, 34, 56, tzinfo=UTC)
PARENT, TREE, COMMIT, BLOB = "1" * 40, "b" * 40, "a" * 40, "c" * 40


def binding() -> GitHubBinding:
    return GitHubBinding(
        "github", "https://api.github.com", "owner", "repo", "main", "v1", "key", "/workspace"
    )


class FakeAdapter:
    def __init__(self) -> None:
        self.base_calls = 0
        self.change_base_on_call: int | None = None
        self.branch_sha: str | None = None
        self.pr = None
        self.blobs: list[tuple[bytes, str]] = []
        self.trees: list[tuple[str, list[dict[str, object]], str]] = []
        self.commits: list[dict[str, object]] = []
        self.remote_commits: dict[str, SimpleNamespace] = {}
        self.branch_creates = self.pr_creates = 0
        self.branch_error: BaseException | None = None
        self.pr_error: BaseException | None = None
        self.blob_error: BaseException | None = None
        self.metadata_error: BaseException | None = None
        self.base_error: BaseException | None = None
        self.tree_error: BaseException | None = None
        self.tree_missing = True
        self.commit_error: BaseException | None = None
        self.commit_error_sha: str | None = None
        self.created_commit_sha: str | None = None

    async def repository_metadata(self):
        if self.metadata_error:
            error, self.metadata_error = self.metadata_error, None
            raise error
        return {
            "provider": "github",
            "owner": "owner",
            "repository": "repo",
            "default_branch": "main",
        }

    async def base_ref(self, _branch: str):
        if self.base_error:
            error, self.base_error = self.base_error, None
            raise error
        self.base_calls += 1
        sha = (
            "2" * 40
            if self.change_base_on_call and self.base_calls >= self.change_base_on_call
            else PARENT
        )
        return SimpleNamespace(sha=sha)

    async def commit(self, sha: str):
        if self.commit_error and (self.commit_error_sha is None or self.commit_error_sha == sha):
            error, self.commit_error = self.commit_error, None
            raise error
        if sha in self.remote_commits:
            return self.remote_commits[sha]
        if sha == PARENT:
            return SimpleNamespace(sha=sha, tree_sha="remote-parent-tree")
        return None

    async def create_blob(self, content: bytes, sha: str):
        self.blobs.append((content, sha))
        if self.blob_error:
            raise self.blob_error
        return sha

    async def create_tree(self, parent: str, entries: list[dict[str, object]], sha: str):
        self.trees.append((parent, entries, sha))
        return sha

    async def create_commit(self, **kwargs: object):
        self.commits.append(kwargs)
        actual_sha = self.created_commit_sha or kwargs["sha"]
        response = {**kwargs, "sha": actual_sha}
        result = SimpleNamespace(
            **response,
            author_timestamp=kwargs["timestamp"],
            committer_timestamp=kwargs["timestamp"],
            author_timezone=0,
            committer_timezone=0,
        )
        self.remote_commits[actual_sha] = result
        return result

    async def branch_ref(self, _ref: str):
        return None if self.branch_sha is None else SimpleNamespace(sha=self.branch_sha)

    async def create_branch(self, _ref: str, sha: str):
        self.branch_creates += 1
        if self.branch_error:
            error, self.branch_error = self.branch_error, None
            self.branch_sha = sha if getattr(error, "remote_completed", False) else None
            raise error
        self.branch_sha = sha
        return SimpleNamespace(sha=sha)

    async def tree(self, _sha: str):
        if self.tree_error:
            error, self.tree_error = self.tree_error, None
            raise error
        if self.tree_missing:
            return None
        return SimpleNamespace(sha=TREE)

    async def find_pull_request(self, **_kwargs: object):
        return self.pr

    async def create_pull_request(self, **kwargs: object):
        self.pr_creates += 1
        self.pr = SimpleNamespace(
            number=7,
            url="https://github.invalid/7",
            head_sha=COMMIT,
            title=kwargs["title"],
            body=kwargs["body"],
            head_ref=kwargs["head"],
            base_ref=kwargs["base"],
        )
        if self.pr_error:
            error, self.pr_error = self.pr_error, None
            raise error
        return self.pr


class FakeSession:
    def __init__(self, action: SimpleNamespace):
        self.action = action

    async def commit(self):
        return None

    async def refresh(self, _action):
        return None


def make_action() -> SimpleNamespace:
    aid = uuid4()
    return SimpleNamespace(
        id=aid,
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        task_id=uuid4(),
        workflow_run_id=uuid4(),
        approval_request_id=uuid4(),
        status="PENDING_APPROVAL",
        prepared_remote_base_sha=PARENT,
        local_parent_sha=PARENT,
        local_tree_sha=TREE,
        local_commit_sha=COMMIT,
        branch_ref=f"novalton/{aid}",
        pr_title="Title",
        pr_body="Body",
        changeset_proof={
            "message": "feat: exact",
            "author": IDENTITY,
            "committer": IDENTITY,
            "timestamp": int(STAMP.timestamp()),
            "changes": [
                {
                    "path": "fixture.txt",
                    "mode": 0o100644,
                    "candidate_blob_id": BLOB,
                    "candidate_sha256": "d" * 64,
                }
            ],
        },
    )


async def value(item):
    return item


def make_harness(monkeypatch: pytest.MonkeyPatch):
    item = make_action()
    session = FakeSession(item)
    monkeypatch.setattr(service.repository, "get_for_approval", lambda *a, **k: value(item))
    monkeypatch.setattr(
        service.policy_service,
        "evaluate",
        lambda *a, **k: value(SimpleNamespace(effect=service.PolicyEffect.REQUIRE_CONFIRMATION)),
    )
    monkeypatch.setattr(
        service.approvals_service, "is_approval_satisfied", lambda *a, **k: value(True)
    )
    monkeypatch.setattr(service.git_service, "_workflow", lambda *a, **k: value(SimpleNamespace()))
    monkeypatch.setattr(service.git_service, "_qa_eligible", lambda *a, **k: value(None))
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(environment="test"))
    monkeypatch.setattr(service, "trusted_binding", binding)
    monkeypatch.setattr(service, "_root", lambda: SimpleNamespace())
    monkeypatch.setattr(
        service.local,
        "read_publication_objects",
        lambda *a, **k: ({}, [("fixture.txt", 0o100644, b"new\n", BLOB)]),
    )
    return session, item


async def publish(session: FakeSession, adapter: FakeAdapter):
    return await service.publish(
        session,
        tenant_id=session.action.tenant_id,
        workspace_id=session.action.workspace_id,
        approval_id=session.action.approval_request_id,
        adapter=adapter,
    )


@pytest.mark.asyncio
async def test_exact_tree_commit_branch_pr_replay_and_retry(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert adapter.blobs == [(b"new\n", BLOB)]
    assert adapter.trees == [
        (
            "remote-parent-tree",
            [{"path": "fixture.txt", "mode": "100644", "type": "blob", "sha": BLOB}],
            TREE,
        )
    ]
    assert adapter.commits[0] == {
        "tree_sha": TREE,
        "parent_sha": PARENT,
        "message": "feat: exact",
        "author": IDENTITY,
        "committer": IDENTITY,
        "timestamp": int(STAMP.timestamp()),
        "sha": COMMIT,
    }
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1
    item.status = "PUBLISHED"
    await publish(session, adapter)
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_initial_tree_read_is_explicit_absence_then_created(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()

    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert len(adapter.trees) == 1
    assert len(adapter.commits) == 1


@pytest.mark.asyncio
async def test_initial_tree_read_failure_is_failed_without_later_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.tree_error = GitHubOperationalError("tree provider failure")

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "tree_read_failed"
    assert item.status == "FAILED" and item.failure_code == "tree_read_failed"
    assert adapter.trees == [] and adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_initial_tree_mismatch_is_conflict_without_later_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()

    async def wrong_tree(_sha: str):
        return SimpleNamespace(sha="0" * 40)

    adapter.tree_missing = False
    adapter.tree = wrong_tree
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "tree_sha_mismatch"
    assert item.status == "CONFLICT" and item.failure_code == "tree_sha_mismatch"
    assert adapter.trees == [] and adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_initial_commit_read_failure_is_failed_without_later_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.commit_error = GitHubOperationalError("commit provider failure")
    adapter.commit_error_sha = COMMIT

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "commit_read_failed"
    assert item.status == "FAILED" and item.failure_code == "commit_read_failed"
    assert adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_initial_commit_mismatch_is_conflict_without_recreation(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()

    async def wrong_commit(sha: str):
        if sha == PARENT:
            return SimpleNamespace(sha=PARENT, tree_sha="remote-parent-tree")
        return RemoteCommit(
            sha="0" * 40,
            tree_sha=TREE,
            parent_sha=PARENT,
            message="feat: exact",
            author=IDENTITY,
            committer=IDENTITY,
            timestamp=int(STAMP.timestamp()),
            author_timestamp=int(STAMP.timestamp()),
            committer_timestamp=int(STAMP.timestamp()),
            author_timezone=0,
            committer_timezone=0,
        )

    adapter.commit = wrong_commit
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "commit_sha_mismatch"
    assert item.status == "CONFLICT" and item.failure_code == "commit_sha_mismatch"
    assert adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_created_commit_with_different_actual_sha_is_conflict_without_branch_or_pr(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.created_commit_sha = "0" * 40

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "commit_sha_mismatch"
    assert item.status == "CONFLICT" and item.failure_code == "commit_sha_mismatch"
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_stale_before_branch_and_branch_timeout_reconcile(monkeypatch: pytest.MonkeyPatch):
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.change_base_on_call = 2
    with pytest.raises(Exception) as error:
        await publish(session, adapter)
    assert getattr(error.value, "code", None) == "stale_base"
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    branch_error = GitHubOperationalError("branch_creation_failed")
    branch_error.remote_completed = True
    adapter.branch_error = branch_error
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED" and adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_stale_prepared_base_and_422_branch_race_reconcile(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    item.prepared_remote_base_sha = "9" * 40
    adapter = FakeAdapter()
    with pytest.raises(Exception) as error:
        await publish(session, adapter)
    assert getattr(error.value, "code", None) == "stale_base"
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    branch_error = GitHubOperationalError("branch_creation_failed")
    branch_error.remote_completed = True
    adapter.branch_error = branch_error
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED" and adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_repository_binding_mismatch_fails_before_any_write(monkeypatch: pytest.MonkeyPatch):
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.repository_metadata = lambda: value(
        {"provider": "github", "owner": "wrong", "repository": "repo"}
    )
    with pytest.raises(Exception) as error:
        await publish(session, adapter)
    assert getattr(error.value, "code", None) == "repository_mismatch"
    assert adapter.blobs == [] and adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_branch_and_pr_reconciliation_variants(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.branch_sha = COMMIT
    adapter.pr = SimpleNamespace(
        number=7,
        url="x",
        head_sha=COMMIT,
        title=item.pr_title,
        body=item.pr_body,
        head_ref=item.branch_ref,
        base_ref="main",
    )
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED" and adapter.branch_creates == 0 and adapter.pr_creates == 0

    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.branch_sha = "0" * 40
    with pytest.raises(Exception) as error:
        await publish(session, adapter)
    assert getattr(error.value, "code", None) == "branch_conflict"
    assert adapter.pr_creates == 0

    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.pr_error = GitHubOperationalError("pr_creation_failed")
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED" and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_blob_failure_has_no_branch_or_pr_writes(monkeypatch: pytest.MonkeyPatch):
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.blob_error = GitHubOperationalError("github_blob_sha_mismatch")
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)
    assert error.value.code == "blob_creation_failed"
    assert session.action.status == "FAILED"
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("tree", "tree_creation_failed"),
        ("commit", "commit_creation_failed"),
        ("branch", "branch_creation_uncertain"),
        ("pr", "pr_creation_uncertain"),
    ],
)
async def test_remote_failures_are_durable_and_bounded(
    monkeypatch: pytest.MonkeyPatch, failure: str, code: str
):
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    if failure == "tree":

        async def fail_tree(*_args, **_kwargs):
            raise GitHubOperationalError("provider secret body")

        adapter.create_tree = fail_tree
    elif failure == "commit":

        async def fail_commit(**_kwargs):
            raise GitHubOperationalError("commit_creation_failed")

        adapter.create_commit = fail_commit
    elif failure == "branch":
        adapter.branch_error = GitHubOperationalError("branch_creation_failed")
    else:

        async def fail_pr(**_kwargs):
            raise GitHubOperationalError("pr_creation_failed")

        adapter.create_pull_request = fail_pr
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)
    assert error.value.code == code
    assert session.action.status == "FAILED"
    assert session.action.failure_code == code
    assert "provider secret" not in repr(session.action)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    [("metadata", "repository_metadata_failed"), ("base", "remote_base_read_failed")],
)
async def test_early_remote_read_failures_from_publishing_are_durable_and_bounded(
    monkeypatch: pytest.MonkeyPatch, failure: str, code: str
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    sentinel = "NOVALTON_EARLY_READ_SECRET"
    if failure == "metadata":
        adapter.metadata_error = GitHubOperationalError(f"provider body Authorization: {sentinel}")
    else:
        adapter.base_error = GitHubOperationalError(f"provider body Authorization: {sentinel}")

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == code
    assert str(error.value) == "GitHub publication is unavailable"
    assert item.status == "FAILED"
    assert item.failure_code == code
    assert sentinel not in repr(item)
    assert sentinel not in str(error.value)
    assert adapter.blobs == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_failed_early_remote_read_retries_to_published_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    adapter.metadata_error = GitHubOperationalError("provider body Authorization: sentinel")

    with pytest.raises(service.ApplicationError):
        await publish(session, adapter)
    assert item.status == "FAILED"
    assert item.failure_code == "repository_metadata_failed"

    adapter.remote_commits[COMMIT] = SimpleNamespace(
        sha=COMMIT,
        tree_sha=TREE,
        parent_sha=PARENT,
        message="feat: exact",
        author=IDENTITY,
        committer=IDENTITY,
        author_timestamp=int(STAMP.timestamp()),
        committer_timestamp=int(STAMP.timestamp()),
        author_timezone=0,
        committer_timezone=0,
    )
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_existing_tree_wrong_sha_is_conflict_without_recreation(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()

    async def wrong_tree(_sha: str):
        return SimpleNamespace(sha="0" * 40)

    adapter.tree = wrong_tree
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "tree_sha_mismatch"
    assert item.status == "CONFLICT"
    assert item.failure_code == "tree_sha_mismatch"
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0
    assert adapter.trees == []


@pytest.mark.asyncio
async def test_missing_tree_is_created_on_retry(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    adapter.tree_missing = True
    adapter.remote_commits[COMMIT] = RemoteCommit(
        sha=COMMIT,
        tree_sha=TREE,
        parent_sha=PARENT,
        message="feat: exact",
        author=IDENTITY,
        committer=IDENTITY,
        timestamp=int(STAMP.timestamp()),
        author_timestamp=int(STAMP.timestamp()),
        committer_timestamp=int(STAMP.timestamp()),
        author_timezone=0,
        committer_timezone=0,
    )

    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert len(adapter.trees) == 1
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_tree_read_failure_is_failed_without_replacement_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    adapter.tree_error = GitHubOperationalError("provider body Authorization: sentinel")

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "tree_read_failed"
    assert item.status == "FAILED"
    assert item.failure_code == "tree_read_failed"
    assert adapter.trees == []
    assert adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0
    assert "sentinel" not in repr(item)
    assert "sentinel" not in str(error.value)


@pytest.mark.asyncio
async def test_missing_commit_is_created_on_retry(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()

    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert len(adapter.commits) == 1
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
async def test_commit_read_failure_is_failed_without_replacement_writes(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    adapter.commit_error = GitHubOperationalError("provider body Authorization: sentinel")
    adapter.commit_error_sha = COMMIT

    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "commit_read_failed"
    assert item.status == "FAILED"
    assert item.failure_code == "commit_read_failed"
    assert adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0
    assert "sentinel" not in repr(item)
    assert "sentinel" not in str(error.value)


@pytest.mark.asyncio
async def test_commit_wrong_sha_is_conflict_without_recreation(
    monkeypatch: pytest.MonkeyPatch,
):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()

    async def wrong_commit(sha: str):
        if sha == PARENT:
            return SimpleNamespace(sha=PARENT, tree_sha="remote-parent-tree")
        return RemoteCommit(
            sha="0" * 40,
            tree_sha=TREE,
            parent_sha=PARENT,
            message="feat: exact",
            author=IDENTITY,
            committer=IDENTITY,
            timestamp=int(STAMP.timestamp()),
            author_timestamp=int(STAMP.timestamp()),
            committer_timestamp=int(STAMP.timestamp()),
            author_timezone=0,
            committer_timezone=0,
        )

    adapter.commit = wrong_commit
    with pytest.raises(service.ApplicationError) as error:
        await publish(session, adapter)

    assert error.value.code == "commit_sha_mismatch"
    assert item.status == "CONFLICT"
    assert item.failure_code == "commit_sha_mismatch"
    assert adapter.commits == []
    assert adapter.branch_creates == 0 and adapter.pr_creates == 0


@pytest.mark.asyncio
async def test_programming_exception_is_not_converted_to_failed(monkeypatch: pytest.MonkeyPatch):
    session, item = make_harness(monkeypatch)
    item.status = "PUBLISHING"
    adapter = FakeAdapter()
    adapter.metadata_error = TypeError("programming defect")

    with pytest.raises(TypeError, match="programming defect"):
        await publish(session, adapter)
    assert item.status == "PUBLISHING"
    assert not hasattr(item, "failure_code")


@pytest.mark.asyncio
async def test_failed_branch_retry_reconciles_without_duplicate_branch(monkeypatch):
    session, _ = make_harness(monkeypatch)
    adapter = FakeAdapter()
    adapter.branch_error = GitHubOperationalError("branch_creation_failed")
    with pytest.raises(service.ApplicationError):
        await publish(session, adapter)
    assert session.action.status == "FAILED"
    adapter.branch_sha = COMMIT
    result = await publish(session, adapter)
    assert result.status == "PUBLISHED"
    assert adapter.branch_creates == 1 and adapter.pr_creates == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tree", "commit", "pr"])
async def test_tree_commit_pr_mismatch_fails_before_branch(
    monkeypatch: pytest.MonkeyPatch, field: str
):
    session, item = make_harness(monkeypatch)
    adapter = FakeAdapter()
    if field == "tree":
        adapter.create_tree = lambda *args: value("0" * 40)
    elif field == "commit":

        async def wrong_commit(**kwargs: object):
            return SimpleNamespace(
                **{**kwargs, "sha": "0" * 40},
                author_timestamp=kwargs["timestamp"],
                committer_timestamp=kwargs["timestamp"],
                author_timezone=0,
                committer_timezone=0,
            )

        adapter.create_commit = wrong_commit
    else:
        adapter.pr = SimpleNamespace(
            number=7,
            url="x",
            head_sha=COMMIT,
            title="wrong",
            body=item.pr_body,
            head_ref=item.branch_ref,
            base_ref="main",
        )
    with pytest.raises((RuntimeError, service.ApplicationError)):
        await publish(session, adapter)
    assert adapter.branch_creates == (0 if field != "pr" else 1)


def test_fake_surface_has_no_ref_or_pr_authority_escape_hatches():
    assert not set(dir(FakeAdapter)).intersection(
        {"update_ref", "force", "delete_ref", "merge", "close_pr", "comment", "review"}
    )
