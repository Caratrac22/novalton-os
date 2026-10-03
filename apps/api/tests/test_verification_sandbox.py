import inspect
import json
from pathlib import Path

import pytest

from novalton_api.infrastructure import verification_sandbox as sandbox


def test_source_view_excludes_sensitive_and_generated_content(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("print('data only')\n")
    for name in (".env", ".env.test", ".git", ".venv", "node_modules"):
        path = tmp_path / name
        if name in {".env", ".env.test"}:
            path.write_text("not-admitted")
        else:
            path.mkdir()
            (path / "secret").write_text("not-admitted")
    assert sandbox.source_digest(tmp_path) == sandbox._digest_files(
        [(sandbox.PurePosixPath("source.py"), tmp_path / "source.py")]
    )


def test_source_view_rejects_symlinks_and_special_files(tmp_path: Path) -> None:
    (tmp_path / "target").write_text("fixture")
    (tmp_path / "link").symlink_to("target")
    with pytest.raises(sandbox.VerificationSandboxError, match="source_symlink_denied"):
        sandbox.source_digest(tmp_path)


def test_source_digest_detects_live_workspace_change(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("before\n")
    before = sandbox.source_digest(tmp_path)
    source.write_text("after\n")
    assert sandbox.source_digest(tmp_path) != before


def test_adapter_marks_result_stale_without_sending_source_authority(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("before\n")
    prepared_digest = sandbox.source_digest(tmp_path)
    requests: list[dict[str, str]] = []

    class FakeAdapter(sandbox.VerificationSandboxAdapter):
        def health(self) -> dict[str, object]:
            return {}

        def _request(self, request: dict[str, str]) -> dict[str, object]:
            requests.append(request)
            if request["op"] == "prepare":
                return {
                    "capability": "c" * 64,
                    "source_digest": prepared_digest,
                    "state": "prepared",
                }
            if request["op"] == "verify":
                source.write_text("changed\n")
                return {"run_id": "a" * 32, "state": "accepted"}
            return {
                "run_id": "a" * 32,
                "state": "passed",
                "source_digest": prepared_digest,
                "population_empty": True,
                "scratch_destroyed": True,
                "snapshot_destroyed": True,
                "output_truncated": False,
                "checks": dict.fromkeys(sandbox._PROBE_CHECKS, True),
            }

    result = FakeAdapter(tmp_path).verify()
    assert result.state == "stale_source" and result.stale_source is True
    assert requests[0] == {"op": "prepare"}
    assert requests[1] == {"op": "verify", "capability": "c" * 64}
    assert all("source_digest" not in request for request in requests)


def test_client_transport_sends_json_only(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[dict[str, str]] = []

    class SocketProxy:
        response = b'{"state":"ready"}\n'

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def settimeout(self, _: float) -> None:
            pass

        def connect(self, _: str) -> None:
            pass

        def sendall(self, message: bytes) -> None:
            received.append(json.loads(message))

        def recv(self, size: int) -> bytes:
            response, self.response = self.response[:size], self.response[size:]
            return response

    monkeypatch.setattr(sandbox.socket, "socket", lambda *_: SocketProxy())
    adapter = object.__new__(sandbox.VerificationSandboxAdapter)
    assert adapter._request({"op": "health"}) == {"state": "ready"}
    assert received == [{"op": "health"}]
    assert "source_fd" not in inspect.signature(adapter._request).parameters


def test_public_action_has_no_execution_parameters() -> None:
    signature = inspect.signature(sandbox.VerificationSandboxAdapter.verify)
    assert list(signature.parameters) == ["self"]


def test_health_pins_definition_foundation_release_and_db_mode(tmp_path: Path) -> None:
    adapter = sandbox.VerificationSandboxAdapter(tmp_path)
    adapter._request = lambda request: {  # type: ignore[method-assign]
        "state": "ready",
        "definition": "wrong",
        "foundation_input_sha256": sandbox._FOUNDATION_INPUT_SHA256,
        "foundation_installed_manifest_sha256": "a" * 64,
        "i044a_input_sha256": sandbox._I044A_INPUT_SHA256,
        "installed_manifest_sha256": "b" * 64,
        "db_mode": False,
    }
    with pytest.raises(sandbox.VerificationSandboxError, match="sandbox_definition_mismatch"):
        adapter.health()
