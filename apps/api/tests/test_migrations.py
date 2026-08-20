from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_configuration_loads_baseline_revision() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    head = scripts.get_current_head()
    revision = scripts.get_revision(head)

    assert head == "20260820_0001"
    assert revision is not None
    assert revision.down_revision is None
