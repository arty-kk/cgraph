"""add patch_blob_sha to analysisrun

Revision ID: 0009_analysisrun_patch_blob_sha
Revises: 0008_analysis_stage_telemetry_stop_reason
Create Date: 2026-03-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_analysisrun_patch_blob_sha"
down_revision = "0008_analysis_stage_telemetry_stop_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysisrun", sa.Column("patch_blob_sha", sa.String(), nullable=True))
    op.create_index("ix_analysisrun_patch_blob_sha", "analysisrun", ["patch_blob_sha"], unique=False)
    op.execute(
        """
        UPDATE analysisrun
        SET patch_blob_sha = NULLIF(result_json::jsonb #>> '{patch_unified_diff_meta,sha256}', '')
        WHERE patch_blob_sha IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_analysisrun_patch_blob_sha", table_name="analysisrun")
    op.drop_column("analysisrun", "patch_blob_sha")
