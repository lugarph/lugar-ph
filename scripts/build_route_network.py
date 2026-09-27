"""Build Bacolod line geometry as full circuits in riding order.

Lines mapped street by street in OpenStreetMap (OSM_ROUTES) are imported
from their public-transport route relations: one relation per direction,
joined out and back, or one relation for a loop. Small breaks between a
relation's ways are bridged with a driving route. This geometry is derived
from OpenStreetMap, (c) OpenStreetMap contributors, under the ODbL.

The remaining lines are inferred from LPTRP anchors: routed out through
their anchors to the far terminal, then back. The way back is routed
separately with the driving profile, which follows one-way restrictions.
Where a line is known to come back through other landmarks, list them in
RETURN_VIA.

Run this manually when route research or the OSM relations change; pass
route ids to rebuild them. The app serves the generated GeoJSON locally and
does not depend on OSRM or Overpass at runtime.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "jeepney_network.geojson"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
USER_AGENT = "LugarPH/0.4 route network builder"

# Coordinates were triangulated against named points in the supplied LPTRP
# diagram and OpenStreetMap. Intermediate road anchors preserve the corridor
# shown by the diagram; they are not official stops.
P = {
    "banago_school": (122.95053, 10.70964),
    "puno_banago": (122.9550, 10.7016),
    "north_terminal": (122.96312, 10.70655),
    "bata": (122.97692, 10.70104),
    "pepsi": (122.96317, 10.70522),
    "lacson_north": (122.9630, 10.6920),
    "ayala": (122.94955, 10.67702),
    "bredco": (122.94202, 10.67774),
    "sm": (122.94436, 10.67221),
    "central_market": (122.94719, 10.66761),
    "burgos_market": (122.95498, 10.66892),
    "libertad": (122.94974, 10.66012),
    "lasalle": (122.96248, 10.67842),
    "san_agustin": (122.9670, 10.6850),
    "queen_mercy": (122.97137, 10.68987),
    "eroreco": (122.97160, 10.69011),
    "triangle": (122.9632, 10.6739),
    "bgc": (122.96658, 10.65885),
    "south_terminal": (122.95564, 10.66249),
    "punta_taytay": (122.90518, 10.59995),
    "tangub": (122.93450, 10.63455),
    "airport": (122.93266, 10.65150),
    "gaisano": (122.93965, 10.65923),
    "taculing": (122.94871, 10.64969),
    "adventist": (122.94948, 10.64755),
    "alijis": (122.95036, 10.63671),
    "handumanan": (122.96373, 10.60161),
    "mansilingan": (122.99046, 10.62263),
    "city_heights": (122.9780, 10.6420),
    "paglaum": (123.00592, 10.61779),
    "vista_alegre": (122.99762, 10.64400),
    "bangga_cory": (122.9840, 10.6510),
    "fortune": (122.99439, 10.67931),
    "estefania": (122.99832, 10.66338),
    "montalban": (122.9890, 10.6710),
    "granada": (123.04775, 10.65883),
    "alangilan": (123.07795, 10.66109),
    "san_dionisio": (123.01914, 10.66883),
    "homesite": (122.97015, 10.66912),
    "dona_juliana": (122.9820, 10.6500),
    "pahanocoy": (122.93246, 10.61251),
    "circumferential_south": (122.9720, 10.6190),
    "bangga_cabug": (122.9850, 10.6150),
}

ROUTES = (
    (1, "banago-libertad", "Banago – Libertad Loop", "#ef6f77", ["banago_school", "puno_banago", "ayala", "bredco", "sm", "libertad"]),
    (2, "bata-libertad", "Bata – Libertad Loop", "#7667d9", ["bata", "north_terminal", "lacson_north", "ayala", "sm", "libertad"]),
    (3, "northbound-libertad", "Northbound Terminal – Libertad Loop", "#36bfa5", ["north_terminal", "lacson_north", "ayala", "sm", "libertad"]),
    (4, "pepsi-bata-bgc", "Pepsi – Bata – Bacolod Government Center Loop", "#64748b", ["pepsi", "bata", "north_terminal", "lacson_north", "ayala", "burgos_market", "bgc"]),
    (5, "shopping-northbound", "Shopping – Northbound Terminal Loop", "#d2c600", ["central_market", "burgos_market", "ayala", "lacson_north", "north_terminal"]),
    (6, "shopping-libertad-lasalle", "Shopping – Libertad via La Salle Loop", "#159447", ["central_market", "burgos_market", "triangle", "lasalle", "south_terminal", "libertad"]),
    (7, "shopping-libertad-san-agustin", "Shopping – Libertad via San Agustin Loop", "#3346c8", ["central_market", "burgos_market", "san_agustin", "triangle", "south_terminal", "libertad"]),
    (8, "eroreco-central-market", "Eroreco – Central Market Loop", "#ed8b2f", ["eroreco", "queen_mercy", "lasalle", "triangle", "burgos_market", "central_market"]),
    (9, "punta-taytay-ferrero", "Punta Taytay – Fr. Ferrero St. Loop", "#dc2626", ["punta_taytay", "tangub", "gaisano", "libertad", "central_market", "burgos_market"]),
    (10, "tangub-south-capitol", "Tangub – South Capitol Rd. Loop", "#16a66a", ["tangub", "gaisano", "libertad", "sm", "ayala"]),
    (11, "airport-south-capitol", "Airport Subd. – South Capitol Rd. Loop", "#6d28a0", ["airport", "gaisano", "libertad", "sm", "ayala"]),
    (12, "taculing-central-market", "Taculing – Central Market Loop", "#7f1d1d", ["taculing", "adventist", "libertad", "central_market"]),
    (13, "alijis-central-market", "Alijis (RPHS) – Central Market Loop", "#67b7e1", ["alijis", "adventist", "libertad", "central_market"]),
    (14, "handumanan-libertad", "Handumanan – Libertad via Mansilingan Loop", "#65d56e", ["handumanan", "mansilingan", "city_heights", "libertad"]),
    (15, "paglaum-libertad", "Paglaum Village – Libertad Loop", "#d616c5", ["paglaum", "vista_alegre", "bangga_cory", "libertad"]),
    (16, "mansilingan-central-market", "Mansilingan – Central Market via City Heights Loop", "#6b2a7a", ["mansilingan", "city_heights", "libertad", "central_market"]),
    (17, "fortune-central-market", "Fortune Towne / Estefania – Central Market Loop", "#e7b817", ["fortune", "estefania", "montalban", "burgos_market", "central_market"]),
    (18, "granada-burgos", "Granada – Burgos", "#e87878", ["granada", "san_dionisio", "estefania", "montalban", "burgos_market"]),
    (19, "alangilan-burgos", "Alangilan – Burgos", "#68731b", ["alangilan", "granada", "san_dionisio", "estefania", "montalban", "burgos_market"]),
    (20, "san-dionisio-central-market", "San Dionisio – Central Market Loop", "#159a9c", ["san_dionisio", "estefania", "montalban", "burgos_market", "central_market"]),
    (21, "homesite-central-market", "PHHC (Homesite) – Central Market Loop", "#168ec2", ["homesite", "burgos_market", "central_market"]),
    (22, "dona-juliana-central-market", "Doña Juliana – Central Market Loop", "#eab084", ["dona_juliana", "bgc", "burgos_market", "central_market"]),
    (23, "bredco-northbound", "BREDCO Port – Northbound Terminal via San Juan St. Loop", "#20b994", ["bredco", "sm", "central_market", "ayala", "lacson_north", "north_terminal"]),
    (24, "pahanocoy-bgc", "Pahanocoy (CEGASCO) – Bacolod Government Center via Circumferential Rd. Loop", "#d681d8", ["pahanocoy", "bgc"]),
)


# Lines mapped in OpenStreetMap: relation ids in riding order (outbound, then
# return; a loop is one relation), the starting terminal, and the far
# terminal. Names come from the route plan, which also corrects a few OSM tag
# slips (a return relation tagged with its outbound from/to, "South Capital").
OSM_ROUTES: dict[str, tuple[list[int], str, str]] = {
    "banago-libertad": ([21146076, 21146074], "Banago", "Libertad"),
    "bata-libertad": ([14998328, 14998329], "Bata", "Libertad"),
    "northbound-libertad": ([21146071, 21146072], "Northbound Terminal", "Libertad"),
    "shopping-northbound": ([21146073, 21146070], "Shopping", "Northbound Terminal"),
    "shopping-libertad-lasalle": ([14998324], "Shopping", "Libertad"),
    "shopping-libertad-san-agustin": ([21146069], "Shopping", "Libertad"),
    "eroreco-central-market": ([21146068], "Eroreco", "Central Market"),
    "punta-taytay-ferrero": ([21163565, 21163564], "Punta Taytay", "Fr. Ferrero St."),
    "tangub-south-capitol": ([21163994, 21163995], "Tangub", "South Capitol Rd."),
    "airport-south-capitol": ([21163992, 21163993], "Airport Subd.", "South Capitol Rd."),
    "mansilingan-central-market": ([14998327, 14998326], "Mansilingan", "Central Market"),
}
# A loop relation may start anywhere on its circuit; start it at this anchor.
LOOP_START = {
    "shopping-libertad-lasalle": "central_market",
    "shopping-libertad-san-agustin": "central_market",
    "eroreco-central-market": "eroreco",
}
# For a loop, the far terminal is the point nearest this anchor.
LOOP_TURNAROUND = {
    "shopping-libertad-lasalle": "libertad",
    "shopping-libertad-san-agustin": "libertad",
    "eroreco-central-market": "central_market",
}
# Class 3 UV Express routes in City Ordinance 966, not jeepneys.
UV_EXPRESS = {"granada-burgos", "alangilan-burgos"}
GAP_KM = 0.03
MAX_SEGMENT_KM = 0.4
ANCHOR_REACH_KM = 0.4
TERMINAL_CLEARANCE_KM = 0.5

# Landmarks a line passes on its way back, between the far terminal and the
# start, when they differ from the outbound ones in reverse. Keyed by route id.
RETURN_VIA: dict[str, list[str]] = {}


def circuit(route_id: str, anchor_ids: list[str]) -> list[str]:
    """Outbound anchors, then the way back to the first anchor."""
    return_via = RETURN_VIA.get(route_id, anchor_ids[-2:0:-1])
    return [*anchor_ids, *return_via, anchor_ids[0]]


def route_geometry(anchor_ids: list[str]) -> tuple[dict, float]:
    coordinates = ";".join(f"{P[key][0]},{P[key][1]}" for key in anchor_ids)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    request = urllib.request.Request(
        f"{OSRM_URL}{coordinates}?{query}",
        headers={"User-Agent": "LugarPH/0.2 route network builder"},
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                route = json.load(response)["routes"][0]
            return route["geometry"], route["distance"] / 1000
        except (OSError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"OSRM failed for {anchor_ids}: {last_error}")


def km(a: list[float], b: list[float]) -> float:
    """Equirectangular distance between [lng, lat] points; exact enough at city scale."""
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 110.57)


def osrm_path(a: list[float], b: list[float]) -> list[list[float]]:
    geometry, _ = route_geometry_between([a, b])
    return geometry["coordinates"]


def route_geometry_between(points: list[list[float]]) -> tuple[dict, float]:
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


def join(points: list[list[float]], piece: list[list[float]]) -> list[list[float]]:
    """Append a piece of path, bridging a break with a driving route."""
    if not points:
        return list(piece)
    gap = km(points[-1], piece[0])
    if gap <= GAP_KM:
        return points + piece[1:]
    print(f"    bridging a {gap:.2f} km break", flush=True)
    return points + osrm_path(points[-1], piece[0])[1:-1] + piece


def relation_path(relation: dict) -> list[list[float]]:
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


def rotate_to(points: list[list[float]], target: list[float]) -> list[list[float]]:
    """Start a closed circuit at its point nearest the target, keeping the riding order."""
    start = min(range(len(points)), key=lambda index: km(points[index], target))
    return points[start:] + points[1 : start + 1]


def densify(points: list[list[float]]) -> list[list[float]]:
    """Split long straight segments so stops can be placed along them."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        parts = max(1, math.ceil(km(a, b) / MAX_SEGMENT_KM))
        out.extend([a[0] + (b[0] - a[0]) * step / parts, a[1] + (b[1] - a[1]) * step / parts] for step in range(1, parts + 1))
    return out


