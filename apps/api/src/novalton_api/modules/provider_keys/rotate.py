"""Host-only, transactional key rotation. Keep old key available until backups rotate."""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import Database, verify_database_identity
from novalton_api.modules.provider_keys.models import ProviderKey
from novalton_api.modules.provider_keys.vault import Keyring


async def rotate_records(session: AsyncSession, keyring: Keyring) -> int:
    rows = (
        await session.scalars(select(ProviderKey).order_by(ProviderKey.id).with_for_update())
    ).all()
    for row in rows:
        plaintext = keyring.decrypt(
            row.key_id,
            row.nonce,
            row.ciphertext,
            owner=row.owner_id,
            tenant=row.tenant_id,
            workspace=row.workspace_id,
            provider=row.provider,
        )
        row.key_id, row.nonce, row.ciphertext = keyring.encrypt(
            plaintext,
            owner=row.owner_id,
            tenant=row.tenant_id,
            workspace=row.workspace_id,
            provider=row.provider,
        )
    return len(rows)


async def run() -> int:
    settings = get_settings()
    await verify_database_identity(settings)
    ring = Keyring.from_environment()
    db = Database.from_settings(settings)
    try:
        async with db.session_factory.begin() as session:
            return await rotate_records(session, ring)
    finally:
        await db.dispose()


def main() -> int:
    if not sys.stdin.isatty() or input("Rotate all provider keys? Type ROTATE: ") != "ROTATE":
        print("Local confirmation required", file=sys.stderr)
        return 1
    try:
        count = asyncio.run(run())
    except Exception:
        print("Rotation failed; transaction rolled back", file=sys.stderr)
        return 1
    print(f"Re-encrypted {count} credential records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
