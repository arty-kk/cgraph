"""Add idempotency key to taskjob.

Revision ID: 0002_taskjob_idempotency_key
Revises: 0001_init
Create Date: 2025-02-06 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_taskjob_idempotency_key"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("taskjob", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_index(
        "ix_taskjob_idempotency_key",
        "taskjob",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_taskjob_org_idempotency_key",
        "taskjob",
        ["org_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_taskjob_org_idempotency_key",
        "taskjob",
        type_="unique",
    )
    op.drop_index("ix_taskjob_idempotency_key", table_name="taskjob")
    op.drop_column("taskjob", "idempotency_key")
