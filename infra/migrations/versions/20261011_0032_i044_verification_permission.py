"""Immutable Developer verification authority and bounded continuation accounting."""

from alembic import op
from sqlalchemy import text

revision = "20261011_0032"
down_revision = "20260902_0031"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_model_runs_recovery_attempt_index"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "model_runs", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "model_runs",
        "(recovery_attempt_kind = 'TOOL_CONTINUATION' AND recovery_attempt_index BETWEEN 0 AND 6) "
        "OR (recovery_attempt_kind <> 'TOOL_CONTINUATION' AND recovery_attempt_index BETWEEN 0 AND 1)",
    )
    op.execute("""
        INSERT INTO agent_definitions (
            id, tenant_id, workspace_id, name, slug, version, status, category,
            mission, capabilities, permissions, created_at, updated_at
        )
        SELECT md5(source.id::text || '-i044-developer-v4')::uuid,
            tenant_id, workspace_id, name, slug, 4, status, category, mission, capabilities,
            ARRAY['workspace.list_files', 'workspace.read_file', 'workspace.search_text',
                  'workspace.replace_text', 'verify.backend_syntax']::varchar[], now(), now()
        FROM agent_definitions source
        WHERE slug = 'developer_worker' AND version = 3
          AND permissions = ARRAY['workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text']::varchar[]
          AND NOT EXISTS (SELECT 1 FROM agent_definitions existing
              WHERE existing.tenant_id = source.tenant_id
                AND existing.workspace_id = source.workspace_id
                AND existing.slug = source.slug AND existing.version = 4)
    """)

    # Re-upgrade reactivates only the exact generated immutable successor.
    op.execute("""
        UPDATE agent_definitions target SET status = 'ENABLED', updated_at = now()
        FROM agent_definitions source
        WHERE source.slug = 'developer_worker' AND source.version = 3
          AND source.status = 'ENABLED'
          AND source.permissions = ARRAY['workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text']::varchar[]
          AND target.id = md5(source.id::text || '-i044-developer-v4')::uuid
          AND target.tenant_id = source.tenant_id AND target.workspace_id = source.workspace_id
          AND target.slug = source.slug AND target.version = 4 AND target.status = 'ARCHIVED'
          AND target.name = source.name AND target.mission = source.mission
          AND target.category = source.category AND target.capabilities = source.capabilities
          AND target.permissions = ARRAY['workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text', 'verify.backend_syntax']::varchar[]
    """)


def downgrade() -> None:
    # Never rewrite historical ModelRun ordinals to force an older schema.
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM model_runs WHERE recovery_attempt_index > 1)"
        )
    ):
        raise RuntimeError("i044_downgrade_has_continuation_history")
    op.drop_constraint(CONSTRAINT, "model_runs", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "model_runs", "recovery_attempt_index BETWEEN 0 AND 1"
    )
    op.execute("""
        UPDATE agent_definitions SET status = 'ARCHIVED', updated_at = now()
        WHERE slug = 'developer_worker' AND version = 4
          AND permissions = ARRAY['workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text', 'verify.backend_syntax']::varchar[]
    """)
