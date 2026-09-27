"""Route-network matching for inferred Bacolod jeepney corridors.

The network is derived from the published LPTRP schematic's named anchors and
OSM roads. It supports a walking access leg, one jeepney, or two jeepneys with
one short walking transfer. It does not claim surveyed stops or live service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


NETWORK_FILE = Path(__file__).resolve().parent / "data" / "jeepney_network.geojson"
NETWORK = json.loads(NETWORK_FILE.read_text(encoding="utf-8"))


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    radius = 6371.0
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    value = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(value))


@dataclass(frozen=True)
class Line:
    id: str
    number: int
    name: str
    color: str
    coordinates: tuple[tuple[float, float], ...]
    cumulative_km: tuple[float, ...]


def _line(feature: dict) -> Line:
    coordinates = tuple(tuple(point) for point in feature["geometry"]["coordinates"])
    cumulative = [0.0]
    for first, second in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + distance_km(first[1], first[0], second[1], second[0]))
    properties = feature["properties"]
    return Line(
        id=properties["id"], number=properties["number"], name=properties["name"],
        color=properties["color"], coordinates=coordinates, cumulative_km=tuple(cumulative),
    )


LINES = tuple(_line(feature) for feature in NETWORK["features"])
LINE_BY_ID = {line.id: line for line in LINES}


def _nearest(line: Line, lat: float, lng: float) -> tuple[float, int]:
    return min(
        (distance_km(lat, lng, point[1], point[0]), index)
        for index, point in enumerate(line.coordinates)
    )


def _sample_indexes(line: Line, limit: int = 130) -> range:
    return range(0, len(line.coordinates), max(1, len(line.coordinates) // limit))


def _transfer(first: Line, second: Line) -> tuple[float, int, int]:
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


TRANSFERS = {
    (first.id, second.id): _transfer(first, second)
    for first_index, first in enumerate(LINES)
    for second in LINES[first_index + 1 :]
}


def _transfer_between(first: Line, second: Line) -> tuple[float, int, int]:
    if (first.id, second.id) in TRANSFERS:
        return TRANSFERS[(first.id, second.id)]
    distance, second_index, first_index = TRANSFERS[(second.id, first.id)]
    return distance, first_index, second_index


def _slice(line: Line, start: int, end: int) -> list[tuple[float, float]]:
    if start <= end:
        return list(line.coordinates[start : end + 1])
    return list(reversed(line.coordinates[end : start + 1]))


def _ride_distance(line: Line, start: int, end: int) -> float:
    return abs(line.cumulative_km[end] - line.cumulative_km[start])


def _point_json(point: tuple[float, float], name: str) -> dict:
    return {"name": name, "lng": point[0], "lat": point[1]}


def _leg(line: Line, start: int, end: int) -> dict:
    geometry = _slice(line, start, end)
    return {
        "route_id": line.id,
        "route_number": line.number,
        "route_name": line.name,
        "color": line.color,
        "board_near": f"the nearest point on line {line.number}",
        "alight_near": f"the nearest point on line {line.number}",
        "geometry": {"type": "LineString", "coordinates": geometry},
        "geometry_status": "inferred_from_lptrp_anchors",
        "road_distance_km": round(_ride_distance(line, start, end), 2),
    }


def _candidate_points(lat: float, lng: float, max_walk_km: float = 0.75) -> list[tuple[float, Line, int]]:
    candidates = []
    for line in LINES:
        distance, index = _nearest(line, lat, lng)
        if distance <= max_walk_km:
            candidates.append((distance, line, index))
    return sorted(candidates, key=lambda item: item[0])


def _direct_candidates(start, end) -> list[dict]:
    end_by_id = {line.id: (walk, line, index) for walk, line, index in end}
    choices = []
    for start_walk, line, board_index in start:
        if line.id not in end_by_id:
            continue
        end_walk, _, alight_index = end_by_id[line.id]
        ride_km = _ride_distance(line, board_index, alight_index)
        if ride_km < 0.25:
            continue
        choices.append({
            "score": ride_km + (start_walk + end_walk) * 2.2,
            "lines": [line], "indexes": [(board_index, alight_index)],
            "start_walk": start_walk, "end_walk": end_walk,
            "transfer_walk": 0.0, "transfer_points": [],
        })
    return choices


def _transfer_candidates(start, end) -> list[dict]:
    choices = []
    for start_walk, first, board_index in start[:10]:
        for end_walk, second, alight_index in end[:10]:
            if first.id == second.id:
                continue
            transfer_walk, first_transfer, second_transfer = _transfer_between(first, second)
            if transfer_walk > 0.32:
                continue
            first_ride = _ride_distance(first, board_index, first_transfer)
            second_ride = _ride_distance(second, second_transfer, alight_index)
            if first_ride < 0.25 or second_ride < 0.25:
                continue
            choices.append({
                "score": first_ride + second_ride + (start_walk + end_walk) * 2.2 + transfer_walk * 3 + 2.0,
                "lines": [first, second],
                "indexes": [(board_index, first_transfer), (second_transfer, alight_index)],
                "start_walk": start_walk, "end_walk": end_walk,
                "transfer_walk": transfer_walk,
                "transfer_points": [first.coordinates[first_transfer], second.coordinates[second_transfer]],
            })
    return choices


def match_trip(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float) -> dict | None:
    if distance_km(origin_lat, origin_lng, destination_lat, destination_lng) < 0.25:
        return None
    start = _candidate_points(origin_lat, origin_lng)
    end = _candidate_points(destination_lat, destination_lng)
    if not start or not end:
        return None

    direct = _direct_candidates(start, end)
    transfers = _transfer_candidates(start, end)
    choices = direct + transfers
    if not choices:
        return None
    # Prefer a direct ride when it is within 30% of the best transfer score.
    best_any = min(choices, key=lambda item: item["score"])
    best_direct = min(direct, key=lambda item: item["score"]) if direct else None
    choice = best_direct if best_direct and best_direct["score"] <= best_any["score"] * 1.3 else best_any

    legs = [_leg(line, *indexes) for line, indexes in zip(choice["lines"], choice["indexes"])]
    board_point = legs[0]["geometry"]["coordinates"][0]
    alight_point = legs[-1]["geometry"]["coordinates"][-1]
    waypoints = [_point_json(board_point, f"Board line {choice['lines'][0].number}")]
    if len(legs) == 2:
        waypoints.extend([
            _point_json(choice["transfer_points"][0], f"Alight line {choice['lines'][0].number}"),
            _point_json(choice["transfer_points"][1], f"Board line {choice['lines'][1].number}"),
        ])
    waypoints.append(_point_json(alight_point, f"Alight line {choice['lines'][-1].number}"))

    total_ride_km = sum(leg["road_distance_km"] for leg in legs)
    total_km = total_ride_km + choice["start_walk"] + choice["end_walk"] + choice["transfer_walk"]
    return {
        "ride_count": len(legs),
        "lines": [
            {"id": line.id, "number": line.number, "name": line.name, "color": line.color}
            for line in choice["lines"]
        ],
        "legs": legs,
        "waypoints": waypoints,
        "transfer_points": [
            _point_json(point, "Walk between jeepney lines") for point in choice["transfer_points"]
        ],
        "access": {
            "origin_walk_km": round(choice["start_walk"], 2),
            "destination_walk_km": round(choice["end_walk"], 2),
            "transfer_walk_km": round(choice["transfer_walk"], 2),
        },
        "geometry_type": "inferred_osm_corridor",
        "road_distance_km": round(total_km, 2),
        "note": "Walk to the nearest mapped jeepney corridor. Lines are inferred from LPTRP landmarks and OSM roads; confirm the signboard and direction locally.",
    }


def public_network() -> dict:
    return NETWORK
