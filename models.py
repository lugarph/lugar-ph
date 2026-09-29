"""Database models for routes that can replace the MVP's mock catalog."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not url:
        # Vercel's filesystem is read-only except /tmp, where notes last only as
        # long as the function instance. Set DATABASE_URL to keep them.
        return "sqlite:////tmp/lugar.db" if os.getenv("VERCEL") else "sqlite:///./lugar.db"
    # Hosted Postgres (Vercel, Neon, Heroku) hands out postgres:// URLs; use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url()


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    origin: Mapped[str] = mapped_column(String(160), nullable=False)
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    transit_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fare_php: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Future PostGIS integration: add a Geography(LineString, srid=4326)
    # column using geoalchemy2 and a GiST index. Query route proximity with
    # ST_DWithin and order candidate boarding points by walking distance.


class RouteComment(Base):
    __tablename__ = "route_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class RouteProposal(Base):
    __tablename__ = "route_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    route_slug: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    number: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    coordinates_json: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProposalVote(Base):
    __tablename__ = "proposal_votes"
    __table_args__ = (UniqueConstraint("proposal_id", "voter_id", name="uq_proposal_voter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("route_proposals.id", ondelete="CASCADE"), nullable=False, index=True)
    voter_id: Mapped[str] = mapped_column(String(64), nullable=False)


class RouteAdminSession(Base):
    __tablename__ = "route_admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

if os.getenv("VERCEL") and DATABASE_URL.startswith("sqlite:////tmp/"):
    # A fresh serverless instance has no migrated database; create the tables in place.
    Base.metadata.create_all(engine)
