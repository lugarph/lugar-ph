"""Small, rate-limited adapters for public OpenStreetMap services.

These endpoints are appropriate for a low-traffic MVP. A production deployment
should self-host or contract geocoding and pedestrian routing capacity.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "LugarPH/0.4 (local transit routing MVP)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FOOT_ROUTER_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/driving"

# Nominatim viewbox order: left, top, right, bottom.
CITY_VIEWBOXES = {
    "bacolod": (122.88, 10.75, 123.10, 10.56),
    "iloilo": (122.45, 10.82, 122.64, 10.63),
    "cebu": (123.78, 10.49, 124.04, 10.17),
    "tacloban": (124.88, 11.40, 125.10, 11.12),
}
class _PublicServiceClient:
    """Serialize requests per service and retain a small in-process cache."""

    def __init__(self, minimum_interval: float = 1.05, cache_size: int = 400):
        self.minimum_interval = minimum_interval
        self.cache_size = cache_size
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, Any] = OrderedDict()

    def get_json(self, url: str, cache_key: str) -> Any:
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

            delay = self.minimum_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=12) as response:
                    value = json.load(response)
            finally:
                self._last_request = time.monotonic()

            self._cache[cache_key] = value
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return value


_geocoder = _PublicServiceClient()
_foot_router = _PublicServiceClient()


def search_places(city: str, query: str) -> list[dict[str, Any]]:
    """Find deliberate, city-bounded search results without autocomplete."""

    normalized = " ".join(query.split())
    left, top, right, bottom = CITY_VIEWBOXES[city]
    params = urlencode(
        {
            # The viewbox already constrains the city. Appending comma-separated
            # locality text causes Nominatim to reject otherwise valid POIs.
            "q": normalized,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 6,
            "countrycodes": "ph",
            "viewbox": f"{left},{top},{right},{bottom}",
            "bounded": 1,
        }
    )
    payload = _geocoder.get_json(
        f"{NOMINATIM_URL}?{params}",
        f"{city}:{normalized.casefold()}",
    )
    results = []
    for item in payload:
        display_name = item.get("display_name", "")
        short_name = item.get("name") or display_name.split(",", 1)[0]
        if not short_name:
            continue
        results.append(
            {
                "name": short_name,
                "area": display_name,
                "lat": float(item["lat"]),
                "lng": float(item["lon"]),
                "type": item.get("type"),
            }
        )
    return results


def _bearing_word(degrees: float | None) -> str:
    if degrees is None:
        return "ahead"
    names = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
    return names[round(degrees / 45) % 8]


def _instruction(step: dict[str, Any]) -> str:
    maneuver = step.get("maneuver", {})
    action = maneuver.get("type", "continue")
    modifier = maneuver.get("modifier")
    street = step.get("name") or "the path"

    if action == "depart":
        return f"Head {_bearing_word(maneuver.get('bearing_after'))} toward {street}"
    if action == "arrive":
        return "Arrive at your walking destination"
    if action in {"turn", "end of road", "fork", "on ramp", "off ramp"}:
        direction = (modifier or "ahead").replace("slight ", "slightly ")
        return f"Turn {direction} onto {street}"
    if action in {"new name", "continue"}:
        direction = f" {modifier}" if modifier and modifier != "straight" else ""
        return f"Continue{direction} on {street}"
    if action == "roundabout":
        return f"Continue through the roundabout onto {street}"
    return f"Continue on {street}"


def _direct_distance_km(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(from_lat), math.radians(to_lat)
    dlat = lat2 - lat1
    dlng = math.radians(to_lng - from_lng)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def walking_route(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> dict[str, Any]:
    """Return a routed pedestrian leg, with a straight-line fallback."""

    direct_km = _direct_distance_km(from_lat, from_lng, to_lat, to_lng)
    if direct_km < 0.035:
        return {
            "distance_km": 0.0,
            "duration_minutes": 0,
            "geometry": {"type": "LineString", "coordinates": [[from_lng, from_lat], [to_lng, to_lat]]},
            "steps": [],
            "street_name": "",
            "routing_status": "already_there",
        }

    rounded = tuple(round(value, 5) for value in (from_lat, from_lng, to_lat, to_lng))
    coordinates = f"{from_lng},{from_lat};{to_lng},{to_lat}"
    params = urlencode({"overview": "full", "geometries": "geojson", "steps": "true"})
    try:
        payload = _foot_router.get_json(
            f"{FOOT_ROUTER_URL}/{coordinates}?{params}",
            ":".join(map(str, rounded)),
        )
        route = payload["routes"][0]
        steps = []
        street_name = ""
        for leg in route.get("legs", []):
            street_name = street_name or leg.get("summary", "")
            for step in leg.get("steps", []):
                if step.get("distance", 0) < 1 and step.get("maneuver", {}).get("type") != "arrive":
                    continue
                steps.append(
                    {
                        "instruction": _instruction(step),
                        "distance_m": round(step.get("distance", 0)),
                    }
                )
        return {
            "distance_km": round(route["distance"] / 1000, 2),
            "duration_minutes": max(1, round(route["duration"] / 60)),
            "geometry": route["geometry"],
            "steps": steps,
            "street_name": street_name,
            "routing_status": "routed",
        }
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        distance_km = round(direct_km * 1.2, 2)
        return {
            "distance_km": distance_km,
            "duration_minutes": max(1, round(distance_km / 4.8 * 60)),
            "geometry": {"type": "LineString", "coordinates": [[from_lng, from_lat], [to_lng, to_lat]]},
            "steps": [{"instruction": "Walk toward the jeepney corridor", "distance_m": round(distance_km * 1000)}],
            "street_name": "",
            "routing_status": "approximate",
        }
