"""Persist explicitly enabled, scoped task dispatch and immutable attempt bindings."""

from alembic import op
from sqlalchemy import text

revision = "20261020_0033"
down_revision = "20261011_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_workspaces_id_tenant", "workspaces", ["id", "tenant_id"])
    op.create_unique_constraint(
        "uq_workflow_runs_dispatch_scope", "workflow_runs",
        ["id", "tenant_id", "workspace_id", "project_id", "task_id"],
    )
    op.execute("""
        CREATE TABLE dispatch_activations (
            workspace_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            enabled boolean NOT NULL,
            generation integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_dispatch_activation_scope UNIQUE (workspace_id, tenant_id),
            CONSTRAINT fk_dispatch_activation_workspace_scope
                FOREIGN KEY (workspace_id, tenant_id)
                REFERENCES workspaces (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT ck_dispatch_activation_generation CHECK (generation > 0)
        )
    """)
    op.execute("""
        CREATE TABLE task_dispatches (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            project_id uuid NOT NULL,
            task_id uuid NOT NULL,
            workflow_run_id uuid NOT NULL,
            request_key varchar(128) NOT NULL,
            input_fingerprint varchar(64) NOT NULL,
            priority integer NOT NULL,
            eligible_at timestamptz NOT NULL,
            deadline timestamptz NOT NULL,
            status varchar(24) NOT NULL,
            generation integer NOT NULL,
            attempt_count integer NOT NULL,
            max_attempts integer NOT NULL,
            model_call_count integer NOT NULL,
            max_model_calls integer NOT NULL,
            allow_unknown_cost boolean NOT NULL,
            owner uuid,
            lease_expires_at timestamptz,
            activation_generation integer,
            stop_reason varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_dispatch_request UNIQUE (tenant_id, workspace_id, request_key),
            CONSTRAINT uq_dispatch_workflow_binding UNIQUE (workflow_run_id),
            CONSTRAINT uq_dispatch_id_scope UNIQUE (id, tenant_id, workspace_id),
            CONSTRAINT uq_dispatch_id_workflow UNIQUE (id, workflow_run_id),
            CONSTRAINT fk_dispatch_activation_scope FOREIGN KEY (workspace_id, tenant_id)
                REFERENCES dispatch_activations (workspace_id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_dispatch_workflow_scope FOREIGN KEY
                (workflow_run_id, tenant_id, workspace_id, project_id, task_id)
                REFERENCES workflow_runs (id, tenant_id, workspace_id, project_id, task_id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_dispatch_status CHECK
                (status IN ('READY','LEASED','WAITING_HUMAN','BLOCKED','DONE','CANCELLED')),
            CONSTRAINT ck_dispatch_priority CHECK (priority BETWEEN -100 AND 100),
            CONSTRAINT ck_dispatch_request CHECK (request_key ~ '^[a-zA-Z0-9_.:-]{1,128}$'),
            CONSTRAINT ck_dispatch_fingerprint CHECK (input_fingerprint ~ '^[a-f0-9]{64}$'),
            CONSTRAINT ck_dispatch_attempt_budget CHECK
                (max_attempts BETWEEN 0 AND 64 AND attempt_count BETWEEN 0 AND max_attempts
                AND generation = attempt_count),
            CONSTRAINT ck_dispatch_model_budget CHECK
                (max_model_calls BETWEEN 0 AND 128
                AND model_call_count BETWEEN 0 AND max_model_calls),
            CONSTRAINT ck_dispatch_lease_shape CHECK
                ((status = 'LEASED' AND owner IS NOT NULL AND lease_expires_at IS NOT NULL
                AND activation_generation IS NOT NULL) OR (status <> 'LEASED'
                AND owner IS NULL AND lease_expires_at IS NULL)),
            CONSTRAINT ck_dispatch_stop_reason CHECK
                (stop_reason IS NULL OR stop_reason ~ '^[a-z][a-z0-9_]{0,63}$')
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_dispatch_active_task ON task_dispatches
        (tenant_id, workspace_id, task_id)
        WHERE status IN ('READY','LEASED','WAITING_HUMAN')
    """)
    op.execute("""
        CREATE INDEX ix_dispatch_claim ON task_dispatches
        (tenant_id, workspace_id, status, priority, eligible_at, id)
    """)
    op.execute("""
        CREATE TABLE dispatch_dependencies (
            dispatch_id uuid NOT NULL,
            prerequisite_id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            PRIMARY KEY (dispatch_id, prerequisite_id),
            CONSTRAINT ck_dispatch_dependency_not_self CHECK (dispatch_id <> prerequisite_id),
            CONSTRAINT fk_dispatch_dependency_scope FOREIGN KEY
                (dispatch_id, tenant_id, workspace_id)
                REFERENCES task_dispatches (id, tenant_id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT fk_dispatch_prerequisite_scope FOREIGN KEY
                (prerequisite_id, tenant_id, workspace_id)
                REFERENCES task_dispatches (id, tenant_id, workspace_id) ON DELETE RESTRICT
        )
    """)
    op.execute("""
        CREATE TABLE dispatch_attempts (
            id uuid PRIMARY KEY,
            dispatch_id uuid NOT NULL,
            workflow_run_id uuid NOT NULL,
            generation integer NOT NULL,
            owner uuid NOT NULL,
            started_at timestamptz NOT NULL,
            completed_at timestamptz,
            pre_status varchar(16) NOT NULL,
            post_status varchar(16),
            workflow_step_run_id uuid REFERENCES workflow_step_runs (id) ON DELETE RESTRICT,
            outcome varchar(24),
            reason_code varchar(64),
            CONSTRAINT uq_dispatch_attempt_generation UNIQUE (dispatch_id, generation),
            CONSTRAINT fk_dispatch_attempt_binding FOREIGN KEY (dispatch_id, workflow_run_id)
                REFERENCES task_dispatches (id, workflow_run_id) ON DELETE RESTRICT,
            CONSTRAINT ck_dispatch_attempt_generation CHECK (generation > 0),
            CONSTRAINT ck_dispatch_attempt_outcome CHECK
                (outcome IS NULL OR outcome IN ('READY','WAITING_HUMAN','BLOCKED','DONE','CANCELLED')),
            CONSTRAINT ck_dispatch_attempt_completion CHECK
                ((outcome IS NULL AND completed_at IS NULL) OR
                (outcome IS NOT NULL AND completed_at IS NOT NULL)),
            CONSTRAINT ck_dispatch_attempt_reason CHECK
                (reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]{0,63}$')
        )
    """)


def downgrade() -> None:
    if op.get_bind().scalar(text("SELECT EXISTS (SELECT 1 FROM task_dispatches)")):
        raise RuntimeError("durable_dispatch_downgrade_has_history")
    op.drop_table("dispatch_attempts")
    op.drop_table("dispatch_dependencies")
    op.drop_table("task_dispatches")
    op.drop_table("dispatch_activations")
    op.drop_constraint("uq_workflow_runs_dispatch_scope", "workflow_runs", type_="unique")
    op.drop_constraint("uq_workspaces_id_tenant", "workspaces", type_="unique")
