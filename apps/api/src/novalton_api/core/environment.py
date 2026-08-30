"""Explicit profile diagnostics for operational entry points."""

import asyncio
import sys

from novalton_api.core.config import Settings, SettingsError, database_name_from_url
from novalton_api.core.database import DatabaseIdentityError, verify_database_identity


def _present(value: object) -> str:
    return "present" if value else "unset"


def _report(settings: Settings, database_name: str) -> None:
    print(f"Environment: {settings.environment}")
    print(f"Database identity: {database_name}")
    print(f"Test database: {'YES' if database_name.endswith('_test') else 'NO'}")
    print(f"Provider configuration: {_present(settings.openai_compatible_base_url)}")
    print(f"Governed qualification: {_present(settings.governed_provider_qualifications)}")
    print(f"Forced router override: {_present(settings.model_router_force_model)}")


def main() -> int:
    """Validate the selected profile, optionally proving the live database identity."""
    if len(sys.argv) != 2 or sys.argv[1] not in {"validate", "db-check"}:
        print("Usage: python -m novalton_api.core.environment {validate|db-check}", file=sys.stderr)
        return 2
    try:
        settings = Settings.from_environment()
        database_name = database_name_from_url(settings.database_url)
        if sys.argv[1] == "db-check":
            database_name = asyncio.run(verify_database_identity(settings))
    except (SettingsError, DatabaseIdentityError):
        print(
            "ENVIRONMENT_BLOCKED: selected environment profile or database identity is invalid.",
            file=sys.stderr,
        )
        return 1
    _report(settings, database_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
