"""Build inferred LPTRP line geometry from map anchors and OSM roads.

Run this manually when anchor research changes. The app serves the generated
GeoJSON locally and does not depend on OSRM at runtime.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "jeepney_network.geojson"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"

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


def main() -> None:
    forced = set(sys.argv[1:])
    existing = {}
    if OUTPUT.exists():
        existing = {
            feature["properties"]["id"]: feature
            for feature in json.loads(OUTPUT.read_text(encoding="utf-8"))["features"]
        }
    features = []
    for number, route_id, name, color, anchor_ids in ROUTES:
        if route_id in existing and route_id not in forced:
            print(f"Keeping {number:02d} {name}", flush=True)
            features.append(existing[route_id])
            continue
        print(f"Routing {number:02d} {name}", flush=True)
        geometry, distance_km = route_geometry(anchor_ids)
        features.append({
            "type": "Feature",
            "properties": {
                "number": number,
                "id": route_id,
                "name": name,
                "color": color,
                "status": "inferred_from_lptrp_anchors",
                "distance_km": round(distance_km, 2),
                "anchors": [
                    {"id": key, "name": key.replace("_", " ").title(), "lng": P[key][0], "lat": P[key][1]}
                    for key in anchor_ids
                ],
            },
            "geometry": geometry,
        })
        OUTPUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
        time.sleep(0.5)
    print(f"Wrote {len(features)} routes to {OUTPUT}")


if __name__ == "__main__":
    main()
