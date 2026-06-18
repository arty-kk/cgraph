"""Link project to its originating task job for idempotent snapshot import.

Revision ID: 0011_project_task_job_id
Revises: 0010_project_graph_counts_and_task_error_json
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_project_task_job_id"
down_revision = "0010_project_graph_counts_and_task_error_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project", sa.Column("task_job_id", sa.String(), nullable=True))
    op.create_index(
        "uq_project_task_job_id",
        "project",
        ["task_job_id"],
        unique=True,
        postgresql_where=sa.text("task_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_task_job_id", table_name="project")
    op.drop_column("project", "task_job_id")