def anchor(key: str, name: str, point: list[float]) -> dict:
    return {"id": key, "name": name, "lng": round(point[0], 6), "lat": round(point[1], 6)}


def osm_anchors(points: list[list[float]], turnaround: int, anchor_ids: list[str], start_name: str, far_name: str) -> tuple[list[dict], list[dict]]:
    """Terminals from the mapped route, plus the planned landmarks it really passes, in riding order.

    Landmarks within reach of a terminal are dropped: the terminal already names that spot.
    """
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + km(a, b))
    terminals = (points[0], points[turnaround])
    passed = []
    for key in anchor_ids:
        target = list(P[key])
        index = min(range(len(points)), key=lambda i: km(points[i], target))
        name = key.replace("_", " ").lower()
        repeats_terminal = any(name in terminal_name.lower() or terminal_name.lower() in name for terminal_name in (start_name, far_name))
        if km(points[index], target) <= ANCHOR_REACH_KM and not repeats_terminal and all(km(target, terminal) > TERMINAL_CLEARANCE_KM for terminal in terminals):
            passed.append((cumulative[index], key))
    outbound = [key for position, key in sorted(passed) if position < cumulative[turnaround]]
    inbound = [key for position, key in sorted(passed) if position > cumulative[turnaround]]
    slug = lambda text: text.lower().replace(".", "").replace(" ", "_")
    landmark = lambda key: anchor(key, key.replace("_", " ").title(), list(P[key]))
    anchors = [anchor(slug(start_name), start_name, points[0]), *map(landmark, outbound), anchor(slug(far_name), far_name, points[turnaround])]
    return anchors, [landmark(key) for key in inbound]


