"""Build Baguio, Cagayan de Oro, Davao, and Naga jeepney lines.

Cagayan de Oro, Naga, and most of Davao are drawn from street-by-street
route plans; Baguio and two Davao lines are imported from OpenStreetMap.

Inputs live in data/sources/<city>/:

- route_plan.json: the published route descriptions as extracted, with the
  source URL and retrieval date. Each route lists the streets it takes
  inbound (barangay to the city centre) and outbound (back).
- places.json: coordinates for the terminals, markets, and bridges the plans
  name, with where each came from and whether it is approximate.

Each line is drawn as a full circuit in riding order: from its barangay
terminal along the inbound streets to the far terminal, then back along the
outbound streets. See street_sequences.py for how streets become waypoints.
Lines mapped in OpenStreetMap (OSM_ROUTES) then replace the drawn ones.

Routing uses OSRM's driving profile, which keeps to one-way streets, on the
public servers or on your own (set LUGAR_OSRM_URL; see osm_routes.py).
Routes and relations are cached in scripts/.cache, so a rerun only asks for what changed.
Run from the repo root:

    python scripts/build_city_networks.py [baguio] [cdo] [davao] [naga]

Geometry is derived from OpenStreetMap, (c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from osm_routes import Point, circuit, fetch_relations, km, osm_anchors, osm_properties, overlay, slug, write_network
from street_sequences import fetch_streets, fold, route_through, split_sequence, waypoints


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
COLORS = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#ea580c", "#0891b2", "#c026d3", "#4f46e5", "#65a30d", "#db2777")
STATUS = "inferred_from_official_route_structure"
# A line drawn much shorter than its published length is missing its outer
# end (an unmapped terminal or road); half a route would mislead riders.
MIN_DRAWN_RATIO = 0.6


@dataclass
class PlannedLine:
    code: str  # shown on chips: "Bulua R1", "8A"
    name: str  # "Terminal – Terminal"
    start: str | None  # place key of the first terminal
    far: str | None  # place key of the far terminal
    inbound: list[str]  # street sequence from start to far
    outbound: list[str]  # street sequence from far back to start
    planned_km: float | None
    source_url: str


# Spellings in the plans mapped to a place key or to the OpenStreetMap street
# name they mean. Keys are folded (lowercase ASCII, no punctuation).
CDO_ALIASES = {
    # Terminals and landmarks
    "carmen public market": "Carmen Public Market", "carment public market": "Carmen Public Market", "ororama": "Carmen Public Market",
    "cogon public market": "Cogon Public Market", "cogon market": "Cogon Public Market", "cogon": "Cogon Public Market",
    "agora market city terminal": "Agora Terminal", "agora market city and terminal": "Agora Terminal",
    "agora market city terminal terminal": "Agora Terminal", "agora terminal": "Agora Terminal",
    "divisoria park": "Divisoria", "westbound terminal and public market": "Westbound Terminal",
    "westbound terminal public market": "Westbound Terminal", "westbound terminal": "Westbound Terminal",
    "wtpm": "Westbound Terminal", "wtpm road": "Westbound Terminal",
    "puerto public market": "Puerto Public Market", "limketkai center": "Limketkai Center", "gaisano city": "Gaisano City",
    "bulua lto": "Bulua LTO", "u turn bulua lto": "Bulua LTO", "u turn fronting lto": "Bulua LTO", "delmonte gate 2": "Del Monte Gate 2",
    "marcos bridge": "Marcos Bridge", "kagay an bridge": "Kagay-an Bridge", "kagayan bridge": "Kagay-an Bridge",
    "ysalina bridge": "Ysalina Bridge", "puntod kauswagan bridge": "Puntod-Kauswagan Bridge",
    "kauswagan puntod bridge": "Puntod-Kauswagan Bridge", "jr borja bridge": "J.R. Borja Bridge", "bulao steel bridge": "Bulao Bridge",
    "centro baikingon": "Baikingon", "baikingon": "Baikingon", "centro balulang": "Balulang", "balulang r1 centro": "Balulang",
    "villa verde subd": "Villa Verde", "xavier heights subd": "Xavier Heights", "brgy bayabas": "Bayabas",
    "barangay bayabas": "Bayabas", "bayabas": "Bayabas", "brgy bonbon": "Bonbon", "bonbon": "Bonbon", "terry hills subd": "Terry Hills",
    "terry hills subdivision": "Terry Hills", "canitoan high school": "Canitoan High School", "calaanan relocation": "Calaanan",
    "silver creek": "Silver Creek", "silver creek subdivision": "Silver Creek", "san agustin valley": "San Agustin Valley",
    "pueblo de oro xavier estates gate 3": "Xavier Estates Gate 3", "pueblo de oro xavier estates": "Xavier Estates Gate 3",
    "pueblo de oro": "Xavier Estates Gate 3", "carmen zone 10": "Carmen Zone 10", "bulao": "Bulao", "iponan bulao": "Bulao",
    "kinasanghan iponan": "Kinasanghan", "kisanlu subd": "Kisanlu", "kisanlu subdivision": "Kisanlu", "kisanlu regency": "Kisanlu",
    "phase 2 nha health center kauswagan": "NHA Kauswagan", "nha": "NHA Kauswagan", "kauswagan pasil road": "Pasil",
    "centro brgy lumbia": "Lumbia", "gran europa": "Gran Europa", "pagatpat centro": "Pagatpat", "centro brgy pagatpat": "Pagatpat",
    "centro pamalihi": "Pamalihi", "camp evangelista": "Camp Evangelista", "patag camp evangelsita": "Camp Evangelista",
    "centro san simon": "San Simon", "san simon": "San Simon", "centro balubal": "Balubal", "villa trinitas subd": "Villa Trinitas",
    "centro brgy cugman": "Cugman", "barangay fs catanico": "FS Catanico", "centro barangay fs catanico": "FS Catanico",
    "gusa brgy hall": "Gusa Barangay Hall",     "centro brgy indahag": "Indahag", "indahag centro": "Indahag", "centro taguanao": "Taguanao",
    "centro sitio macapaya": "Macapaya", "centro macabalan": "Macabalan", "buena oro": "Buena Oro", "centro buena oro": "Buena Oro",
    "eagle st": "Eagle Street", "eagles st": "Eagle Street",
    # Streets spelled differently from OpenStreetMap
    "p chaves st": "P. Chavez Street", "p chaves": "P. Chavez Street", "t chavez st": "Toribio Chaves Street",
    "t chaves st": "Toribio Chaves Street", "chaves st": "Toribio Chaves Street", "chavez st": "Toribio Chaves Street",
    "capistranost": "Capistrano Street", "saaranes st": "Saarenas Street", "vamental blvd": "Vamenta Boulevard",
    "valezuela ave": "Valenzuela Ave", "rn peleaz blvd": "R. N. Pelaez Boulevard",
    "the baptist st": "John The Baptist Street", "john the baptist st": "John The Baptist Street",
    "e jabulin st": "Captain Jabulin Street", "jabulin st": "Captain Jabulin Street",
    "bonbon pasil road": "Pasil-Bonbon Road", "lumbia diversion palalan road": "Lumbia Diversion Road",
    "macapagal road": "Macapagal Drive", "pagatpat road": "Canitoan-Pagatpat Road", "tibasak road": "Tibasak Street",
    "cadre road": "CDO-Cadre Road", "balubal agusan road": "Agusan-Balubal Road", "agusan balubal road": "Agusan-Balubal Road",
    "camaman an indahag road": "Indahag Road", "saint paul st": "Saint Paul Street",
    "j pacana st": "Julio Pacana Street", "jr borja st": "Mayor J. R. Borja Avenue",
    "jr borja ave": "Mayor J. R. Borja Avenue", "j r borja st": "Mayor J. R. Borja Avenue", "jr borja avenue": "Mayor J. R. Borja Avenue",
    "v roa st": "Captain Vicente Roa Street",
    "cruz taal st": "Cruz Taal Street", "t neri st": "Tirso Neri Street", "velez st": "Don Apolinar Velez Street",
    "a velez st": "Don Apolinar Velez Street", "sto nino st": "Sto. Niño Street", "baconga st": "Baconga Road",
}
# Barangay routes that run far into the uplands (50-80 km round trips), and a
# listing whose description repeats another route's, are left out.
CDO_EXCLUDED = ("Dansolihon", "Tuburan", "Tagpangi", "Tumpagon")


def _places(city: str) -> dict[str, Point | None]:
    data = json.loads((SOURCES / city / "places.json").read_text(encoding="utf-8"))["places"]
    return {name: ([item["lng"], item["lat"]] if item else None) for name, item in data.items()}


def _place_key(text: str, places: dict, aliases: dict[str, str]) -> str | None:
    for candidate in (text, re.sub(r"\([^)]*\)", " ", text), " ".join(re.findall(r"\(([^)]*)\)", text))):
        key = aliases.get(fold(candidate), candidate.strip(" .–-"))
        if key in places:
            return key
    return None


def cdo_lines() -> list[PlannedLine]:
    plan = json.loads((SOURCES / "cdo" / "route_plan.json").read_text(encoding="utf-8"))
    places = _places("cdo")
    lines = []
    for route in plan["routes"]:
        title = re.sub(r"\s*\(?\d[\d.]*\s*(km|kilometer)?\s*(roundtrip|rt)\)?\s*$", "", route["title"], flags=re.I).strip()
        if not route["operational"] or title.startswith(CDO_EXCLUDED):
            continue
        parts = [part.strip() for part in re.split(r"\s+[–-]\s+|\s*–\s*", title.replace("Evangelsita", "Evangelista")) if part.strip()]
        left, far_text = " ".join(parts[:-1]), re.sub(r"\s+via\s+.*$", "", parts[-1])
        match = re.match(r"^(.*?)\s*\(?R(\d)\)?\s*(.*)$", left)
        if match:
            base, rest = match.group(1), re.sub(r"\s*\([^)]*\)?", "", match.group(3)).strip()
            code = f"{base} R{match.group(2)}"
        else:
            base, rest = re.sub(r"\s*\(.*$", "", left), " ".join(re.findall(r"\(([^)]*)\)", left))
            code = base if len(base.split()) <= 2 else base.split()[0]
        inbound, outbound = split_sequence(route["inbound"]), split_sequence(route["outbound"])
        start = _place_key(inbound[0], places, CDO_ALIASES) or _place_key(rest or base, places, CDO_ALIASES) or _place_key(base, places, CDO_ALIASES)
        far = _place_key(inbound[-1], places, CDO_ALIASES) or _place_key(far_text, places, CDO_ALIASES)
        label = base if rest in ("", "Centro") or code == base else rest
        name = f"{label} – {parts[-1]}".replace(" and Terminal", "").replace(" and Public Market", "").replace("Market City", "Market")
        lines.append(PlannedLine(code, name, start, far, inbound, outbound, round(route["inbound_km"] + route["outbound_km"], 1), plan["source_urls"][0 if route["district"] == "District 1" else 1]))
    return lines


def transcribed_lines(city: str) -> list[PlannedLine]:
    """Lines from a route plan already transcribed into start, far, inbound, and outbound fields."""
    plan = json.loads((SOURCES / city / "route_plan.json").read_text(encoding="utf-8"))
    return [
        PlannedLine(route["code"], route["name"], route["start"], route["far"], split_sequence(route["inbound"]),
                    split_sequence(route["outbound"]), route.get("planned_km"), route["source_url"])
        for route in plan["routes"]
    ]


# Naga's plan calls the highway into the city AH26 (Asian Highway 26): from
# the Pili boundary it is Maharlika Highway, then Almeda Highway to the
# junction with Magsaysay Avenue, Roxas Avenue, and Panganiban Drive.
NAGA_ALIASES = {"ah26": "Almeda Highway", "maharlika highway": "Almeda Highway", "diaz st": "P. Diaz Street", "carolina rd": "San Isidro - Carolina Road",
                "panicuason rd": "San Felipe-Pacol-Carolina-Panicuason Road", "balatas rd": "Balatas-Cararayan Road"}

# Downtown Davao's main streets share surnames with smaller streets elsewhere.
DAVAO_ALIASES = {"quezon boulevard": "Manuel L. Quezon Boulevard", "magsaysay": "Ramon Magsaysay Avenue",
                 "quirino avenue": "Elpidio Quirino Avenue", "chavez": "Governor Chavez Street", "dela cruz": "Juan dela Cruz Street"}

CITIES = {
    "cdo": {"bbox": (8.36, 124.52, 8.56, 124.79), "lines": cdo_lines, "aliases": CDO_ALIASES},
    "naga": {"bbox": (13.55, 123.14, 13.70, 123.33), "lines": lambda: transcribed_lines("naga"), "aliases": NAGA_ALIASES},
    "davao": {"bbox": (7.00, 125.55, 7.16, 125.70), "lines": lambda: transcribed_lines("davao"), "aliases": DAVAO_ALIASES},
    "baguio": {},  # mapped in OpenStreetMap only; see OSM_LINES
}

# Lines drawn from a plan that are mapped street by street in OpenStreetMap:
# relation ids in riding order, then the starting and far terminal names.
OSM_ROUTES: dict[str, dict[str, tuple[list[int], str | None, str | None]]] = {
    # Davao's relations use the older one-relation-per-route scheme. Only
    # these have no breaks; Routes 1, 5, 8, 11, and 13 have gaps of up to 2.4 km.
    "davao": {"davao-4": ([6736912], "Claveria", "SPMC")},
}

# Lines that only exist in OpenStreetMap: code, name, relation ids in riding
# order (downtown outward, then back), and the far terminal's name.
DOWNTOWN = "Downtown Baguio"
OSM_LINES: dict[str, list[tuple[str, str, list[int], str | None]]] = {
    # Baguio's lines were ground-surveyed in OpenStreetMap, one relation per
    # direction. Jeeps show their destination rather than a number, so it
    # stands in as the code. Lines to Agoo, Rosario, Pugo (Taloy), Sablan,
    # Nangalisan, and Itogon run 10-26 km out of the city and are left out,
    # as are one-way-only mappings (Tawang) and alternative return paths.
    "baguio": [
        ("Asin Hot Springs", "Baguio – Asin Hot Springs", [13440188, 13440189], "Asin Hot Springs"),
        ("Asin Road", "Baguio – Asin Road", [13440186, 13440187], "Asin Road"),
        ("Aurora Hill", "Baguio – Aurora Hill", [10841890, 10841891], "Aurora Hill"),
        ("Badiwan", "Baguio – Badiwan", [13595082, 13595081], "Badiwan"),
        ("Bakakeng", "Baguio – Bakakeng Norte / Sur", [10827541, 10822347], "Bakakeng"),
        ("Balacbac", "Baguio – Balacbac", [15590276, 15590275], "Balacbac"),
        ("Bengao", "Baguio – Bengao", [16243861, 16243860], "Bengao"),
        ("Camp 6", "Baguio – Camp 6", [14134274, 14134306], "Camp 6"),
        ("Camp 7", "Baguio – Camp 7", [13495464, 13495463], "Camp 7"),
        ("Camp Dangwa", "Baguio – Camp Dangwa", [13970693, 13970692], "Camp Dangwa"),
        ("Campo Sioco", "Baguio – Campo Sioco", [13594334, 13594333], "Campo Sioco"),
        ("City Camp", "Baguio – City Camp Quarry", [13667243, 13667242], "City Camp Quarry"),
        ("Country Club", "Baguio – Country Club", [13618337, 13618349], "Country Club"),
        ("Crystal Cave", "Baguio – Crystal Cave", [13625711, 13627575], "Crystal Cave"),
        ("Dumpsite", "Baguio – Dumpsite", [14747600, 14747449], "Dumpsite"),
        ("Gabriela Silang", "Baguio – Gabriela Silang", [13594348, 13594549], "Gabriela Silang"),
        ("Green Valley", "Baguio – Green Valley", [11190023, 11190024], "Green Valley"),
        ("Greenwater", "Baguio – Greenwater", [10827821, 10827822], "Greenwater"),
        ("Guisad", "Baguio – Guisad", [13562608, 13562598], "Guisad"),
        ("Happy Hollow", "Baguio – Happy Hollow", [14134819, 14135112], "Happy Hollow"),
        ("Kitma", "Baguio – Kitma", [10814471, 10813981], "Kitma"),
        ("Lamtang", "Baguio – Lamtang", [13627848, 13627847], "Lamtang"),
        ("Liteng", "Baguio – Liteng", [10841916, 10841917], "Liteng"),
        ("Loakan PEZA", "Baguio – Loakan PEZA", [13384988, 13384989], "Loakan PEZA"),
        ("Longlong", "Baguio – Longlong", [13462733, 13462731], "Longlong"),
        ("Lourdes", "Baguio – Lourdes Dominican", [13571343, 13571476], "Dominican Mirador"),
        ("Lucnab", "Baguio – Lucnab", [13613151, 13613150], "Lucnab"),
        ("Marville", "Baguio – Marville", [13668464, 13668303], "Marville"),
        ("Military Cut-Off", "Baguio – Military Cut-Off", [10827706, 10827746], "Military Cut-Off"),
        ("Mines View", "Baguio – Mines View", [10831360, 10831364], "Mines View Park"),
        ("Navy Base", "Baguio – Navy Base", [11174155, 11173414], "Navy Base"),
        ("Pico-Puguis", "Baguio – Pico-Puguis Loop", [7402943], None),
        ("Pinget", "Baguio – Pinget-Dreamland", [18654966, 18655895], "Dreamland"),
        ("Pinsao", "Baguio – Pinsao Pilot Project", [13573518, 13573517], "Pinsao Pilot Project"),
        ("PMA Kias", "Baguio – PMA Kias", [10828037, 10831305], "Kias"),
        ("Quezon Hill", "Baguio – Quezon Hill", [13573914, 13573913], "Quezon Hill"),
        ("San Carlos Hts.", "Baguio – San Carlos Heights", [12910001, 12910000], "San Carlos Heights"),
        ("San Carlos Ext.", "Baguio – San Carlos Heights Extension", [13598983, 13598982], "San Carlos Heights Extension"),
        ("San Luis", "Baguio – San Luis", [13460743, 13462544], "San Luis"),
        ("St. Patrick", "Baguio – Saint Patrick / NPC", [11243347, 11243161], "Saint Patrick / NPC"),
        ("Scout Barrio", "Baguio – Scout Barrio", [10822449, 10822551], "Scout Barrio"),
        ("Tam-Awan", "Baguio – Tam-Awan", [13595132, 13595131], "Tam-Awan"),
        ("Trancoville", "Baguio – Trancoville Loop", [15475655], None),
        ("Ucab", "Baguio – Ucab", [12922868, 12926774], "Ucab"),
        ("Wangal", "Baguio – Wangal", [16237135, 16237133], "Wangal"),
    ],
    "davao": [("12", "Route 12", [6736832], None)],
}


def osm_features(city: str, landmarks: list[tuple[str, str, Point]], first_color: int) -> list[dict]:
    """Features for the lines that only exist in OpenStreetMap."""
    lines = OSM_LINES.get(city, [])
    if not lines:
        return []
    relations = fetch_relations([relation_id for _, _, ids, _ in lines for relation_id in ids])
    features = []
    for index, (code, name, relation_ids, far_name) in enumerate(lines, start=first_color):
        points, turnaround = circuit(relations, relation_ids)
        start_name = DOWNTOWN if city == "baguio" else None
        anchors, return_anchors = osm_anchors(points, turnaround, landmarks, start_name, far_name or code)
        print(f"{city}: {code:14s} {sum(km(a, b) for a, b in zip(points, points[1:])):5.1f} km from OpenStreetMap", flush=True)
        features.append({
            "type": "Feature",
            "properties": {
                "number": code, "id": f"{city}-{slug(code).replace('_', '-')}", "name": name,
                "color": COLORS[index % len(COLORS)], **osm_properties(relation_ids, points, anchors, return_anchors),
            },
            "geometry": {"type": "LineString", "coordinates": [[round(lng, 6), round(lat, 6)] for lng, lat in points]},
        })
    return features


def build(city: str) -> None:
    config = CITIES[city]
    places = _places(city)
    known = {name: point for name, point in places.items() if point is not None}
    landmarks = [(slug(name), name, point) for name, point in known.items() if "Bridge" not in name]
    planned = config["lines"]() if "lines" in config else []
    streets = fetch_streets(city, config["bbox"]) if planned else None
    features, report = [], []
    for index, line in enumerate(planned):
        start_point = known.get(line.start) if line.start else None
        far_point = known.get(line.far) if line.far else None
        outward, missing_out = waypoints(line.inbound, start_point, far_point, streets, known, config["aliases"])
        # With no mapped start terminal, the way back returns to where the way out began.
        back, missing_back = waypoints(line.outbound, far_point, start_point or outward[0], streets, known, config["aliases"])
        out_path, back_path = route_through(outward), route_through(back)
        points = out_path + back_path[1:]
        turnaround = len(out_path) - 1
        drawn = sum(km(a, b) for a, b in zip(points, points[1:]))
        ratio = drawn / line.planned_km if line.planned_km else None
        report.append((line.code, line.name, round(drawn, 1), line.planned_km, ratio, missing_out + missing_back, line.start, line.far))
        print(f"{city}: {line.code:14s} {drawn:5.1f} km drawn / {line.planned_km} planned"
              f"{'' if not ratio else f' ({ratio:.2f})'}{'  unplaced: ' + '; '.join(missing_out + missing_back) if missing_out + missing_back else ''}", flush=True)
        if ratio is not None and ratio < MIN_DRAWN_RATIO:
            print(f"{city}: {line.code} left out: too little of it could be placed", flush=True)
            continue
        start_name, far_name = line.start or line.name.split(" – ")[0], line.far or line.name.split(" – ")[-1]
        anchors, return_anchors = osm_anchors(points, turnaround, landmarks, start_name, far_name)
        features.append({
            "type": "Feature",
            "properties": {
                "number": line.code, "id": f"{city}-{slug(line.code).replace('_', '-')}", "name": line.name,
                "color": COLORS[index % len(COLORS)], "status": STATUS,
                "distance_km": round(drawn, 2), "planned_length_km": line.planned_km, "source_url": line.source_url,
                "anchors": anchors, "return_anchors": return_anchors,
            },
            "geometry": {"type": "LineString", "coordinates": [[round(lng, 6), round(lat, 6)] for lng, lat in points]},
        })
    features += osm_features(city, landmarks, len(features))
    output = ROOT / "data" / f"{city}_jeepney_network.geojson"
    write_network(output, features)
    if city in OSM_ROUTES:
        overlay(output, OSM_ROUTES[city])
    (SOURCES / city / "build_report.json").write_text(json.dumps(
        [{"code": code, "name": name, "drawn_km": drawn, "planned_km": planned, "ratio": round(ratio, 2) if ratio else None,
          "unplaced": missing, "start": start, "far": far, "included": not (ratio is not None and ratio < MIN_DRAWN_RATIO)}
         for code, name, drawn, planned, ratio, missing, start, far in report],
        indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    for city in sys.argv[1:] or list(CITIES):
        build(city)
