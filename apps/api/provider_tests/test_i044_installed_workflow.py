"""CI-only real IPC acceptance. Requires the reviewed installed service and test DB."""

import asyncio
import os
from pathlib import Path

from test_development_workflow import _cleanup, _seed, run_i044_verification_cycle


def test_installed_governed_verify_correct_verify(monkeypatch):
    assert os.geteuid() != 0
    assert os.environ.get("NOVALTON_ENV") == "test"
    assert os.environ.get("NOVALTON_I044_INSTALLED_ACCEPTANCE") == "1"
    assert not any(
        os.environ.get(name)
        for name in (
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "OPENAI_API_KEY",
            "SSH_AUTH_SOCK",
            "HTTP_PROXY",
            "HTTPS_PROXY",
        )
    )
    from novalton_api.core.config import Settings
    from novalton_api.core.database import verify_database_identity

    asyncio.run(verify_database_identity(Settings.from_environment()))
    root = Path("/srv/novalton/workspace")
    assert root.is_dir() and not root.is_symlink()
    assert root.stat().st_uid == os.geteuid()
    scope = asyncio.run(_seed())
    try:
        run_i044_verification_cycle(scope, root, monkeypatch, installed=True)
    finally:
        asyncio.run(_cleanup(scope))
