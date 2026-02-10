from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_analysis_stage_telemetry"
down_revision = "0006_bootstrap_sentinel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysisstagetelemetry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage_name", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retry_index", sa.Integer(), nullable=False),
        sa.Column("self_check_result", sa.String(), nullable=True),
        sa.Column("failure_class", sa.String(), nullable=True),
        sa.Column("tool_calls", sa.Integer(), nullable=True),
        sa.Column("tool_output_chars", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysisstagetelemetry_run_id"), "analysisstagetelemetry", ["run_id"])
    op.create_index(op.f("ix_analysisstagetelemetry_org_id"), "analysisstagetelemetry", ["org_id"])
    op.create_index(
        op.f("ix_analysisstagetelemetry_project_id"),
        "analysisstagetelemetry",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_analysisstagetelemetry_stage_name"),
        "analysisstagetelemetry",
        ["stage_name"],
    )
    op.create_index(
        op.f("ix_analysisstagetelemetry_created_at"),
        "analysisstagetelemetry",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_analysisstagetelemetry_created_at"), table_name="analysisstagetelemetry")
    op.drop_index(op.f("ix_analysisstagetelemetry_stage_name"), table_name="analysisstagetelemetry")
    op.drop_index(op.f("ix_analysisstagetelemetry_project_id"), table_name="analysisstagetelemetry")
    op.drop_index(op.f("ix_analysisstagetelemetry_org_id"), table_name="analysisstagetelemetry")
    op.drop_index(op.f("ix_analysisstagetelemetry_run_id"), table_name="analysisstagetelemetry")
    op.drop_table("analysisstagetelemetry")
