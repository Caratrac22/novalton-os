"""Persist bounded safe QA human-review summaries.

Revision ID: 20260901_0029
Revises: 20260831_0028
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0029"
down_revision: str | None = "20260831_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_challenge_resolutions",
        sa.Column(
            "safe_review_summary",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_agent_challenge_resolutions_review_role",
        "agent_challenge_resolutions",
        "safe_review_summary IS NULL OR specialization_role = 'qa_worker'",
    )
    op.create_check_constraint(
        "ck_agent_challenge_resolutions_review_shape",
        "agent_challenge_resolutions",
        "safe_review_summary IS NULL OR "
        "(jsonb_typeof(safe_review_summary) = 'object' "
        "AND octet_length(safe_review_summary::text) <= 524288)",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_agent_challenge_review_summary_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.safe_review_summary IS DISTINCT FROM OLD.safe_review_summary THEN
                RAISE EXCEPTION 'safe human review summary is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_challenge_review_summary_immutable
        BEFORE UPDATE OF safe_review_summary ON agent_challenge_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_agent_challenge_review_summary_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_agent_challenge_review_summary_immutable "
        "ON agent_challenge_resolutions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_agent_challenge_review_summary_update()"
    )
    op.drop_constraint(
        "ck_agent_challenge_resolutions_review_shape",
        "agent_challenge_resolutions",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_challenge_resolutions_review_role",
        "agent_challenge_resolutions",
        type_="check",
    )
    op.drop_column("agent_challenge_resolutions", "safe_review_summary")
