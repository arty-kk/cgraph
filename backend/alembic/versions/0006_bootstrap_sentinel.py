from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_bootstrap_sentinel"
down_revision = "0005_organization_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bootstrapsentinel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_bootstrapsentinel_key"),
    )
    op.create_index(op.f("ix_bootstrapsentinel_key"), "bootstrapsentinel", ["key"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bootstrapsentinel_key"), table_name="bootstrapsentinel")
    op.drop_table("bootstrapsentinel")
