from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_organization_slug"
down_revision = "0004_filenode_file_mtime_ns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("slug", sa.String(), nullable=True))
    op.create_index("uq_organization_slug", "organization", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_organization_slug", table_name="organization")
    op.drop_column("organization", "slug")
