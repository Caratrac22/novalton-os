"""Bind signed external subjects to existing durable human operators."""

from alembic import op
from sqlalchemy import text

revision = "20261021_0038"
down_revision = "20261021_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE federated_operator_identities (
            user_id uuid PRIMARY KEY REFERENCES human_operators(id) ON DELETE RESTRICT,
            issuer varchar(512) NOT NULL,
            subject varchar(256) NOT NULL,
            active boolean NOT NULL,
            revoked_at timestamptz,
            CONSTRAINT uq_federated_operator_subject UNIQUE (issuer, subject),
            CONSTRAINT ck_federated_issuer CHECK (char_length(issuer) BETWEEN 1 AND 512),
            CONSTRAINT ck_federated_subject CHECK (char_length(subject) BETWEEN 1 AND 256),
            CONSTRAINT ck_federated_revocation CHECK
                ((active AND revoked_at IS NULL) OR (NOT active AND revoked_at IS NOT NULL))
        )
    """)


def downgrade() -> None:
    if op.get_bind().scalar(text("SELECT EXISTS (SELECT 1 FROM federated_operator_identities)")):
        raise RuntimeError("federated_operator_identity_downgrade_has_history")
    op.drop_table("federated_operator_identities")
