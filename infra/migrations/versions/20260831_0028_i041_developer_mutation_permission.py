"""Create immutable Developer Worker v3 definitions with mutation permission."""

from alembic import op

revision = "20260831_0028"
down_revision = "20260831_0027"
branch_labels = None
depends_on = None

_MISSION = (
    "Execute one bounded software-development assignment and return a validated "
    "implementation result; workspace mutation remains server-owned and requires Policy "
    "plus explicit human approval."
)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO agent_definitions (
            id, tenant_id, workspace_id, name, slug, version, status, category,
            mission, capabilities, permissions, created_at, updated_at
        )
        SELECT
            md5(source.id::text || '-i041-developer-v3')::uuid,
            source.tenant_id,
            source.workspace_id,
            source.name,
            source.slug,
            3,
            source.status,
            source.category,
            '{_MISSION}',
            source.capabilities,
            ARRAY[
                'workspace.list_files', 'workspace.read_file',
                'workspace.search_text', 'workspace.replace_text'
            ]::varchar[],
            now(),
            now()
        FROM agent_definitions AS source
        WHERE source.slug = 'developer_worker'
          AND source.version = 2
          AND NOT EXISTS (
              SELECT 1
              FROM agent_definitions AS existing
              WHERE existing.tenant_id = source.tenant_id
                AND existing.workspace_id = source.workspace_id
                AND existing.slug = source.slug
                AND existing.version = 3
          )
        """
    )
    op.execute(
        """
        UPDATE agent_definitions AS retained
        SET status = source.status,
            updated_at = now()
        FROM agent_definitions AS source
        WHERE retained.tenant_id = source.tenant_id
          AND retained.workspace_id = source.workspace_id
          AND retained.slug = 'developer_worker'
          AND retained.version = 3
          AND retained.mission = :mission
          AND retained.permissions = ARRAY[
              'workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text'
          ]::varchar[]
          AND source.slug = 'developer_worker'
          AND source.version = 2
        """.replace(":mission", "'" + _MISSION.replace("'", "''") + "'")
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE agent_definitions
        SET status = 'ARCHIVED', updated_at = now()
        WHERE slug = 'developer_worker'
          AND version = 3
          AND mission = :mission
          AND permissions = ARRAY[
              'workspace.list_files', 'workspace.read_file',
              'workspace.search_text', 'workspace.replace_text'
          ]::varchar[]
        """.replace(":mission", "'" + _MISSION.replace("'", "''") + "'")
    )
