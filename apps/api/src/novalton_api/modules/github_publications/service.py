"""Approval-gated exact-SHA GitHub publication orchestration."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.approvals import service as approvals_service
from novalton_api.modules.approvals.schemas import ApprovalCreate
from novalton_api.modules.git_changesets import local
from novalton_api.modules.git_changesets import repository as git_repository
from novalton_api.modules.git_changesets import service as git_service
from novalton_api.modules.github_publications import repository
from novalton_api.modules.github_publications.adapter import (
    GitHubOperationalError,
    GitHubPublicationAdapter,
)
from novalton_api.modules.github_publications.config import trusted_binding
from novalton_api.modules.github_publications.models import GitHubPublicationAction
from novalton_api.modules.github_publications.schemas import GitHubPublicationCreate
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationContext,
    PolicyEvaluationRequest,
)
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot

ACTION = "github.publication.create"


def _fail(code: str) -> ApplicationError:
    return ApplicationError(code, "GitHub publication is unavailable", status_code=409)


def _policy(action: GitHubPublicationAction) -> PolicyEvaluationRequest:
    return PolicyEvaluationRequest(
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        action=ACTION,
        actor_type="service",
        actor_id=f"github-publication:{action.id}",
        resource_type="task",
        resource_id=action.task_id,
        project_id=action.project_id,
        task_id=action.task_id,
        context=PolicyEvaluationContext(
            risk_level="CRITICAL", environment=get_settings().environment, reversible=False
        ),
    )


def _root() -> WorkspaceRoot:
    value = get_settings().workspace_root
    if value is None:
        raise _fail("workspace_root_unavailable")
    try:
        return WorkspaceRoot.approved(value)
    except ToolExecutionError:
        raise _fail("workspace_root_unavailable") from None


async def prepare(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    git_commit_action_id: UUID,
    data: GitHubPublicationCreate,
    adapter: GitHubPublicationAdapter,
) -> GitHubPublicationAction:
    existing = await repository.get_for_commit(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        git_commit_action_id=git_commit_action_id,
        for_update=True,
    )
    commit = await git_repository.get_scoped(
        session, tenant_id=tenant_id, workspace_id=workspace_id, action_id=git_commit_action_id
    )
    if commit is None or commit.status != "APPLIED" or not commit.resulting_commit_sha:
        raise _fail("git_commit_not_approved")
    binding = trusted_binding()
    if commit.repository_key != hashlib.sha256(binding.workspace_root.encode()).hexdigest():
        raise _fail("repository_binding_mismatch")
    if commit.branch_ref != f"refs/heads/{binding.base_branch}":
        raise _fail("base_branch_mismatch")
    try:
        metadata = await adapter.repository_metadata()
        if (
            metadata.get("provider") != binding.provider
            or metadata.get("owner") != binding.owner
            or metadata.get("repository") != binding.repository
            or metadata.get("default_branch") != binding.base_branch
        ):
            raise _fail("repository_mismatch")
        observed_base = (await adapter.base_ref(binding.base_branch)).sha
    except ApplicationError:
        raise
    except GitHubOperationalError:
        raise _fail("remote_base_read_failed") from None
    if observed_base != commit.prepared_head_sha:
        raise _fail("stale_base")
    try:
        proof, _ = local.read_publication_objects(
            _root(),
            expected_commit=commit.resulting_commit_sha,
            expected_parent=commit.prepared_head_sha,
            branch_ref=commit.branch_ref,
            message=commit.commit_message,
            author=commit.author_identity,
            committer=commit.committer_identity,
            timestamp=commit.commit_timestamp,
            paths=commit.prepared_paths,
        )
    except ToolExecutionError as error:
        raise _fail(error.code) from None
    branch = f"novalton/{commit.id}"
    body_hash = hashlib.sha256(data.body.encode()).hexdigest()
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "commit": commit.resulting_commit_sha,
                "base": observed_base,
                "branch": branch,
                "title": data.title,
                "body": body_hash,
                "binding": binding.version,
                "key": binding.key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if existing is not None:
        expected_identity = {
            "provider": "github",
            "api_base": "https://api.github.com",
            "owner": binding.owner,
            "repository": binding.repository,
            "binding_key": binding.key,
        }
        if (
            existing.repository_identity != expected_identity
            or existing.binding_version != binding.version
            or existing.prepared_remote_base_sha != observed_base
            or existing.branch_ref != branch
            or existing.pr_title != data.title
            or existing.pr_body_hash != body_hash
            or existing.pr_body != data.body
            or existing.publication_fingerprint != fingerprint
        ):
            raise _fail("publication_conflict")
        return existing
    action = GitHubPublicationAction(
        id=uuid4(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=commit.project_id,
        task_id=commit.task_id,
        workflow_run_id=commit.workflow_run_id,
        git_commit_action_id=commit.id,
        binding_version=binding.version,
        repository_identity={
            "provider": "github",
            "api_base": "https://api.github.com",
            "owner": binding.owner,
            "repository": binding.repository,
            "binding_key": binding.key,
        },
        base_branch=binding.base_branch,
        prepared_remote_base_sha=observed_base,
        branch_ref=branch,
        local_parent_sha=commit.prepared_head_sha,
        local_tree_sha=str(proof["tree_sha"]),
        local_commit_sha=commit.resulting_commit_sha,
        changeset_proof=proof,
        pr_title=data.title,
        pr_body=data.body,
        pr_body_hash=body_hash,
        publication_fingerprint=fingerprint,
        policy_effect="REQUIRE_CONFIRMATION",
        status="PENDING_APPROVAL",
    )
    decision = await policy_service.evaluate(session, request=_policy(action))
    if decision.effect != PolicyEffect.REQUIRE_CONFIRMATION:
        raise _fail("publication_policy_rejected")
    approval = await approvals_service.create_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=ApprovalCreate(
            action=ACTION,
            requester_actor_type="service",
            requester_actor_id=f"github-publication:{action.id}",
            resource_type="task",
            resource_id=action.task_id,
            project_id=action.project_id,
            task_id=action.task_id,
            context=PolicyEvaluationContext(
                risk_level="CRITICAL", environment=get_settings().environment, reversible=False
            ),
        ),
        commit=False,
    )
    action.approval_request_id = approval.id
    session.add(action)
    await session.flush()
    await session.commit()
    await session.refresh(action)
    return action


async def publish(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    adapter: GitHubPublicationAdapter,
) -> GitHubPublicationAction:
    action = await repository.get_for_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
        for_update=True,
    )
    if action is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if action.status == "PUBLISHED":
        return action
    retrying = action.status in {"PUBLISHING", "FAILED"}
    request = _policy(action)
    if (
        (await policy_service.evaluate(session, request=request)).effect
        != PolicyEffect.REQUIRE_CONFIRMATION
        or not await approvals_service.is_approval_satisfied(
            session, approval_id=approval_id, request=request
        )
    ):
        raise _fail("approval_not_satisfied")
    binding = trusted_binding()
    try:
        metadata = await adapter.repository_metadata()
    except GitHubOperationalError:
        return await _mark_failed(session, action, "repository_metadata_failed")
    if (
        metadata.get("provider") != binding.provider
        or metadata.get("owner") != binding.owner
        or metadata.get("repository") != binding.repository
        or metadata.get("default_branch") != binding.base_branch
    ):
        raise _fail("repository_mismatch")
    run = await git_service._workflow(
        session,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        workflow_run_id=action.workflow_run_id,
    )
    await git_service._qa_eligible(session, run)
    try:
        current_base = (await adapter.base_ref(binding.base_branch)).sha
    except GitHubOperationalError:
        return await _mark_failed(session, action, "remote_base_read_failed")
    if current_base != action.prepared_remote_base_sha:
        return await _mark(session, action, "STALE", "stale_base")
    proof, objects = local.read_publication_objects(
        _root(),
        expected_commit=action.local_commit_sha,
        expected_parent=action.local_parent_sha,
        branch_ref=f"refs/heads/{binding.base_branch}",
        message=action.changeset_proof.get("message", ""),
        author=action.changeset_proof.get("author", ""),
        committer=action.changeset_proof.get("committer", ""),
        timestamp=datetime.fromtimestamp(float(action.changeset_proof.get("timestamp", 0)), UTC),
        paths=action.changeset_proof.get("changes", []),
        expected_tree=action.local_tree_sha,
    )
    action.status = "PUBLISHING"
    await session.commit()
    for _, _, content, blob_sha in objects:
        try:
            blob_reader = getattr(adapter, "blob", None)
            if retrying and blob_reader is not None:
                existing_blob = await blob_reader(blob_sha)
                if existing_blob is not None and existing_blob.sha != blob_sha:
                    return await _mark(session, action, "CONFLICT", "blob_sha_mismatch")
                if (
                    existing_blob is None
                    and await adapter.create_blob(content, blob_sha) != blob_sha
                ):
                    return await _mark(session, action, "CONFLICT", "blob_sha_mismatch")
            else:
                if await adapter.create_blob(content, blob_sha) != blob_sha:
                    return await _mark(session, action, "CONFLICT", "blob_sha_mismatch")
        except GitHubOperationalError:
            return await _mark_failed(session, action, "blob_creation_failed")
    entries = [
        {"path": path, "mode": f"{mode:o}", "type": "blob", "sha": sha}
        for path, mode, _, sha in objects
    ]
    try:
        parent = await adapter.commit(action.local_parent_sha)
    except GitHubOperationalError:
        return await _mark_failed(session, action, "parent_read_failed")
    if parent is None:
        return await _mark(session, action, "CONFLICT", "parent_sha_mismatch")
    if parent.sha != action.local_parent_sha:
        return await _mark(session, action, "CONFLICT", "parent_sha_mismatch")
    try:
        remote_tree = await adapter.tree(action.local_tree_sha)
    except GitHubOperationalError:
        return await _mark_failed(session, action, "tree_read_failed")
    if remote_tree is not None and remote_tree.sha != action.local_tree_sha:
        return await _mark(session, action, "CONFLICT", "tree_sha_mismatch")
    if remote_tree is None:
        try:
            if (
                await adapter.create_tree(parent.tree_sha, entries, action.local_tree_sha)
                != action.local_tree_sha
            ):
                return await _mark(session, action, "CONFLICT", "tree_sha_mismatch")
        except GitHubOperationalError:
            return await _mark_failed(session, action, "tree_creation_failed")
    try:
        remote = await adapter.commit(action.local_commit_sha)
    except GitHubOperationalError:
        return await _mark_failed(session, action, "commit_read_failed")
    if remote is not None and remote.sha != action.local_commit_sha:
        return await _mark(session, action, "CONFLICT", "commit_sha_mismatch")
    if remote is None:
        try:
            remote = await adapter.create_commit(
                tree_sha=action.local_tree_sha,
                parent_sha=action.local_parent_sha,
                message=action.changeset_proof.get("message", ""),
                author=action.changeset_proof.get("author", ""),
                committer=action.changeset_proof.get("committer", ""),
                timestamp=int(action.changeset_proof.get("timestamp", 0)),
                sha=action.local_commit_sha,
            )
        except GitHubOperationalError:
            return await _mark_failed(session, action, "commit_creation_failed")
    commit_matches = (
        remote.sha == action.local_commit_sha
        and remote.tree_sha == action.local_tree_sha
        and remote.parent_sha == action.local_parent_sha
        and remote.message == action.changeset_proof.get("message", "")
        and remote.author == action.changeset_proof.get("author", "")
        and remote.committer == action.changeset_proof.get("committer", "")
        and remote.author_timestamp == int(action.changeset_proof.get("timestamp", 0))
        and remote.committer_timestamp == int(action.changeset_proof.get("timestamp", 0))
        and remote.author_timezone == 0
        and remote.committer_timezone == 0
    )
    if not commit_matches:
        return await _mark(session, action, "CONFLICT", "commit_sha_mismatch")
    try:
        current_base = (await adapter.base_ref(binding.base_branch)).sha
    except GitHubOperationalError:
        return await _mark_failed(session, action, "remote_base_read_failed")
    if current_base != action.prepared_remote_base_sha:
        return await _mark(session, action, "STALE", "stale_base")
    try:
        ref = await adapter.branch_ref(action.branch_ref)
    except GitHubOperationalError:
        return await _mark_failed(session, action, "branch_read_failed")
    if ref is None:
        try:
            ref = await adapter.create_branch(action.branch_ref, action.local_commit_sha)
        except GitHubOperationalError:
            try:
                ref = await adapter.branch_ref(action.branch_ref)
            except GitHubOperationalError:
                return await _mark_failed(session, action, "branch_creation_uncertain")
    if ref is None:
        return await _mark_failed(session, action, "branch_creation_uncertain")
    if ref.sha != action.local_commit_sha:
        return await _mark(session, action, "CONFLICT", "branch_conflict")
    try:
        pr = await adapter.find_pull_request(head=action.branch_ref, base=binding.base_branch)
    except GitHubOperationalError:
        return await _mark_failed(session, action, "pr_read_failed")
    if pr is None:
        try:
            pr = await adapter.create_pull_request(
                title=action.pr_title,
                body=action.pr_body,
                head=action.branch_ref,
                base=binding.base_branch,
            )
        except GitHubOperationalError:
            try:
                pr = await adapter.find_pull_request(
                    head=action.branch_ref, base=binding.base_branch
                )
            except GitHubOperationalError:
                return await _mark_failed(session, action, "pr_creation_uncertain")
    if pr is None:
        return await _mark_failed(session, action, "pr_creation_uncertain")
    if (
        pr.head_sha != action.local_commit_sha
        or pr.head_ref != action.branch_ref
        or pr.base_ref != binding.base_branch
        or pr.title != action.pr_title
        or pr.body != action.pr_body
    ):
        return await _mark(session, action, "CONFLICT", "pr_conflict")
    action.remote_tree_sha = action.local_tree_sha
    action.remote_commit_sha = remote.sha
    action.remote_ref_sha = ref.sha
    action.pr_number = pr.number
    action.pr_url = pr.url
    action.status = "PUBLISHED"
    action.published_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(action)
    return action


async def _mark(
    session: AsyncSession, action: GitHubPublicationAction, status: str, code: str
) -> GitHubPublicationAction:
    action.status = status
    action.failure_code = code
    await session.commit()
    raise _fail(code)


async def _mark_failed(
    session: AsyncSession, action: GitHubPublicationAction, code: str
) -> GitHubPublicationAction:
    action.status = "FAILED"
    action.failure_code = code
    await session.commit()
    raise _fail(code)
