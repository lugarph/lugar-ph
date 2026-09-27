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
from osm_services import search_places, walking_matrix, walking_route
from route_catalog import ROUTE_BY_ID, distance_km, public_catalog
from transit_network import CITY_METADATA, plan_trips, public_network, trip_help


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Lugar.ph", version="0.3.0")
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


def _known_city(city: str) -> str:
    city = city.lower().strip()
    if city not in CITY_METADATA:
        raise HTTPException(status_code=404, detail="Unknown city")
    return city


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


@app.get("/api/cities")
def cities():
    return {"cities": [{"id": city, **metadata} for city, metadata in CITY_METADATA.items()]}


@app.get("/api/places")
def places(q: str = Query(min_length=2, max_length=120), city: str = "bacolod"):
    """Explicit city-bounded place search through OpenStreetMap Nominatim."""
    city = _known_city(city)
    try:
        return {"results": search_places(city, q)}
    except (OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Place search is temporarily unavailable")


@app.get("/api/walking-route")
def walking_directions(
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lng: float = Query(ge=-180, le=180),
):
    """Pedestrian directions from a pin to a mapped jeepney corridor."""
    return walking_route(from_lat, from_lng, to_lat, to_lng)


@app.get("/api/jeepney-routes")
def jeepney_routes(city: str = "bacolod"):
    """Published or documented jeepney routes for one supported city."""
    return public_catalog(_known_city(city))


@app.get("/api/jeepney-network", response_class=JSONResponse)
def jeepney_network(city: str = "bacolod"):
    """Road-aligned GeoJSON for a supported city's jeepney corridors."""
    city = _known_city(city)
    return JSONResponse(
        content=public_network(city),
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
    city: str = "bacolod",
):
    """Suggest mapped jeepney connections (up to three rides) plus distinct alternatives."""
    city = _known_city(city)
    straight_km = distance_km(origin_lat, origin_lng, destination_lat, destination_lng)
    itineraries = plan_trips(origin_lat, origin_lng, destination_lat, destination_lng, city, walk_matrix=walking_matrix)
    road_km = itineraries[0]["road_distance_km"] if itineraries else max(0.6, straight_km * 1.35)

    # Future PostGIS integration: store surveyed route geometries, query near
    # both endpoints, and compute exact access, ride, and transfer legs.
    return {
        "city": city,
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "destination": {"lat": destination_lat, "lng": destination_lng},
        "distance_km": round(road_km, 1),
        "jeepney_notice": None if itineraries else "No mapped jeepney connection was found within walking distance of both pins. Try moving a pin closer to a colored corridor or check the jeepney route map.",
        "no_route": None if itineraries else trip_help(origin_lat, origin_lng, destination_lat, destination_lng, city),
        "estimate_note": (
            "Walking links connect your pins to the nearest mapped corridors. Signboards, direction, current service, time, and fare need local confirmation."
            if itineraries else
            "Lugar.ph currently recommends jeepney routes only. Mapped coverage and active service still need local confirmation."
        ),
        "fare_note": FARE_NOTE,
        "options": [_jeepney_option(itinerary, index) for index, itinerary in enumerate(itineraries)],
    }


FARE_NOTE = "Estimated LTFRB regular fare (₱14 for the first 4 km, ₱2 per km after). Students, seniors, and PWDs pay 20% less."


def _jeepney_option(itinerary: dict, index: int) -> dict:
    access = itinerary["access"]
    rides = itinerary["ride_count"]
    if rides == 1:
        description = f"Walk {round((access['origin_walk_km'] + access['destination_walk_km']) * 1000)} m total, then take one jeepney"
    else:
        transfers = "once" if rides == 2 else f"{rides - 1} times"
        description = f"Take {rides} jeepneys and transfer {transfers} ({round(access['transfer_walk_km'] * 1000)} m between lines)"
    return {
        "id": "jeepney" if index == 0 else f"jeepney-alt-{index}",
        "mode": "jeepney",
        "label": "Jeepney",
        "recommended": index == 0,
        "highlight": itinerary["highlight"],
        "tags": itinerary["tags"],
        "compared_to_best": itinerary["compared_to_best"],
        "fare_php": itinerary["fare_php"],
        "duration_minutes": itinerary["duration_minutes"],
        "ride_duration_minutes": itinerary["ride_minutes"],
        "ride_distance_km": itinerary["ride_km"],
        "walk_distance_km": itinerary["walk_km"],
        "distance_km": itinerary["road_distance_km"],
        "description": description,
        "lines": itinerary["lines"],
        "itinerary": itinerary,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
