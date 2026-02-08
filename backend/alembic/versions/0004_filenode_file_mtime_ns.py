"""Add filenode.file_mtime_ns.

Revision ID: 0004_filenode_file_mtime_ns
Revises: 0003_taskjob_idempotency_active_index
Create Date: 2025-02-06 00:00:02.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_filenode_file_mtime_ns"
down_revision = "0003_taskjob_idempotency_active_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "filenode",
        sa.Column("file_mtime_ns", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.execute("UPDATE filenode SET file_mtime_ns = CAST(file_mtime * 1e9 AS BIGINT)")


def downgrade() -> None:
    op.drop_column("filenode", "file_mtime_ns")
