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

import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


# Driving routers tried in order: set LUGAR_OSRM_URL to put your own OSRM
# server (for example one built with a jeepney profile) ahead of the public ones.
ROUTERS = tuple(url for url in (
    os.environ.get("LUGAR_OSRM_URL"),
    "https://routing.openstreetmap.de/routed-car/route/v1/driving/",
    "https://router.project-osrm.org/route/v1/driving/",
) if url)
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
OSM_API = "https://api.openstreetmap.org/api/0.6"
USER_AGENT = "LugarPH/0.4 route network builder"
ATTRIBUTION = "© OpenStreetMap contributors, ODbL"
GAP_KM = 0.03  # ways closer than this are already joined
MAX_SEGMENT_KM = 0.4  # longer straight segments are split so stops can be placed along them
ANCHOR_REACH_KM = 0.4  # a planned landmark counts only if the mapped route passes this close
TERMINAL_CLEARANCE_KM = 0.5  # landmarks this close to a terminal repeat it

# Member roles for the road a route drives. Baguio mappers mark stretches where
# riders flag jeeps down anywhere as hail_and_ride.
WAY_ROLES = ("", "forward", "backward", "hail_and_ride")

Point = list[float]  # [lng, lat]
Landmark = tuple[str, str, Point]  # (id, name, point)


def km(a: Point, b: Point) -> float:
    """Equirectangular distance between [lng, lat] points; exact enough at city scale."""
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 110.57)


def route_path(points: list[Point]) -> list[Point]:
    """A driving path through the points, cached in scripts/.cache so reruns only ask for what changed."""
    key = hashlib.sha1(json.dumps([[round(lng, 6), round(lat, 6)] for lng, lat in points]).encode()).hexdigest()
    cache = CACHE_DIR / "osrm" / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    coordinates = ";".join(f"{lng},{lat}" for lng, lat in points)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    last_error: Exception | None = None
    for attempt in range(3):
        for router in ROUTERS:
            try:
                request = urllib.request.Request(f"{router}{coordinates}?{query}", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    path = json.load(response)["routes"][0]["geometry"]["coordinates"]
                time.sleep(1.1)  # the public servers ask for at most one request a second
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(path))
                return path
            except OSError as exc:  # the public servers are often slow or down; try the next one
                last_error = exc
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"No router answered: {last_error}")


def route_geometry_between(points: list[Point]) -> tuple[dict, float]:
    """A driving route through the points, and its length in km."""
    path = route_path(points)
    return {"type": "LineString", "coordinates": path}, sum(km(a, b) for a, b in zip(path, path[1:]))


def fetch_relations(relation_ids: list[int]) -> dict[int, dict]:
    """Route relations with their member geometry, cached in scripts/.cache/relations.

    Delete a relation's cache file to pick up edits made in OpenStreetMap since.
    """
    cache = CACHE_DIR / "relations"
    found = {relation_id: json.loads((cache / f"{relation_id}.json").read_text()) for relation_id in relation_ids if (cache / f"{relation_id}.json").exists()}
    missing = [relation_id for relation_id in relation_ids if relation_id not in found]
    if missing:
        fetched = _fetch_relations(missing)
        cache.mkdir(parents=True, exist_ok=True)
        for relation_id, relation in fetched.items():
            (cache / f"{relation_id}.json").write_text(json.dumps(relation))
        found.update(fetched)
    return found


def _fetch_relations(relation_ids: list[int]) -> dict[int, dict]:
    """Route relations with their member geometry, trying each public Overpass server, then the OSM API."""
    query = f"[out:json][timeout:90];relation(id:{','.join(map(str, relation_ids))});out body geom;"
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt, url in enumerate(OVERPASS_URLS):
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
    print("    Overpass unavailable; reading the relations from the OpenStreetMap API instead", flush=True)
    return {relation_id: _relation_from_api(relation_id) for relation_id in relation_ids}


def _relation_from_api(relation_id: int) -> dict:
    """One relation in Overpass's `out body geom` shape, from the main OSM API's /full call."""
    request = urllib.request.Request(f"{OSM_API}/relation/{relation_id}/full.json", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        elements = json.load(response)["elements"]
    time.sleep(1)
    nodes = {element["id"]: element for element in elements if element["type"] == "node"}
    ways = {element["id"]: element for element in elements if element["type"] == "way"}
    relation = next(element for element in elements if element["type"] == "relation" and element["id"] == relation_id)
    members = []
    for member in relation["members"]:
        item = {"type": member["type"], "ref": member["ref"], "role": member.get("role", "")}
        if member["type"] == "way" and member["ref"] in ways:
            item["geometry"] = [{"lat": nodes[node]["lat"], "lon": nodes[node]["lon"]} for node in ways[member["ref"]]["nodes"] if node in nodes]
        members.append(item)
    return {"type": "relation", "id": relation_id, "tags": relation.get("tags", {}), "members": members}


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
        if member["type"] == "way" and member.get("role", "") in WAY_ROLES and member.get("geometry")
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


# A person corrected this line, in the routes repo's editor or through an approved
# suggestion in the app. Rebuilds must not overwrite it.
CORRECTED_STATUS = "community_verified"


def dumps_network(network: dict) -> str:
    """The routes repo's own formatter, so a rebuild's diff shows only what really changed."""
    tools = str(Path(__file__).resolve().parents[1] / "data" / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from routeformat import dumps_network as canonical

    return canonical(network)


def write_network(path: Path, features: list[dict]) -> None:
    """Write a city's file from freshly built lines, keeping every line a person corrected."""
    corrected: dict[str, dict] = {}
    if path.exists():
        corrected = {feature["properties"]["id"]: feature for feature in json.loads(path.read_text(encoding="utf-8"))["features"]
                     if feature["properties"].get("status") == CORRECTED_STATUS}
    kept = [corrected.pop(feature["properties"]["id"], feature) for feature in features]
    network = {"type": "FeatureCollection", "features": [*kept, *corrected.values()]}
    path.write_text(dumps_network(network), encoding="utf-8")


def overlay(path: Path, routes: dict[str, tuple[list[int], str | None, str | None]]) -> None:
    """Replace the listed lines in a city's GeoJSON with their OSM circuits, keeping every other line.

    Each line's existing anchors are reused as candidate landmarks. A line a person
    corrected is skipped, and the build says so, so its fix can be moved to OSM.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    relations = fetch_relations([relation_id for ids, _, _ in routes.values() for relation_id in ids])
    for feature in data["features"]:
        properties = feature["properties"]
        if properties["id"] not in routes:
            continue
        if properties.get("status") == CORRECTED_STATUS:
            print(f"{path.stem}: keeping corrected line {properties['number']} {properties['name']}", flush=True)
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
    path.write_text(dumps_network(data), encoding="utf-8")
