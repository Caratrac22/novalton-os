from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_configuration_loads_i007_after_i006() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    head = scripts.get_current_head()
    revision = scripts.get_revision(head)
    baseline = scripts.get_revision("20260820_0001")

    assert head == "20260820_0004"
    assert revision is not None
    assert revision.down_revision == "20260820_0003"
    assert baseline is not None
    assert baseline.down_revision is None


def test_postgres_migration_downgrades_to_i006_and_reupgrades() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")

    command.upgrade(config, "head")
    try:
        command.downgrade(config, "20260820_0003")
    finally:
        command.upgrade(config, "head")
