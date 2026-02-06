"""Allow taskjob idempotency key reuse after completion.

Revision ID: 0003_taskjob_idempotency_active_index
Revises: 0002_taskjob_idempotency_key
Create Date: 2025-02-06 00:00:01.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_taskjob_idempotency_active_index"
down_revision = "0002_taskjob_idempotency_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_taskjob_org_idempotency_key",
        "taskjob",
        type_="unique",
    )
    op.create_index(
        "uq_taskjob_org_idempotency_key_active",
        "taskjob",
        ["org_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_taskjob_org_idempotency_key_active", table_name="taskjob")
    op.create_unique_constraint(
        "uq_taskjob_org_idempotency_key",
        "taskjob",
        ["org_id", "idempotency_key"],
    )
