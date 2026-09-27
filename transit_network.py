"""Multi-city jeepney network matching with walking access and one transfer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
CITY_METADATA = {
    "bacolod": {"name": "Bacolod City", "center": [10.6825, 122.9545], "zoom": 13, "source_label": "Bacolod LPTRP", "source_url": "https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf"},
    "iloilo": {"name": "Iloilo City", "center": [10.7130, 122.5570], "zoom": 13, "source_label": "Iloilo LPTRP 2023", "source_url": "https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf"},
    "cebu": {"name": "Cebu City", "center": [10.3157, 123.8854], "zoom": 13, "source_label": "Cebu DOTC GTFS", "source_url": "https://www.transit.land/feeds/f-wcb4-cebu~dotc"},
    "tacloban": {"name": "Tacloban City", "center": [11.2440, 125.0000], "zoom": 13, "source_label": "Tacloban LPTRP 2024", "source_url": "https://tacloban.gov.ph/ordinance/page/5/"},
}
NETWORK_FILES = {
    "bacolod": DATA_DIR / "jeepney_network.geojson",
    "iloilo": DATA_DIR / "iloilo_jeepney_network.geojson",
    "cebu": DATA_DIR / "cebu_jeepney_network.geojson",
    "tacloban": DATA_DIR / "tacloban_jeepney_network.geojson",
}
NETWORKS = {city: json.loads(path.read_text(encoding="utf-8")) for city, path in NETWORK_FILES.items()}
NETWORK = NETWORKS["bacolod"]


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    radius = 6371.0
    dlat, dlng = radians(b_lat - a_lat), radians(b_lng - a_lng)
    value = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(value))


@dataclass(frozen=True)
class Line:
    city: str
    id: str
    number: str
    name: str
    color: str
    source_url: str | None
    status: str
    coordinates: tuple[tuple[float, float], ...]
    cumulative_km: tuple[float, ...]


def _line(city: str, feature: dict) -> Line:
    coordinates = tuple(tuple(point) for point in feature["geometry"]["coordinates"])
    cumulative = [0.0]
    for first, second in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + distance_km(first[1], first[0], second[1], second[0]))
    properties = feature["properties"]
    return Line(
        city=city, id=properties["id"], number=str(properties["number"]), name=properties["name"],
        color=properties["color"], source_url=properties.get("source_url") or CITY_METADATA[city]["source_url"], status=properties["status"],
        coordinates=coordinates, cumulative_km=tuple(cumulative),
    )


LINES_BY_CITY = {city: tuple(_line(city, feature) for feature in network["features"]) for city, network in NETWORKS.items()}
LINE_BY_ID = {line.id: line for lines in LINES_BY_CITY.values() for line in lines}


def _nearest(line: Line, lat: float, lng: float) -> tuple[float, int]:
    return min((distance_km(lat, lng, point[1], point[0]), index) for index, point in enumerate(line.coordinates))


def _sample_indexes(line: Line, limit: int = 90) -> range:
    return range(0, len(line.coordinates), max(1, len(line.coordinates) // limit))


@lru_cache(maxsize=4096)
def _transfer_between(first_id: str, second_id: str) -> tuple[float, int, int]:
    first, second = LINE_BY_ID[first_id], LINE_BY_ID[second_id]
    best = (float("inf"), 0, 0)
    second_indexes = tuple(_sample_indexes(second))
    for first_index in _sample_indexes(first):
        first_point = first.coordinates[first_index]
        for second_index in second_indexes:
            second_point = second.coordinates[second_index]
            distance = distance_km(first_point[1], first_point[0], second_point[1], second_point[0])
            if distance < best[0]:
                best = (distance, first_index, second_index)
    return best


def _slice(line: Line, start: int, end: int) -> list[tuple[float, float]]:
    return list(line.coordinates[start : end + 1]) if start <= end else list(reversed(line.coordinates[end : start + 1]))


def _ride_distance(line: Line, start: int, end: int) -> float:
    return abs(line.cumulative_km[end] - line.cumulative_km[start])


def _point_json(point: tuple[float, float], name: str) -> dict:
    return {"name": name, "lng": point[0], "lat": point[1]}


def _leg(line: Line, start: int, end: int) -> dict:
    return {
        "route_id": line.id, "route_number": line.number, "route_name": line.name, "color": line.color,
        "board_near": f"the nearest point on line {line.number}", "alight_near": f"the nearest point on line {line.number}",
        "geometry": {"type": "LineString", "coordinates": _slice(line, start, end)},
        "geometry_status": line.status, "road_distance_km": round(_ride_distance(line, start, end), 2),
    }


def _candidate_points(lines, lat: float, lng: float, max_walk_km: float = 0.75):
    candidates = []
    for line in lines:
        distance, index = _nearest(line, lat, lng)
        if distance <= max_walk_km:
            candidates.append((distance, line, index))
    return sorted(candidates, key=lambda item: item[0])


def _direct_candidates(start, end):
    end_by_id = {line.id: (walk, line, index) for walk, line, index in end}
    choices = []
    for start_walk, line, board_index in start:
        if line.id not in end_by_id:
            continue
        end_walk, _, alight_index = end_by_id[line.id]
        ride_km = _ride_distance(line, board_index, alight_index)
        if ride_km >= 0.25:
            choices.append({"score": ride_km + (start_walk + end_walk) * 2.2, "lines": [line], "indexes": [(board_index, alight_index)], "start_walk": start_walk, "end_walk": end_walk, "transfer_walk": 0.0, "transfer_points": []})
    return choices


def _transfer_candidates(start, end):
    choices = []
    for start_walk, first, board_index in start[:10]:
        for end_walk, second, alight_index in end[:10]:
            if first.id == second.id:
                continue
            transfer_walk, first_transfer, second_transfer = _transfer_between(first.id, second.id)
            if transfer_walk > 0.32:
                continue
            first_ride = _ride_distance(first, board_index, first_transfer)
            second_ride = _ride_distance(second, second_transfer, alight_index)
            if first_ride < 0.25 or second_ride < 0.25:
                continue
            choices.append({"score": first_ride + second_ride + (start_walk + end_walk) * 2.2 + transfer_walk * 3 + 2.0, "lines": [first, second], "indexes": [(board_index, first_transfer), (second_transfer, alight_index)], "start_walk": start_walk, "end_walk": end_walk, "transfer_walk": transfer_walk, "transfer_points": [first.coordinates[first_transfer], second.coordinates[second_transfer]]})
    return choices


def match_trip(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float, city: str = "bacolod") -> dict | None:
    if city not in LINES_BY_CITY or distance_km(origin_lat, origin_lng, destination_lat, destination_lng) < 0.25:
        return None
    start = _candidate_points(LINES_BY_CITY[city], origin_lat, origin_lng)
    end = _candidate_points(LINES_BY_CITY[city], destination_lat, destination_lng)
    if not start or not end:
        return None
    direct, transfers = _direct_candidates(start, end), _transfer_candidates(start, end)
    if not direct and not transfers:
        return None
    best_any = min(direct + transfers, key=lambda item: item["score"])
    best_direct = min(direct, key=lambda item: item["score"]) if direct else None
    choice = best_direct if best_direct and best_direct["score"] <= best_any["score"] * 1.3 else best_any
    legs = [_leg(line, *indexes) for line, indexes in zip(choice["lines"], choice["indexes"])]
    waypoints = [_point_json(legs[0]["geometry"]["coordinates"][0], f"Board line {choice['lines'][0].number}")]
    if len(legs) == 2:
        waypoints.extend([_point_json(choice["transfer_points"][0], f"Alight line {choice['lines'][0].number}"), _point_json(choice["transfer_points"][1], f"Board line {choice['lines'][1].number}")])
    waypoints.append(_point_json(legs[-1]["geometry"]["coordinates"][-1], f"Alight line {choice['lines'][-1].number}"))
    total_km = sum(leg["road_distance_km"] for leg in legs) + choice["start_walk"] + choice["end_walk"] + choice["transfer_walk"]
    return {
        "city": city, "ride_count": len(legs),
        "lines": [{"id": line.id, "number": line.number, "name": line.name, "color": line.color} for line in choice["lines"]],
        "legs": legs, "waypoints": waypoints,
        "transfer_points": [_point_json(point, "Walk between jeepney lines") for point in choice["transfer_points"]],
        "access": {"origin_walk_km": round(choice["start_walk"], 2), "destination_walk_km": round(choice["end_walk"], 2), "transfer_walk_km": round(choice["transfer_walk"], 2)},
        "geometry_type": "published_or_inferred_road_corridor", "road_distance_km": round(total_km, 2),
        "source_url": choice["lines"][0].source_url,
        "note": "Walk to the nearest mapped jeepney corridor. Confirm the signboard, direction, and current operation locally before boarding.",
    }


def public_network(city: str = "bacolod") -> dict:
    return NETWORKS[city]


def route_ids() -> set[str]:
    return set(LINE_BY_ID)
