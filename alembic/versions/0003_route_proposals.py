"""Store suggested route edits and one support vote per browser."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("route_slug", sa.String(length=100), nullable=True),
        sa.Column("number", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("coordinates_json", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_route_proposals_city", "route_proposals", ["city"])
    op.create_index("ix_route_proposals_route_slug", "route_proposals", ["route_slug"])
    op.create_index("ix_route_proposals_status", "route_proposals", ["status"])
    op.create_table(
        "proposal_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("route_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voter_id", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("proposal_id", "voter_id", name="uq_proposal_voter"),
    )
    op.create_index("ix_proposal_votes_proposal_id", "proposal_votes", ["proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_proposal_votes_proposal_id", table_name="proposal_votes")
    op.drop_table("proposal_votes")
    op.drop_index("ix_route_proposals_status", table_name="route_proposals")
    op.drop_index("ix_route_proposals_route_slug", table_name="route_proposals")
    op.drop_index("ix_route_proposals_city", table_name="route_proposals")
    op.drop_table("route_proposals")
