"""Idempotently seed the published LPTRP route names into the Route table."""

from sqlalchemy import select

from models import Route, SessionLocal
from route_catalog import ROUTES


def endpoints(name: str) -> tuple[str, str]:
    parts = name.removesuffix(" Loop").split(" – ")
    origin = parts[0]
    destination = parts[-1].split(" via ")[0]
    return origin, destination


def seed_routes() -> int:
    with SessionLocal.begin() as session:
        existing = set(session.scalars(select(Route.name)).all())
        added = 0
        for _, _, name, _ in ROUTES:
            if name in existing:
                continue
            origin, destination = endpoints(name)
            session.add(
                Route(
                    name=name,
                    origin=origin,
                    destination=destination,
                    transit_mode="jeepney",
                )
            )
            added += 1
        return added


if __name__ == "__main__":
    print(f"Seeded {seed_routes()} published jeepney routes")
