"""Establish the empty I-004 migration baseline.

Revision ID: 20260820_0001
Revises:
Create Date: 2026-08-20
"""

revision: str = "20260820_0001"
down_revision: None = None
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Establish migration history without application tables."""


def downgrade() -> None:
    """Remove the baseline migration marker."""
