"""Lugar.ph MVP: Bacolod transit route previews."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from time import monotonic

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select

from models import RouteComment, SessionLocal
from route_catalog import ROUTE_BY_ID, distance_km, match_jeepney, public_catalog
from transit_network import public_network


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Lugar.ph", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
_comment_times: dict[str, float] = {}
_comment_lock = Lock()


class CommentInput(BaseModel):
    author: str = Field(min_length=2, max_length=40)
    body: str = Field(min_length=10, max_length=600)
    website: str = ""  # Quiet honeypot for simple automated form submissions.


def _known_line(route_slug: str) -> None:
    if route_slug not in ROUTE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown jeepney line")


def _comment_json(comment: RouteComment) -> dict:
    return {
        "id": comment.id,
        "route_slug": comment.route_slug,
        "author": comment.author,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
    }

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/jeepney-routes")
def jeepney_routes():
    """The 24 routes in Bacolod's published Local Public Transport Route Plan."""
    return public_catalog()


@app.get("/api/jeepney-network", response_class=JSONResponse)
def jeepney_network():
    """Road-aligned GeoJSON for all 24 inferred LPTRP corridors."""
    return JSONResponse(
        content=public_network(),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/jeepney-routes/{route_slug}/comments")
def route_comments(route_slug: str):
    _known_line(route_slug)
    with SessionLocal() as session:
        comments = session.scalars(
            select(RouteComment)
            .where(RouteComment.route_slug == route_slug)
            .order_by(RouteComment.created_at.desc(), RouteComment.id.desc())
            .limit(50)
        ).all()
        return {"comments": [_comment_json(comment) for comment in comments]}


@app.post("/api/jeepney-routes/{route_slug}/comments", status_code=201)
def add_route_comment(route_slug: str, payload: CommentInput, request: Request):
    _known_line(route_slug)
    if payload.website:
        raise HTTPException(status_code=422, detail="Invalid comment")
    author = " ".join(payload.author.split())
    body = " ".join(payload.body.split())
    if len(author) < 2 or len(body) < 10:
        raise HTTPException(status_code=422, detail="Please enter a name and a useful comment")
    client = request.client.host if request.client else "unknown"
    now = monotonic()
    with _comment_lock:
        if now - _comment_times.get(client, 0) < 20:
            raise HTTPException(status_code=429, detail="Please wait before commenting again")
        _comment_times[client] = now
        if len(_comment_times) > 1000:
            _comment_times.clear()
    with SessionLocal() as session:
        comment = RouteComment(route_slug=route_slug, author=author, body=body)
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return _comment_json(comment)


@app.get("/api/routes")
def routes(
    origin_lat: float = Query(10.6765, ge=-90, le=90),
    origin_lng: float = Query(122.9509, ge=-180, le=180),
    destination_lat: float = Query(10.6922, ge=-90, le=90),
    destination_lng: float = Query(122.9569, ge=-180, le=180),
):
    """Suggest mapped jeepney connections with walking access and one transfer."""
    straight_km = distance_km(origin_lat, origin_lng, destination_lat, destination_lng)
    itinerary = match_jeepney(origin_lat, origin_lng, destination_lat, destination_lng)
    road_km = itinerary["road_distance_km"] if itinerary else max(0.6, straight_km * 1.35)
    options = []

    if itinerary:
        access = itinerary.get("access", {})
        walking_km = sum(access.values())
        ride_km = max(0, road_km - walking_km)
        jeepney_minutes = max(8, round(ride_km / 12 * 60 + walking_km / 4.8 * 60 + 6 + 8 * (itinerary["ride_count"] - 1)))
        options.append(
            {
                "id": "jeepney",
                "mode": "jeepney",
                "label": "Jeepney",
                "fare_php": None,  # No verified current fare matrix for these trip legs.
                "duration_minutes": jeepney_minutes,
                "description": (
                    f"Walk {round((access.get('origin_walk_km', 0) + access.get('destination_walk_km', 0)) * 1000)} m total, then take one jeepney"
                    if itinerary["ride_count"] == 1
                    else f"Walk to the first line, then transfer once ({round(access.get('transfer_walk_km', 0) * 1000)} m between lines)"
                ),
                "lines": itinerary["lines"],
                "itinerary": itinerary,
            }
        )

    # Future PostGIS integration: store surveyed route geometries, query near
    # both endpoints, and compute exact access, ride, and transfer legs.
    if not itinerary:
        tricycle_minutes = max(8, round(road_km / 18 * 60 + 3))
        walk_minutes = max(8, round(road_km / 4.8 * 60))
        options.extend([
            {
                "id": "walk",
                "mode": "walk",
                "label": "Walk",
                "fare_php": 0,
                "duration_minutes": walk_minutes,
                "description": "Walk if practical; check crossings and street conditions.",
                "lines": [],
            },
            {
                "id": "tricycle",
                "mode": "tricycle",
                "label": "Tricycle (if available)",
                "fare_php": None,  # No verified local fare for this origin/destination.
                "duration_minutes": tricycle_minutes,
                "availability": "unconfirmed",
                "description": "Optional local ride. Availability varies and it can be costly; agree on a fare before boarding.",
                "lines": [],
            },
        ])
    return {
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "destination": {"lat": destination_lat, "lng": destination_lng},
        "distance_km": round(road_km, 1),
        "jeepney_notice": None if itinerary else "This preview has no mapped jeepney connection for these places yet. That does not mean no jeepney serves them. Check the route map or ask locally; walk if practical, or ask about tricycles.",
        "estimate_note": (
            "Walking links connect your pins to the nearest mapped corridors. Route geometry is inferred from LPTRP landmarks and OpenStreetMap; signboards, direction, service, time, and fare need local confirmation."
            if itinerary else
            "Walking time is approximate. Tricycle service and fare are unconfirmed; agree on a fare before boarding."
        ),
        "options": options,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
