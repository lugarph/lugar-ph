"""Keep current published route overlays and immutable revision history."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("route_slug", sa.String(length=100), nullable=False),
        sa.Column("feature_json", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("route_proposals.id"), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_route_revisions_city", "route_revisions", ["city"])
    op.create_index("ix_route_revisions_route_slug", "route_revisions", ["route_slug"])
    op.create_table(
        "route_publications",
        sa.Column("city", sa.String(length=40), primary_key=True),
        sa.Column("route_slug", sa.String(length=100), primary_key=True),
        sa.Column("feature_json", sa.Text(), nullable=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("route_revisions.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("route_publications")
    op.drop_index("ix_route_revisions_route_slug", table_name="route_revisions")
    op.drop_index("ix_route_revisions_city", table_name="route_revisions")
    op.drop_table("route_revisions")
