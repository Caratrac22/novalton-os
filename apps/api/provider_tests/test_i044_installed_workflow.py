"""CI-only real IPC acceptance. Requires the reviewed installed service and test DB."""

import asyncio
import os
import re
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
    from novalton_api.core.config import Settings, get_settings
    from novalton_api.core.database import verify_database_identity
    from novalton_api.infrastructure.verification_sandbox import (
        VerificationSandboxAdapter,
        VerificationSandboxError,
    )

    asyncio.run(verify_database_identity(Settings.from_environment()))
    # This legacy I-044 acceptance exercises governed execution, not SaaS login.
    # Its identity check above confines the fixture exemption to disposable PostgreSQL.
    monkeypatch.setenv("NOVALTON_TEST_LEGACY_API_AUTH_BYPASS", "true")
    get_settings.cache_clear()
    root = Path("/srv/novalton/workspace")
    assert root.is_dir() and not root.is_symlink()
    assert root.stat().st_uid == os.geteuid()
    # Fail at the actual adapter boundary, rather than reporting a stale
    # recent.json left by the preceding standalone containment acceptance.
    VerificationSandboxAdapter(root).health()
    original_verify = VerificationSandboxAdapter.verify

    def diagnostic_verify(adapter):
        try:
            return original_verify(adapter)
        except VerificationSandboxError as error:
            code = str(error)
            assert re.fullmatch(r"[a-z0-9_]{1,64}", code), "unsafe_adapter_error"
            print("installed_adapter_failure=" + code)
            raise

    monkeypatch.setattr(VerificationSandboxAdapter, "verify", diagnostic_verify)
    scope = asyncio.run(_seed())
    try:
        run_i044_verification_cycle(scope, root, monkeypatch, installed=True)
    finally:
        asyncio.run(_cleanup(scope))
        get_settings.cache_clear()
