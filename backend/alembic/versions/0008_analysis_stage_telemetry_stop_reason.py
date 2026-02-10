"""add stop_reason to analysis stage telemetry

Revision ID: 0008_analysis_stage_telemetry_stop_reason
Revises: 0007_analysis_stage_telemetry
Create Date: 2026-02-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_analysis_stage_telemetry_stop_reason"
down_revision = "0007_analysis_stage_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysisstagetelemetry", sa.Column("stop_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysisstagetelemetry", "stop_reason")
