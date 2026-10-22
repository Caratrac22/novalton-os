"""HTTP-level OIDC → Next → FastAPI → PostgreSQL acceptance on disposable test DB."""

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from sqlalchemy import delete
from test_development_workflow import QueueProvider, _manager, _qa, _worker
from test_durable_dispatch import db_call, enqueue, operator_for, other_task, snapshot, tick

from novalton_api.core.config import get_settings
from novalton_api.main import create_app
from novalton_api.modules.durable_dispatch import provisioning
from novalton_api.modules.durable_dispatch.identity import FederatedOperatorIdentity

pytest_plugins = ["test_durable_dispatch"]


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _until(path: Path, process: subprocess.Popen, *, timeout: float = 40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"OIDC integration process exited {process.returncode}: {stdout} {stderr}"
            )
        time.sleep(0.1)
    raise AssertionError(f"OIDC integration handshake timed out: {path.name}")


def test_local_oidc_console_and_real_api_workflow(scope, monkeypatch, tmp_path):
    """Only the IdP and model are local test doubles; web/API/DB are real services."""
    repo = Path(__file__).resolve().parents[3]
    assert (repo / "apps/web/.next/BUILD_ID").exists(), "CI must build the web application"
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    finished, _, _ = enqueue(scope, provider, max_attempts=3, max_model_calls=3)
    assert [tick(scope, provider).outcome.value for _ in range(3)] == [
        "STEP_COMPLETED",
        "STEP_COMPLETED",
        "WORKFLOW_COMPLETED",
    ]
    pending, _, _ = enqueue(other_task(scope), QueueProvider([]), max_attempts=3)

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host="127.0.0.1", port=_port(), log_level="error", access_log=False
        )
    )
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    deadline = time.monotonic() + 15
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "FastAPI did not start with the disposable database profile"
    script = repo / "apps/web/scripts/operator-oidc-smoke.mjs"
    env = {
        **os.environ,
        "NOVALTON_SMOKE_API_BASE_URL": f"http://127.0.0.1:{server.config.port}",
        "NOVALTON_SMOKE_HANDSHAKE_DIR": str(tmp_path),
        "NOVALTON_SMOKE_TENANT_ID": str(scope.tenant_id),
        "NOVALTON_SMOKE_WORKSPACE_ID": str(scope.workspace_id),
        "NOVALTON_SMOKE_DISPATCH_ID": str(finished.id),
        "NOVALTON_SMOKE_CANCEL_ID": str(pending.id),
        "NOVALTON_SMOKE_WORKFLOW_ID": str(finished.workflow_run_id),
    }
    process = subprocess.Popen(
        ["node", str(script)],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    bound = False
    try:
        _until(tmp_path / "issuer.json", process)
        metadata = json.loads((tmp_path / "issuer.json").read_text())
        monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_ISSUER", metadata["issuer"])
        monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_AUDIENCE", "operator-test")
        monkeypatch.setenv("NOVALTON_OPERATOR_OIDC_PUBLIC_KEY_PEM", metadata["publicKey"])
        monkeypatch.delenv("NOVALTON_OPERATOR_OIDC_JWKS_URI", raising=False)
        get_settings.cache_clear()
        actor = operator_for(scope)
        db_call(
            lambda session: provisioning.bind_federated_subject(
                session,
                operator=actor,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                subject_id=actor.user_id,
                issuer=metadata["issuer"],
                subject="human-123",
            )
        )
        bound = True
        (tmp_path / "ready").touch()
        _until(tmp_path / "waiting-for-revocation", process)
        assert snapshot(scope, pending.id)[0].status == "CANCELLED"
        assert snapshot(scope, finished.id)[0].status == "DONE"
        assert len(snapshot(scope, finished.id)[2]) == 3
        db_call(
            lambda session: provisioning.revoke_federated_subject(
                session,
                operator=actor,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                subject_id=actor.user_id,
            )
        )
        (tmp_path / "revoked").touch()
        stdout, stderr = process.communicate(timeout=45)
        assert process.returncode == 0, (stdout, stderr)
        assert json.loads(stdout.strip())["backend"] == "FastAPI/PostgreSQL"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        server.should_exit = True
        worker.join(timeout=10)
        if bound:

            async def remove(session):
                await session.execute(
                    delete(FederatedOperatorIdentity).where(
                        FederatedOperatorIdentity.user_id == operator_for(scope).user_id
                    )
                )
                await session.commit()

            db_call(remove)
        get_settings.cache_clear()
