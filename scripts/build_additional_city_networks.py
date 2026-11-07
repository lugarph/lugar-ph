"""Build Iloilo, Cebu, and Tacloban jeepney GeoJSON files.

Iloilo and Tacloban lines use endpoint and corridor anchors transcribed from
their LTFRB route structures, then follow OSM roads through public OSRM. Each
is drawn as a full circuit in riding order (out to the far terminal and back),
with the way back routed separately so one-way streets are respected; list
known return landmarks in RETURN_VIA. Cebu
uses the archived DOTC GTFS shapes and keeps codes found in the 74-line Cebu
Bus Spotters directory. Lines mapped in OpenStreetMap (OSM_ROUTES) then
replace the generated ones; pass --osm-only to refresh just those. Generated
geometry is committed so runtime is offline.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from osm_routes import overlay, write_network


ROOT = Path(__file__).resolve().parents[1]
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
COLORS = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#ea580c", "#0891b2", "#c026d3", "#4f46e5", "#65a30d", "#db2777")

ILOILO_SOURCE = "https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf"
TACLOBAN_SOURCE = "https://tacloban.gov.ph/ordinance/page/5/"
CEBU_SOURCE = "https://www.transit.land/feeds/f-wcb4-cebu~dotc"
CEBU_DIRECTORY = "https://sites.google.com/view/cebubusspotters/cbs-virtual-library/cebu-jeepney-route-guide/cebu-city-jeepney-routes"

I = {
    "molo": (122.5441131, 10.6969114), "proper": (122.5736662, 10.6926337),
    "obrero": (122.5797, 10.7133), "villa": (122.5048, 10.6867),
    "ungka": (122.5390235, 10.7464288), "cpu": (122.5493335, 10.7307835),
    "festive": (122.5462299, 10.7170583), "lanit": (122.5683341, 10.7691105),
    "infante": (122.5553267, 10.6929217), "compania": (122.5361381, 10.6891193),
    "parola": (122.5842, 10.7000), "sm": (122.5517428, 10.7149703),
    "mohon": (122.4998694, 10.6926481), "tagbak": (122.5774308, 10.7618510),
    "ticud": (122.5785019, 10.7174905), "mandurriao": (122.5369198, 10.7171820),
    "hibaoan": (122.5266406, 10.7282701), "jaro": (122.5572445, 10.7244416),
    "bitoon": (122.5895154, 10.7502843), "lapaz": (122.5678, 10.7107),
    "isatu": (122.5659859, 10.7152659),
}

ILOILO_ROUTES = (
    ("01", "Molo – City Proper via General Luna", 8.67, ["molo", "infante", "proper"]),
    ("02", "Bo. Obrero Lapuz – City Proper Loop", 11.04, ["obrero", "proper"]),
    ("03", "Villa Plaza – City Proper via Calumpang", None, ["villa", "molo", "infante", "proper"]),
    ("04", "Ungka – City Proper via CPU", 9.33, ["ungka", "cpu", "jaro", "lapaz", "proper"]),
    ("05", "Ungka – City Proper via Aquino Avenue / Festive Walk", 9.65, ["ungka", "festive", "sm", "infante", "proper"]),
    ("06", "Festive Walk Transport Hub – City Proper via Diversion / SM City", 6.91, ["festive", "sm", "infante", "proper"]),
    ("07", "Lanit – Infante via SM City", 13.23, ["lanit", "jaro", "sm", "infante"]),
    ("08", "Compania – City Proper Loop", 12.38, ["compania", "molo", "proper"]),
    ("09", "Parola – SM City via Infante Loop", 14.12, ["parola", "proper", "infante", "sm"]),
    ("10", "Mohon – City Proper", 9.26, ["mohon", "villa", "molo", "infante", "proper"]),
    ("11", "Buntatala / Tagbak – City Proper", 14.85, ["tagbak", "jaro", "lapaz", "proper"]),
    ("12", "Ticud La Paz – City Proper", None, ["ticud", "lapaz", "proper"]),
    ("13", "Mandurriao – City Proper via Festive Walk / Aquino Avenue", 10.68, ["mandurriao", "festive", "sm", "infante", "proper"]),
    ("14", "Hibao-an – City Proper via Tabucan", 10.70, ["hibaoan", "molo", "infante", "proper"]),
    ("15", "Hibao-an – Jaro via Festive / Aquino Avenue", 10.76, ["hibaoan", "festive", "sm", "jaro"]),
    ("16", "Molo – City Proper via Baluarte Loop", 10.46, ["molo", "infante", "proper"]),
    ("17", "Bito-on – Jaro via Balabago Loop", None, ["bitoon", "jaro"]),
    ("18", "Villa Baybay – Iloilo City Proper", 10.32, ["villa", "molo", "proper"]),
    ("19", "Buntatala / Tagbak – City Proper via Lapuz", 11.92, ["tagbak", "obrero", "proper"]),
    ("20", "Bito-on – City Proper via La Paz", 9.81, ["bitoon", "lapaz", "proper"]),
    ("21", "Mohon – ISATU via Sooc / Festive Walk", 17.99, ["mohon", "mandurriao", "festive", "jaro", "isatu"]),
    ("22", "Buntatala / Tagbak – Festive Walk via SM City / Atria", 8.95, ["tagbak", "jaro", "sm", "festive"]),
    ("23", "Ungka – La Paz via CPU / ISATU Loop", 13.36, ["ungka", "cpu", "jaro", "isatu", "lapaz"]),
    ("24", "Mohon – Mandurriao Business District", 8.86, ["mohon", "molo", "festive", "sm"]),
    ("25", "La Paz – Festive Walk via Nabitasan Loop", 8.94, ["lapaz", "isatu", "sm", "festive"]),
)

T = {
    "downtown": (125.0030, 11.2420), "kassel": (124.9831430, 11.2374182),
    "sanroque": (124.9436674, 11.2748066), "manlurip": (125.0175594, 11.1973330),
    "cabalawan": (124.9579649, 11.2999779), "imelda": (124.9934506, 11.1960369),
    "kawayan": (124.9492462, 11.3319138), "marasbaras": (125.0067758, 11.2019355),
    "newbus": (124.9878522, 11.2390533), "robinsons": (125.0072488, 11.2078856),
    "airport": (125.0274758, 11.2275065), "tagpuro": (124.9431483, 11.3386721),
    "vg": (124.9990709, 11.1993607), "vgwest": (124.9958, 11.1983),
    "camansihay": (124.9409867, 11.3024865), "staelena": (124.9364100, 11.3410229),
    "palanog": (124.9676066, 11.2585078), "peerless": (124.9619073, 11.2905270),
    "calanipawan": (124.9990156, 11.2081465), "astrodome": (125.0050171, 11.2216218),
    "anibong": (124.9950, 11.2570), "nagahanga": (124.9815, 11.2690),
    "sanjose": (125.0120, 11.2185),
}

TACLOBAN_ROUTES = (
    ("01", "Tacloban City – Kassel City", 10.73, ["kassel", "nagahanga", "anibong", "downtown"]),
    ("02", "Tacloban City – San Roque", 8.67, ["sanroque", "nagahanga", "anibong", "downtown"]),
    ("03", "Tacloban City – Manlurip via Apitong", 19.20, ["manlurip", "sanjose", "astrodome", "downtown"]),
    ("04", "Tacloban City – Cabalawan", 22.53, ["cabalawan", "newbus", "downtown"]),
    ("05", "Tacloban City – Imelda Village", 6.96, ["imelda", "sanjose", "downtown"]),
    ("06", "Tacloban City – New Kawayan", 16.56, ["kawayan", "newbus", "downtown"]),
    ("07", "Tacloban City – Marasbaras", 14.22, ["marasbaras", "downtown"]),
    ("08", "Tacloban City – New Bus Terminal", 5.82, ["newbus", "downtown"]),
    ("09", "Tacloban City – Robinsons South", 9.96, ["robinsons", "downtown"]),
    ("10", "Tacloban City – San Jose / DZR Airport", 17.45, ["airport", "sanjose", "downtown"]),
    ("11", "Tacloban City – Tagpuro", 18.85, ["tagpuro", "newbus", "downtown"]),
    ("12", "Tacloban City – V&G Subdivision Phases 1, 2, 3, 5, 6", 13.39, ["vg", "calanipawan", "downtown"]),
    ("13", "Tacloban City – V&G Subdivision Phases 4, 4 Ext., 2B, 3B", 13.22, ["vgwest", "calanipawan", "downtown"]),
    ("14", "Tacloban City – Camansihay via Ridgeview", 15.16, ["camansihay", "newbus", "downtown"]),
    ("15", "Tacloban City – Sta. Elena", 17.88, ["staelena", "newbus", "downtown"]),
    ("16", "Tacloban City – Palanog", 10.64, ["palanog", "newbus", "downtown"]),
    ("17", "Tacloban City – Bagacay via Peerless Village", 9.65, ["peerless", "nagahanga", "anibong", "downtown"]),
    ("18", "Tacloban City – Calanipawan", 10.15, ["calanipawan", "astrodome", "downtown"]),
    ("19", "Robinsons South – Robinsons North", 5.03, ["robinsons", "sanjose", "newbus"]),
)

CEBU_CODES = {
    "01A","01B","01C","01E","01H","01K","02A","02B","03A","03B","03G","03Q","03L",
    "04B","04C","04D","04H","04I","04L","04M","06A","06B","06C","06D","06F","06G","06H",
    "07B","07D","08E","08F","08G","09C","09F","09G","09H","09J","10C","10D","10E","10F",
    "10G","10H","10K","10M","11A","11D","12A","12B","12C","12D","12E","12F","12G","12I",
    "12J","12L","12M","13B","13C","13H","13I","14B","14C","14D","15","15A","17B","17C",
    "17D","51","51E","62B","62C","63B",
}


def distance_km(points: list[list[float]]) -> float:
    from math import asin, cos, radians, sin, sqrt
    total = 0.0
    for first, second in zip(points, points[1:]):
        dlat, dlng = radians(second[1] - first[1]), radians(second[0] - first[0])
        value = sin(dlat / 2) ** 2 + cos(radians(first[1])) * cos(radians(second[1])) * sin(dlng / 2) ** 2
        total += 12742 * asin(sqrt(value))
    return total


def osrm(anchor_ids: list[str], places: dict[str, tuple[float, float]]) -> dict:
    coordinates = ";".join(f"{places[key][0]},{places[key][1]}" for key in anchor_ids)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    request = urllib.request.Request(f"{OSRM_URL}{coordinates}?{query}", headers={"User-Agent": "LugarPH/0.3 network builder"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)["routes"][0]["geometry"]
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 + attempt * 2)
    raise RuntimeError("unreachable")


# Lines mapped street by street in OpenStreetMap, overlaid on the generated
# files: relation ids in riding order (outbound, then return), the starting
# terminal, and the far terminal, from the relations' from/to tags. Iloilo's
# OSM routes use an older numbering, so only clear name matches are listed.
OSM_ROUTES: dict[str, dict[str, tuple[list[int], str | None, str | None]]] = {
    "iloilo": {
        "iloilo-02": ([15029087, 15029088], "City Proper", "Barrio Obrero"),
        "iloilo-04": ([15029083, 15029084], "City Proper", "Ungka"),
        "iloilo-05": ([15029082], "Ungka", "City Proper"),
        "iloilo-06": ([15029080, 15029081], "City Proper", "Festive Walk Transport Hub"),
        "iloilo-08": ([15029076, 15029077], "City Proper", "Compania"),
        "iloilo-11": ([15029070, 15029071], "City Proper", "Tagbak"),
        "iloilo-15": ([15029062, 15029063], "Jaro", "Hibao-an"),
        "iloilo-16": ([15029060, 15029061], "City Proper", "Molo"),
        "iloilo-17": ([15029058, 15029059], "Jaro", "Bitoon"),
        "iloilo-18": ([15029056, 15029057], "City Proper", "Villa Baybay"),
    },
    "tacloban": {
        "tacloban-01": ([19847427, 19847428], "Tacloban City Proper", "Kassel City"),
        "tacloban-02": ([19847425, 19847426], "San Roque", "Tacloban City Proper"),
        "tacloban-03": ([19847423, 19847424], "Tacloban City Proper", "Manlurip"),
        "tacloban-04": ([19847421, 19847422], "Tacloban City Proper", "Cabalawan"),
        "tacloban-05": ([19847419, 19847420], "Imelda Village", "Tacloban City"),
        "tacloban-07": ([19847876, 19847877], "Marasbaras", "Tacloban City Proper"),
    },
    "cebu": {
        "cebu-01b": ([20587182, 20587183], "Pier 1 & 2", "Sambag 1"),
        "cebu-01c": ([21251283, 21251284], "Robinsons", "Sambag"),
        "cebu-01k": ([21251289, 21251290], "Parkmall", "Urgello"),
        "cebu-02b": ([21251287, 21251288], "San Nicolas", "Robinsons"),
        "cebu-03a": ([21251279, 21251280], "Carbon Market", "Mabolo"),
        "cebu-03b": ([21251277, 21251278], "Mabolo", "Carbon Market"),
        "cebu-03l": ([21251273, 21251274], "Carbon Market", "Mabolo"),
        "cebu-03q": ([21267107, 21267108], None, None),
        "cebu-04c": ([21251269, 21251270], "Campo Lahug", "Carbon Market"),
        "cebu-04d": ([21254495, 21254496], "Carbon Market", "Plaza Housing"),
        "cebu-04l": ([14991302, 14991303], None, None),
        "cebu-06b": ([21142705, 21142706], "Carbon Market", "Guadalupe"),
        "cebu-06c": ([21265626, 21265627], "Carbon Market", "Guadalupe"),
        "cebu-06f": ([21267111, 21267112], "Magallanes", "Guadalupe"),
        "cebu-06g": ([21142707, 21142708], "San Nicolas", "Guadalupe"),
        "cebu-06h": ([21267109, 21267110], "SM City Cebu", "Guadalupe"),
        "cebu-07b": ([21267105, 21267106], "Carbon Market", "Banawa"),
        "cebu-08g": ([21241370, 21241371], "Colon", "Alumnos"),
        "cebu-09c": ([21267103, 21267104], "Carbon Market", "Pardo"),
        "cebu-09f": ([21267101, 21267102], "Colon", "Pardo"),
        "cebu-09g": ([21241368, 21241369], "Colon", "Basak"),
        "cebu-10f": ([21267099, 21267100], "Colon", "Bulacao"),
        "cebu-10g": ([21251285, 21251286], "Pardo", "Magallanes"),
        "cebu-10h": ([21267097, 21267098], "North Reclamation", "Bulacao"),
        "cebu-10m": ([21267095, 21267096], "SM City Cebu", "Bulacao"),
        "cebu-11a": ([21363724, 21363725], "Colon", "Inayawan"),
        "cebu-13b": ([21251281, 21251282], "Talamban", "Carbon Market"),
        "cebu-13c": ([21251275, 21251276], "Colon", "Talamban"),
    },
}


# Landmarks a line passes on its way back, when they differ from the outbound
# ones in reverse. Keyed by "city-code", for example "iloilo-02".
RETURN_VIA: dict[str, list[str]] = {}


def build_inferred(city: str, routes, places, source: str) -> None:
    features = []
    for index, (code, name, planned_km, anchor_ids) in enumerate(routes):
        print(f"{city}: {code} {name}", flush=True)
        return_via = RETURN_VIA.get(f"{city}-{code.lower()}", anchor_ids[-2:0:-1])
        geometry = osrm([*anchor_ids, *return_via, anchor_ids[0]], places)
        features.append({
            "type": "Feature",
            "properties": {
                "number": code, "id": f"{city}-{code.lower()}", "name": name,
                "color": COLORS[index % len(COLORS)], "status": "inferred_from_official_route_structure",
                "distance_km": round(distance_km(geometry["coordinates"]), 2), "planned_length_km": planned_km,
                "source_url": source,
                "anchors": [{"id": key, "name": key.replace("_", " ").title(), "lng": places[key][0], "lat": places[key][1]} for key in anchor_ids],
                "return_anchors": [
                    {"id": key, "name": key.replace("_", " ").title(), "lng": places[key][0], "lat": places[key][1]}
                    for key in RETURN_VIA.get(f"{city}-{code.lower()}", [])
                ],
            },
            "geometry": geometry,
        })
        time.sleep(0.35)
    output = ROOT / "data" / f"{city}_jeepney_network.geojson"
    write_network(output, features)


def build_cebu(gtfs_directory: Path) -> None:
    feed = gtfs_directory / "GTFS_feed" if (gtfs_directory / "GTFS_feed").exists() else gtfs_directory
    with (feed / "routes.txt").open(newline="", encoding="utf-8-sig") as file:
        routes = {row["route_id"].upper(): row for row in csv.DictReader(file)}
    shapes = defaultdict(list)
    with (feed / "shapes.txt").open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            shapes[row["shape_id"].upper()].append((int(row["shape_pt_sequence"]), [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])]))
    features = []
    for index, code in enumerate(sorted(CEBU_CODES)):
        if code not in routes or code not in shapes:
            print(f"Cebu: skipping {code}; missing from archived GTFS", flush=True)
            continue
        points = [point for _, point in sorted(shapes[code])]
        raw_name = routes[code].get("route_short_name") or routes[code].get("route_long_name") or code
        raw_name = raw_name.replace("\x96", "-").replace("OsmeÃ±a", "Osmeña")
        name = raw_name.title().replace(" - ", " – ")
        features.append({
            "type": "Feature",
            "properties": {
                "number": code, "id": f"cebu-{code.lower()}", "name": name,
                "color": COLORS[index % len(COLORS)], "status": "archived_dotc_gtfs_shape",
                "distance_km": round(distance_km(points), 2), "planned_length_km": None,
                "source_url": CEBU_SOURCE, "directory_url": CEBU_DIRECTORY,
                "anchors": [
                    {"id": "start", "name": f"{code} route endpoint", "lng": points[0][0], "lat": points[0][1]},
                    {"id": "end", "name": f"{code} route endpoint", "lng": points[-1][0], "lat": points[-1][1]},
                ],
            },
            "geometry": {"type": "LineString", "coordinates": points},
        })
    output = ROOT / "data" / "cebu_jeepney_network.geojson"
    write_network(output, features)
    print(f"Cebu: wrote {len(features)} GTFS shapes", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cebu-gtfs", type=Path, help="Directory containing the Cebu GTFS text files")
    parser.add_argument("--osm-only", action="store_true", help="Only re-import the OpenStreetMap lines into the existing files")
    args = parser.parse_args()
    if not args.osm_only:
        build_inferred("iloilo", ILOILO_ROUTES, I, ILOILO_SOURCE)
        build_inferred("tacloban", TACLOBAN_ROUTES, T, TACLOBAN_SOURCE)
        if args.cebu_gtfs:
            build_cebu(args.cebu_gtfs)
    # Mapped lines replace the generated ones, so rebuilding never loses them.
    for city, routes in OSM_ROUTES.items():
        overlay(ROOT / "data" / f"{city}_jeepney_network.geojson", routes)