def osm_feature(number: int, route_id: str, name: str, color: str, anchor_ids: list[str], relations: dict[int, dict]) -> dict:
    relation_ids, start_name, far_name = OSM_ROUTES[route_id]
    points: list[list[float]] = []
    far_point = list(P[LOOP_TURNAROUND[route_id]]) if len(relation_ids) == 1 else None
    for position, relation_id in enumerate(relation_ids):
        points = join(points, relation_path(relations[relation_id]))
        if position == 0 and far_point is None:
            far_point = points[-1]  # the outbound relation ends at the far terminal
    points = densify(join(points, [points[0]]))  # close the circuit
    if route_id in LOOP_START:
        points = rotate_to(points, list(P[LOOP_START[route_id]]))
    turnaround = min(range(len(points)), key=lambda index: km(points[index], far_point))
    anchors, return_anchors = osm_anchors(points, turnaround, anchor_ids, start_name, far_name)
    return {
        "type": "Feature",
        "properties": {
            "number": number, "id": route_id, "name": name, "color": color, "mode": "jeepney",
            "status": "osm_route_relation", "distance_km": round(sum(km(a, b) for a, b in zip(points, points[1:])), 2),
            "source_url": f"https://www.openstreetmap.org/relation/{relation_ids[0]}",
            "osm_relations": relation_ids,
            "attribution": "© OpenStreetMap contributors, ODbL",
            "anchors": anchors,
            "return_anchors": return_anchors,
        },
        "geometry": {"type": "LineString", "coordinates": [[round(lng, 6), round(lat, 6)] for lng, lat in points]},
    }


