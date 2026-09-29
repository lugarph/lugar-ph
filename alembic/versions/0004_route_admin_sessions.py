"""Store revocable route reviewer sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_admin_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_index("ix_route_admin_sessions_expires_at", "route_admin_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_route_admin_sessions_expires_at", table_name="route_admin_sessions")
    op.drop_table("route_admin_sessions")
