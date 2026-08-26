"""Persist contract-enforcement policy and safe execution diagnostics for I-051.

Revision ID: 20260826_0018
Revises: 20260825_0017
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0018"
down_revision: str | None = "20260825_0017"
branch_labels = None
depends_on = None

_GRADES = "'UNSUPPORTED', 'BEST_EFFORT', 'PROVIDER_ENFORCED', 'STRICT_SCHEMA_GUARANTEED'"


def upgrade() -> None:
    op.add_column(
        "model_definitions",
        sa.Column("contract_enforcement_grade", sa.String(32), nullable=False, server_default="UNSUPPORTED"),
    )
    op.add_column(
        "model_definitions",
        sa.Column("enforcement_metadata_source", sa.String(64), nullable=False, server_default="catalog_unknown"),
    )
    op.execute(
        "UPDATE model_definitions SET contract_enforcement_grade = "
        "CASE WHEN structured_output IS TRUE THEN 'BEST_EFFORT' ELSE 'UNSUPPORTED' END, "
        "enforcement_metadata_source = CASE WHEN structured_output IS TRUE "
        "THEN 'catalog_structured_output_capability' ELSE 'catalog_unknown' END"
    )
    op.create_check_constraint(
        "ck_model_definitions_contract_enforcement_grade",
        "model_definitions",
        f"contract_enforcement_grade IN ({_GRADES})",
    )
    op.create_check_constraint(
        "ck_model_definitions_enforcement_metadata_source_length",
        "model_definitions",
        "char_length(enforcement_metadata_source) BETWEEN 1 AND 64",
    )
    for name, column in (
        ("target_structured_output_capability", sa.Column("target_structured_output_capability", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("contract_enforcement_grade", sa.Column("contract_enforcement_grade", sa.String(32), nullable=False, server_default="UNSUPPORTED")),
        ("minimum_contract_enforcement_grade", sa.Column("minimum_contract_enforcement_grade", sa.String(32), nullable=False, server_default="UNSUPPORTED")),
        ("enforcement_metadata_source", sa.Column("enforcement_metadata_source", sa.String(64), nullable=True)),
        ("contract_strategy_tier", sa.Column("contract_strategy_tier", sa.String(32), nullable=True)),
        ("contract_fingerprint", sa.Column("contract_fingerprint", sa.String(64), nullable=True)),
        ("contextual_constraint_count", sa.Column("contextual_constraint_count", sa.Integer(), nullable=True)),
        ("execution_max_output_tokens", sa.Column("execution_max_output_tokens", sa.Integer(), nullable=True)),
        ("output_budget_source", sa.Column("output_budget_source", sa.String(64), nullable=True)),
        ("finish_reason", sa.Column("finish_reason", sa.String(128), nullable=True)),
        ("truncation_classification", sa.Column("truncation_classification", sa.String(32), nullable=False, server_default="NONE")),
        ("recovery_attempt_kind", sa.Column("recovery_attempt_kind", sa.String(32), nullable=False, server_default="INITIAL")),
        ("recovery_attempt_index", sa.Column("recovery_attempt_index", sa.Integer(), nullable=False, server_default="0")),
    ):
        del name
        op.add_column("model_runs", column)
    op.create_check_constraint("ck_model_runs_contract_enforcement_grade", "model_runs", f"contract_enforcement_grade IN ({_GRADES})")
    op.create_check_constraint("ck_model_runs_minimum_contract_enforcement_grade", "model_runs", f"minimum_contract_enforcement_grade IN ({_GRADES})")
    op.create_check_constraint("ck_model_runs_contract_strategy_tier", "model_runs", "contract_strategy_tier IS NULL OR contract_strategy_tier IN ('STRICT_SCHEMA', 'JSON_OBJECT', 'JSON_INSTRUCTION')")
    op.create_check_constraint("ck_model_runs_truncation_classification", "model_runs", "truncation_classification IN ('NONE', 'TOKEN_LIMIT', 'OTHER')")
    op.create_check_constraint("ck_model_runs_recovery_attempt_kind", "model_runs", "recovery_attempt_kind IN ('INITIAL', 'TRUNCATION', 'CONTRACT_REPAIR')")
    op.create_check_constraint("ck_model_runs_recovery_attempt_index", "model_runs", "recovery_attempt_index BETWEEN 0 AND 1")
    op.create_check_constraint("ck_model_runs_enforcement_metadata_source_length", "model_runs", "enforcement_metadata_source IS NULL OR char_length(enforcement_metadata_source) BETWEEN 1 AND 64")
    op.create_check_constraint("ck_model_runs_contract_fingerprint_format", "model_runs", "contract_fingerprint IS NULL OR contract_fingerprint ~ '^[a-f0-9]{8,64}$'")
    op.create_check_constraint("ck_model_runs_contextual_constraint_count", "model_runs", "contextual_constraint_count IS NULL OR contextual_constraint_count BETWEEN 0 AND 16")
    op.create_check_constraint("ck_model_runs_execution_max_output_tokens", "model_runs", "execution_max_output_tokens IS NULL OR execution_max_output_tokens BETWEEN 1 AND 65536")
    op.create_check_constraint("ck_model_runs_output_budget_source_length", "model_runs", "output_budget_source IS NULL OR char_length(output_budget_source) BETWEEN 1 AND 64")
    op.create_check_constraint("ck_model_runs_finish_reason_length", "model_runs", "finish_reason IS NULL OR char_length(finish_reason) BETWEEN 1 AND 128")


def downgrade() -> None:
    for name in (
        "ck_model_runs_finish_reason_length",
        "ck_model_runs_output_budget_source_length",
        "ck_model_runs_execution_max_output_tokens",
        "ck_model_runs_contextual_constraint_count",
        "ck_model_runs_contract_fingerprint_format",
        "ck_model_runs_enforcement_metadata_source_length",
        "ck_model_runs_recovery_attempt_index",
        "ck_model_runs_recovery_attempt_kind",
        "ck_model_runs_truncation_classification",
        "ck_model_runs_contract_strategy_tier",
        "ck_model_runs_minimum_contract_enforcement_grade",
        "ck_model_runs_contract_enforcement_grade",
    ):
        op.execute(f"ALTER TABLE model_runs DROP CONSTRAINT IF EXISTS {name}")
    for name in (
        "recovery_attempt_index", "recovery_attempt_kind", "truncation_classification",
        "finish_reason", "output_budget_source", "execution_max_output_tokens",
        "contextual_constraint_count", "contract_fingerprint", "contract_strategy_tier",
        "enforcement_metadata_source", "minimum_contract_enforcement_grade",
        "contract_enforcement_grade", "target_structured_output_capability",
    ):
        op.drop_column("model_runs", name)
    op.drop_constraint("ck_model_definitions_enforcement_metadata_source_length", "model_definitions", type_="check")
    op.drop_constraint("ck_model_definitions_contract_enforcement_grade", "model_definitions", type_="check")
    op.drop_column("model_definitions", "enforcement_metadata_source")
    op.drop_column("model_definitions", "contract_enforcement_grade")
