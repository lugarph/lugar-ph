"""Lugar.ph MVP: Bacolod transit route previews."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from route_catalog import distance_km, match_jeepney, public_catalog


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Lugar.ph", version="0.1.0")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/jeepney-routes")
def jeepney_routes():
    """The 24 routes in Bacolod's published Local Public Transport Route Plan."""
    return public_catalog()


@app.get("/api/routes")
def routes(
    origin_lat: float = Query(10.6765, ge=-90, le=90),
    origin_lng: float = Query(122.9509, ge=-180, le=180),
    destination_lat: float = Query(10.6922, ge=-90, le=90),
    destination_lng: float = Query(122.9569, ge=-180, le=180),
):
    """Suggest only landmark connections backed by published Bacolod routes."""
    straight_km = distance_km(origin_lat, origin_lng, destination_lat, destination_lng)
    itinerary = match_jeepney(origin_lat, origin_lng, destination_lat, destination_lng)
    road_km = itinerary["road_distance_km"] if itinerary else max(0.6, straight_km * 1.35)
    options = []

    if itinerary:
        # The line and landmark connection are researched. This time is only a
        # rough MVP estimate because active stops, headways, and service direction
        # are not surveyed. The stored road trace is inferred from LPTRP anchors.
        jeepney_minutes = max(12, round(road_km / 13 * 60 + 8 + 10 * (itinerary["ride_count"] - 1)))
        options.append(
            {
                "id": "jeepney",
                "mode": "jeepney",
                "label": "Jeepney",
                "fare_php": None,  # No verified current fare matrix for these trip legs.
                "duration_minutes": jeepney_minutes,
                "description": (
                    "One researched jeepney connection"
                    if itinerary["ride_count"] == 1
                    else "Two researched lines with a transfer near SM City Bacolod"
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
        "jeepney_notice": None if itinerary else "No verified jeepney connection for these areas yet. Walk if practical, or ask locally whether a tricycle is available.",
        "estimate_note": (
            "Road trace is inferred from the route map and OpenStreetMap. Boarding points, service direction, time, and fare need local confirmation."
            if itinerary else
            "Walking time is approximate. Tricycle service and fare are unconfirmed; agree on a fare before boarding."
        ),
        "options": options,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
