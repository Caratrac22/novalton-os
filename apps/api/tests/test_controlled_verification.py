"""Provider-free authority and integrity tests for the fixed I-044 command."""

import hashlib

import pytest
from pydantic import ValidationError

from novalton_api.infrastructure.verification_sandbox import (
    VerificationResult,
    VerificationSandboxError,
)
from novalton_api.modules.tools import verification
from novalton_api.modules.tools.contracts import ToolProposal
from novalton_api.modules.tools.executor import (
    TRUSTED_TOOL_REGISTRY,
    ToolExecutionError,
    WorkspaceRoot,
)


def proposal(**parameters):
    return {
        "call_key": "verification-1",
        "tool_name": "verify.backend_syntax",
        "arguments": {"command_id": "verify.backend_syntax", "parameters": parameters},
    }


@pytest.mark.parametrize(
    "field",
    [
        "executable",
        "argv",
        "cwd",
        "env",
        "shell",
        "timeout",
        "uid",
        "gid",
        "mount",
        "image",
        "namespace",
        "network",
        "database_url",
        "signal",
        "stdout",
        "stdin",
        "pty",
        "test_target",
        "PATH",
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
    ],
)
@pytest.mark.parametrize("location", ["parameters", "arguments", "request"])
def test_no_execution_authority_fields(field, location):
    value = proposal()
    target = (
        value["arguments"]["parameters"]
        if location == "parameters"
        else value["arguments"]
        if location == "arguments"
        else value
    )
    target[field] = "forbidden"
    with pytest.raises(ValidationError):
        ToolProposal.model_validate(value)


@pytest.mark.parametrize(
    "command",
    [
        "unknown",
        "verify.backend_tests",
        "sh",
        "/usr/bin/python",
        "../test.py",
        "-x",
        "test;id",
        "x&&id",
        "x|id",
        "`id`",
        "$(id)",
        ">out",
        "x\x00",
        "x\n",
        "x\r",
    ],
)
def test_command_catalog_is_closed(command):
    value = proposal()
    value["arguments"]["command_id"] = command
    with pytest.raises(ValidationError):
        ToolProposal.model_validate(value)


def test_registered_command_has_exact_authority():
    value = ToolProposal.model_validate(proposal())
    assert value.arguments.model_dump() == {"command_id": "verify.backend_syntax", "parameters": {}}
    registered = TRUSTED_TOOL_REGISTRY.get(value.tool_name)
    assert registered.definition.required_permission == "verify.backend_syntax"
    assert registered.definition.policy_action == "tool.verify.backend_syntax"
    assert registered.definition.side_effect_class == "READ_ONLY"


@pytest.fixture
def bound_workspace(tmp_path, monkeypatch):
    (tmp_path / "source.py").write_text("x = 1\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/index").write_bytes(b"staged-state")
    (tmp_path / "unrelated.txt").write_text("dirty-content")
    monkeypatch.setattr(verification, "WORKSPACE", tmp_path)
    return tmp_path


def result(**updates):
    data = {
        "run_id": "1" * 32,
        "state": "passed",
        "source_digest": "a" * 64,
        "stale_source": False,
        "population_empty": True,
        "scratch_destroyed": True,
        "snapshot_destroyed": True,
        "output_truncated": False,
        "checks": {},
        "verification": {
            "state": "passed",
            "checked_files": 1,
            "failed_files": 0,
            "diagnostics": [],
            "truncated": False,
            "exit_code": 0,
        },
    }
    return VerificationResult(**(data | updates))


def adapter(monkeypatch, value, action=None):
    class Adapter:
        def __init__(self, root):
            self.root = root

        def verify(self):
            if action:
                action(self.root)
            return value

    monkeypatch.setattr(verification, "VerificationSandboxAdapter", Adapter)


def test_verification_evidence_is_bounded_untrusted_and_readonly(bound_workspace, monkeypatch):
    adapter(monkeypatch, result())
    before = verification.protected_state(bound_workspace)
    evidence, durable = verification.execute(bound_workspace)
    assert evidence == durable
    assert evidence["authority"] == "UNTRUSTED_DATA"
    assert evidence["workspace_integrity"] == "unchanged"
    assert (
        evidence["command_fingerprint"] == hashlib.sha256(b"verify.backend_syntax:1:{}").hexdigest()
    )
    assert verification.protected_state(bound_workspace) == before


