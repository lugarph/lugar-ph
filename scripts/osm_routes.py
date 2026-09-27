"""Import jeepney lines from OpenStreetMap public-transport route relations.

A line mapped in OSM usually has one route relation per direction (PTv2), or
one relation for a loop. The relations are fetched from Overpass, their ways
joined end to end in member order, small breaks bridged with a driving route,
and the directions joined out and back into one circuit in riding order: the
shape the planner rides forward only.

Geometry built here is derived from OpenStreetMap, (c) OpenStreetMap
contributors, under the ODbL.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path


OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
USER_AGENT = "LugarPH/0.4 route network builder"
ATTRIBUTION = "© OpenStreetMap contributors, ODbL"
GAP_KM = 0.03  # ways closer than this are already joined
MAX_SEGMENT_KM = 0.4  # longer straight segments are split so stops can be placed along them
ANCHOR_REACH_KM = 0.4  # a planned landmark counts only if the mapped route passes this close
TERMINAL_CLEARANCE_KM = 0.5  # landmarks this close to a terminal repeat it

Point = list[float]  # [lng, lat]
Landmark = tuple[str, str, Point]  # (id, name, point)


def km(a: Point, b: Point) -> float:
    """Equirectangular distance between [lng, lat] points; exact enough at city scale."""
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 110.57)


def route_geometry_between(points: list[Point]) -> tuple[dict, float]:
    """A driving route through the points, from the public OSRM demo server."""
    coordinates = ";".join(f"{lng},{lat}" for lng, lat in points)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    request = urllib.request.Request(f"{OSRM_URL}{coordinates}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                route = json.load(response)["routes"][0]
            time.sleep(0.5)
            return route["geometry"], route["distance"] / 1000
        except OSError:  # the public demo server is often slow; back off and retry
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_relations(relation_ids: list[int]) -> dict[int, dict]:
    """Route relations with their member geometry, trying each public Overpass server."""
    query = f"[out:json][timeout:90];relation(id:{','.join(map(str, relation_ids))});out body geom;"
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt, url in enumerate([*OVERPASS_URLS, *OVERPASS_URLS]):
        try:
            request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                elements = {element["id"]: element for element in json.load(response)["elements"]}
            missing = set(relation_ids) - set(elements)
            if missing:
                raise RuntimeError(f"Overpass did not return relations {sorted(missing)}")
            return elements
        except OSError as exc:  # busy public servers answer 504/429; try the next mirror
            print(f"    Overpass {url} failed ({exc}); retrying", flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("All Overpass servers failed")


def join(points: list[Point], piece: list[Point]) -> list[Point]:
    """Append a piece of path, bridging a break with a driving route."""
    if not points:
        return list(piece)
    gap = km(points[-1], piece[0])
    if gap <= GAP_KM:
        return points + piece[1:]
    print(f"    bridging a {gap:.2f} km break", flush=True)
    bridge, _ = route_geometry_between([points[-1], piece[0]])
    return points + bridge["coordinates"][1:-1] + piece


def relation_path(relation: dict) -> list[Point]:
    """The relation's ways joined end to end in member order, each flipped to follow on."""
    ways = [
        [[point["lon"], point["lat"]] for point in member["geometry"]]
        for member in relation["members"]
        if member["type"] == "way" and member.get("role", "") in ("", "forward", "backward") and member.get("geometry")
    ]
    first = ways[0]
    if len(ways) > 1 and min(km(first[0], ways[1][0]), km(first[0], ways[1][-1])) < min(km(first[-1], ways[1][0]), km(first[-1], ways[1][-1])):
        first = first[::-1]
    points = list(first)
    for way in ways[1:]:
        if km(points[-1], way[-1]) < km(points[-1], way[0]):
            way = way[::-1]
        points = join(points, way)
    return points


def rotate_to(points: list[Point], target: Point) -> list[Point]:
    """Start a closed circuit at its point nearest the target, keeping the riding order."""
    start = min(range(len(points)), key=lambda index: km(points[index], target))
    return points[start:] + points[1 : start + 1]


