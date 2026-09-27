"""Add community comments tied to published LPTRP line IDs."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_slug", sa.String(length=80), nullable=False),
        sa.Column("author", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_route_comments_route_slug", "route_comments", ["route_slug"])


def downgrade() -> None:
    op.drop_index("ix_route_comments_route_slug", table_name="route_comments")
    op.drop_table("route_comments")