@pytest.mark.parametrize("path", ["source.py", ".git/index", "unrelated.txt"])
def test_unexpected_workspace_mutation_fails_closed(bound_workspace, monkeypatch, path):
    adapter(monkeypatch, result(), lambda root: (root / path).write_text("changed"))
    with pytest.raises(VerificationSandboxError, match="unexpected_workspace_mutation"):
        verification.execute(bound_workspace)


@pytest.mark.parametrize(
    "updates",
    [
        {"stale_source": True},
        {"population_empty": False},
        {"scratch_destroyed": False},
        {"snapshot_destroyed": False},
        {"state": "timeout"},
        {"state": "cancelled"},
    ],
)
def test_invalid_lifecycle_cannot_pass(bound_workspace, monkeypatch, updates):
    adapter(monkeypatch, result(**updates))
    with pytest.raises(VerificationSandboxError, match="verification_sandbox_failed"):
        verification.execute(bound_workspace)


def test_failed_syntax_is_evidence_for_correction(bound_workspace, monkeypatch):
    value = result(
        verification={
            "state": "failed",
            "checked_files": 1,
            "failed_files": 1,
            "diagnostics": [{"path": "apps/api/src/bad.py", "code": "python_syntax_invalid"}],
            "truncated": False,
            "exit_code": 1,
        }
    )
    adapter(monkeypatch, value)
    evidence, _ = verification.execute(bound_workspace)
    assert evidence["verification"]["state"] == "failed"
    assert evidence["authority"] == "UNTRUSTED_DATA"


def test_unbound_workspace_fails_without_ipc(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("unbound workspace reached IPC")

    monkeypatch.setattr(verification, "VerificationSandboxAdapter", forbidden)
    with pytest.raises(VerificationSandboxError, match="verification_workspace_not_bound"):
        verification.execute(tmp_path)


def test_transport_error_is_sanitized(bound_workspace, monkeypatch):
    def fail(_):
        raise VerificationSandboxError("postgresql://secret:credential@host/development")

    monkeypatch.setattr(verification, "VerificationSandboxAdapter", fail)
    tool = TRUSTED_TOOL_REGISTRY.get("verify.backend_syntax")
    with pytest.raises(ToolExecutionError, match="^verification_unavailable$"):
        tool.executor.execute(
            WorkspaceRoot.approved(bound_workspace),
            ToolProposal.model_validate(proposal()).arguments,
        )


@pytest.mark.parametrize(
    "output",
    [
        {"state": "passed", "checked_files": 0, "exit_code": 0},
        {"state": "passed", "checked_files": 1, "exit_code": 1},
        {"state": "passed", "checked_files": 1, "exit_code": 0, "env": "secret"},
        {
            "state": "failed",
            "checked_files": 1,
            "failed_files": 1,
            "exit_code": 1,
            "diagnostics": [{"path": "../../escape", "code": "python_syntax_invalid"}],
        },
    ],
)
def test_invalid_result_does_not_become_evidence(bound_workspace, monkeypatch, output):
    adapter(monkeypatch, result(verification=output))
    with pytest.raises((VerificationSandboxError, ValidationError)):
        verification.execute(bound_workspace)


@pytest.mark.parametrize(
    "code",
    [
        "verification_timeout",
        "verification_unavailable",
        "verification_source_missing",
        "verification_source_empty",
        "verification_source_bound",
        "verification_source_type",
    ],
)
def test_infrastructure_failure_does_not_authorize_a_repair(bound_workspace, monkeypatch, code):
    adapter(
        monkeypatch,
        result(
            verification={
                "state": "failed",
                "failure_code": code,
                "exit_code": None if code == "verification_timeout" else 1,
            }
        ),
    )
    with pytest.raises(VerificationSandboxError, match=code):
        verification.execute(bound_workspace)