def densify(points: list[Point]) -> list[Point]:
    """Split long straight segments so stops can be placed along them."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        parts = max(1, math.ceil(km(a, b) / MAX_SEGMENT_KM))
        out.extend([a[0] + (b[0] - a[0]) * step / parts, a[1] + (b[1] - a[1]) * step / parts] for step in range(1, parts + 1))
    return out


def circuit(relations: dict[int, dict], relation_ids: list[int], loop_start: Point | None = None, loop_far: Point | None = None) -> tuple[list[Point], int]:
    """The line as one closed path in riding order, and the index where it reaches the far terminal.

    Two relations are joined outbound then return; the far terminal is where
    the outbound one ends. A single loop relation may start anywhere, so it is
    rotated to loop_start, and its far terminal is the point nearest loop_far.
    """
    points: list[Point] = []
    far_point = loop_far
    for position, relation_id in enumerate(relation_ids):
        points = join(points, relation_path(relations[relation_id]))
        if position == 0 and len(relation_ids) > 1:
            far_point = points[-1]
    points = densify(join(points, [points[0]]))
    if loop_start is not None:
        points = rotate_to(points, loop_start)
    if far_point is None:  # a loop with no known far terminal: take its farthest point
        far_point = max(points, key=lambda point: km(point, points[0]))
    turnaround = min(range(len(points)), key=lambda index: km(points[index], far_point))
    return points, turnaround


def anchor(key: str, name: str, point: Point) -> dict:
    return {"id": key, "name": name, "lng": round(point[0], 6), "lat": round(point[1], 6)}


def _bare(name: str) -> str:
    """Letters and digits only, so "Hibaoan" and "Hibao-an" compare equal."""
    return "".join(char for char in name.lower() if char.isalnum())


def slug(text: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in text.lower()).strip("_")


def osm_anchors(points: list[Point], turnaround: int, landmarks: list[Landmark], start_name: str | None, far_name: str | None) -> tuple[list[dict], list[dict]]:
    """Terminals from the mapped route, plus the known landmarks it really passes, in riding order.

    Landmarks within reach of a terminal, or sharing its name, are dropped: the
    terminal already names that spot. Without both terminal names the line
    gets no anchors, since the planner reads the last anchor as the far
    terminal.
    """
    if not start_name or not far_name:
        return [], []
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + km(a, b))
    terminals = (points[0], points[turnaround])
    passed = []
    for key, name, target in landmarks:
        index = min(range(len(points)), key=lambda i: km(points[i], target))
        repeats_terminal = any(_bare(name) in _bare(terminal) or _bare(terminal) in _bare(name) for terminal in (start_name, far_name))
        if km(points[index], target) <= ANCHOR_REACH_KM and not repeats_terminal and all(km(target, point) > TERMINAL_CLEARANCE_KM for point in terminals):
            passed.append((cumulative[index], key, name, target))
    outbound = [anchor(key, name, target) for position, key, name, target in sorted(passed) if position < cumulative[turnaround]]
    inbound = [anchor(key, name, target) for position, key, name, target in sorted(passed) if position > cumulative[turnaround]]
    anchors = [anchor(slug(start_name), start_name, points[0]), *outbound, anchor(slug(far_name), far_name, points[turnaround])]
    return anchors, inbound


def osm_properties(relation_ids: list[int], points: list[Point], anchors: list[dict], return_anchors: list[dict]) -> dict:
    """Properties every OSM-imported line carries."""
    return {
        "mode": "jeepney",
        "status": "osm_route_relation",
        "distance_km": round(sum(km(a, b) for a, b in zip(points, points[1:])), 2),
        "source_url": f"https://www.openstreetmap.org/relation/{relation_ids[0]}",
        "osm_relations": relation_ids,
        "attribution": ATTRIBUTION,
        "anchors": anchors,
        "return_anchors": return_anchors,
    }


def overlay(path: Path, routes: dict[str, tuple[list[int], str | None, str | None]]) -> None:
    """Replace the listed lines in a city's GeoJSON with their OSM circuits, keeping every other line.

    Each line's existing anchors are reused as candidate landmarks.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    relations = fetch_relations([relation_id for ids, _, _ in routes.values() for relation_id in ids])
    for feature in data["features"]:
        properties = feature["properties"]
        if properties["id"] not in routes:
            continue
        relation_ids, start_name, far_name = routes[properties["id"]]
        print(f"{path.stem}: importing {properties['number']} {properties['name']} from OpenStreetMap", flush=True)
        points, turnaround = circuit(relations, relation_ids)
        known = [
            (item["id"], item["name"], [item["lng"], item["lat"]])
            for item in [*properties.get("anchors", []), *properties.get("return_anchors", [])]
            if "endpoint" not in item["name"]
        ]
        anchors, return_anchors = osm_anchors(points, turnaround, known, start_name, far_name)
        properties.update(osm_properties(relation_ids, points, anchors, return_anchors))
        feature["geometry"] = {"type": "LineString", "coordinates": [[round(lng, 6), round(lat, 6)] for lng, lat in points]}
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