def main() -> None:
    forced = set(sys.argv[1:])
    existing = {}
    if OUTPUT.exists():
        existing = {
            feature["properties"]["id"]: feature
            for feature in json.loads(OUTPUT.read_text(encoding="utf-8"))["features"]
        }
    features = []
    relations: dict[int, dict] = {}
    for number, route_id, name, color, anchor_ids in ROUTES:
        mode = "uv_express" if route_id in UV_EXPRESS else "jeepney"
        from_osm = route_id in OSM_ROUTES
        current = existing.get(route_id)
        if current and route_id not in forced and (current["properties"]["status"] == "osm_route_relation") == from_osm:
            print(f"Keeping {number:02d} {name}", flush=True)
            features.append({**current, "properties": {**current["properties"], "mode": mode}})
            continue
        if from_osm:
            if not relations:
                relations = fetch_relations([relation_id for ids, _, _ in OSM_ROUTES.values() for relation_id in ids])
            print(f"Importing {number:02d} {name} from OpenStreetMap", flush=True)
            features.append(osm_feature(number, route_id, name, color, anchor_ids, relations))
            OUTPUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
            continue
        print(f"Routing {number:02d} {name}", flush=True)
        geometry, distance_km = route_geometry(circuit(route_id, anchor_ids))
        features.append({
            "type": "Feature",
            "properties": {
                "number": number,
                "id": route_id,
                "name": name,
                "color": color,
                "mode": mode,
                "status": "inferred_from_lptrp_anchors",
                "distance_km": round(distance_km, 2),
                "anchors": [
                    {"id": key, "name": key.replace("_", " ").title(), "lng": P[key][0], "lat": P[key][1]}
                    for key in anchor_ids
                ],
                "return_anchors": [
                    {"id": key, "name": key.replace("_", " ").title(), "lng": P[key][0], "lat": P[key][1]}
                    for key in RETURN_VIA.get(route_id, [])
                ],
            },
            "geometry": geometry,
        })
        OUTPUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
        time.sleep(0.5)
    OUTPUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
    print(f"Wrote {len(features)} routes to {OUTPUT}")


if __name__ == "__main__":
    main()
