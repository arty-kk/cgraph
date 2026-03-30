"""Add project graph counters and structured task error payload.

Revision ID: 0010_project_graph_counts_and_task_error_json
Revises: 0009_analysisrun_patch_blob_sha
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_project_graph_counts_and_task_error_json"
down_revision = "0009_analysisrun_patch_blob_sha"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column("graph_node_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "project",
        sa.Column("graph_edge_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("taskjob", sa.Column("error_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("taskjob", "error_json")
    op.drop_column("project", "graph_edge_count")
    op.drop_column("project", "graph_node_count")
