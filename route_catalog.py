"""Published Bacolod LPTRP lines and limited road-aligned trip patterns.

The 24 line names and lengths come from Table 1 of the Bacolod LPTRP study.
The study's Figure 2 is a schematic, not street-level route geometry. The two
MVP line corridors use inferred OpenStreetMap road alignments through the
diagram's landmarks. Do not treat these as surveyed jeepney tracks or stops.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from road_geometry import trip_segment


LPTRP_SOURCE = (
    "https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/"
    "TSSP2023-09-Tiglao-1.pdf"
)
CITY_SOURCE = (
    "https://bacolodcity.gov.ph/updated-routes-under-the-local-public-"
    "transport-route-plan-lptrp/"
)
CITY_2025_UPDATE = (
    "https://bacolodcity.gov.ph/bacolod-city-holds-local-public-"
    "transport-route-plan-lptrp-public-consultation-2025/"
)
LOCAL_TRIP_CORROBORATION = (
    "https://www.reddit.com/r/LasalleBacolod/comments/1vsc3k8/"
    "jeep_to_ride_from_ayala/"
)

# Approved LPTRP lines, rather than a claim that every line is running today.
ROUTES = (
    (1, "banago-libertad", "Banago – Libertad Loop", 17.0),
    (2, "bata-libertad", "Bata – Libertad Loop", 16.9),
    (3, "northbound-libertad", "Northbound Terminal – Libertad Loop", 15.23),
    (4, "pepsi-bata-bgc", "Pepsi – Bata – Bacolod Government Center Loop", 16.61),
    (5, "shopping-northbound", "Shopping – Northbound Terminal Loop", 8.305),
    (6, "shopping-libertad-lasalle", "Shopping – Libertad via La Salle Loop", 10.9),
    (7, "shopping-libertad-san-agustin", "Shopping – Libertad via San Agustin Loop", 13.46),
    (8, "eroreco-central-market", "Eroreco – Central Market Loop", 7.14),
    (9, "punta-taytay-ferrero", "Punta Taytay – Fr. Ferrero St. Loop", 24.35),
    (10, "tangub-south-capitol", "Tangub – South Capitol Rd. Loop", 16.02),
    (11, "airport-south-capitol", "Airport Subd. – South Capitol Rd. Loop", 13.57),
    (12, "taculing-central-market", "Taculing – Central Market Loop", 7.56),
    (13, "alijis-central-market", "Alijis (RPHS) – Central Market Loop", 14.95),
    (14, "handumanan-libertad", "Handumanan – Libertad via Mansilingan Loop", 15.79),
    (15, "paglaum-libertad", "Paglaum Village – Libertad Loop", 16.42),
    (16, "mansilingan-central-market", "Mansilingan – Central Market via City Heights Loop", 10.54),
    (17, "fortune-central-market", "Fortune Towne / Estefania – Central Market Loop", 16.0),
    (18, "granada-burgos", "Granada – Burgos", 7.6),
    (19, "alangilan-burgos", "Alangilan – Burgos", 18.0),
    (20, "san-dionisio-central-market", "San Dionisio – Central Market Loop", 9.33),
    (21, "homesite-central-market", "PHHC (Homesite) – Central Market Loop", 9.09),
    (22, "dona-juliana-central-market", "Doña Juliana – Central Market Loop", 8.4),
    (23, "bredco-northbound", "BREDCO Port – Northbound Terminal via San Juan St. Loop", 12.72),
    (24, "pahanocoy-bgc", "Pahanocoy (CEGASCO) – Bacolod Government Center via Circumferential Rd. Loop", 18.12),
)

ROUTE_BY_ID = {
    slug: {"number": number, "id": slug, "name": name, "length_km": length}
    for number, slug, name, length in ROUTES
}

# Approximate landmark centroids. They identify a general boarding/alighting
# area and are not official stop coordinates or a street-level route shape.
LANDMARKS = {
    "northterminal": {"name": "Bacolod North Terminal area", "lat": 10.70655, "lng": 122.96312},
    "ayala": {"name": "Ayala Malls Capitol Central area", "lat": 10.6768, "lng": 122.9500},
    "sm": {"name": "SM City Bacolod area", "lat": 10.6722, "lng": 122.9443},
    "lasalle": {"name": "University of St. La Salle area", "lat": 10.6785, "lng": 122.9626},
}


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    earth_radius_km = 6371.0
    lat_delta = radians(b_lat - a_lat)
    lng_delta = radians(b_lng - a_lng)
    haversine = (
        sin(lat_delta / 2) ** 2
        + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(lng_delta / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(haversine))


def nearby_landmark(lat: float, lng: float, radius_km: float = 0.35) -> str | None:
    matches = sorted(
        (
            (distance_km(lat, lng, place["lat"], place["lng"]), key)
            for key, place in LANDMARKS.items()
        )
    )
    return matches[0][1] if matches and matches[0][0] <= radius_km else None


def _leg(route_id: str, segment_id: str) -> dict:
    segment = trip_segment(segment_id)
    return {
        "route_id": route_id,
        "route_name": ROUTE_BY_ID[route_id]["name"],
        "board_near": segment["properties"]["anchors"][0],
        "alight_near": segment["properties"]["anchors"][-1],
        "geometry": segment["geometry"],
        "geometry_status": segment["properties"]["status"],
        "road_distance_km": segment["properties"]["distance_m"] / 1000,
    }


def match_jeepney(
    origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float
) -> dict | None:
    """Match only researched landmark directions; never infer citywide service."""
    start = nearby_landmark(origin_lat, origin_lng)
    end = nearby_landmark(destination_lat, destination_lng)
    if (start, end) == ("ayala", "sm"):
        route_ids = ["bata-libertad"]
        legs = [_leg("bata-libertad", "ayala-sm")]
        points = ["ayala", "sm"]
    elif (start, end) == ("northterminal", "ayala"):
        route_ids = ["bata-libertad"]
        legs = [_leg("bata-libertad", "northterminal-ayala")]
        points = ["northterminal", "ayala"]
    elif (start, end) == ("northterminal", "sm"):
        route_ids = ["bata-libertad"]
        legs = [_leg("bata-libertad", "northterminal-sm")]
        points = ["northterminal", "sm"]
    elif (start, end) == ("northterminal", "lasalle"):
        route_ids = ["bata-libertad", "shopping-libertad-lasalle"]
        legs = [
            _leg("bata-libertad", "northterminal-sm"),
            _leg("shopping-libertad-lasalle", "sm-lasalle"),
        ]
        points = ["northterminal", "sm", "lasalle"]
    elif (start, end) == ("sm", "lasalle"):
        route_ids = ["shopping-libertad-lasalle"]
        legs = [_leg("shopping-libertad-lasalle", "sm-lasalle")]
        points = ["sm", "lasalle"]
    elif (start, end) == ("ayala", "lasalle"):
        route_ids = ["bata-libertad", "shopping-libertad-lasalle"]
        legs = [
            _leg("bata-libertad", "ayala-sm"),
            _leg("shopping-libertad-lasalle", "sm-lasalle"),
        ]
        points = ["ayala", "sm", "lasalle"]
    else:
        return None

    waypoint_coordinates = [legs[0]["geometry"]["coordinates"][0]]
    waypoint_coordinates.extend(leg["geometry"]["coordinates"][-1] for leg in legs)
    waypoints = [
        {"name": LANDMARKS[key]["name"], "lat": coordinate[1], "lng": coordinate[0]}
        for key, coordinate in zip(points, waypoint_coordinates)
    ]

    return {
        "ride_count": len(legs),
        "lines": [ROUTE_BY_ID[route_id] for route_id in route_ids],
        "legs": legs,
        "waypoints": waypoints,
        "geometry_type": "inferred_road_alignment",
        "road_distance_km": round(sum(leg["road_distance_km"] for leg in legs), 2),
        "source_url": LPTRP_SOURCE,
        "local_corroboration_url": LOCAL_TRIP_CORROBORATION,
        "note": "Markers are reference landmarks, not designated stops. Street alignment is inferred from the route map and OpenStreetMap; confirm the jeepney's direction locally.",
    }


def public_catalog() -> dict:
    mapped_portions = {
        "bata-libertad": "North Terminal → Ayala → SM",
        "shopping-libertad-lasalle": "SM → La Salle",
    }
    return {
        "routes": [
            {**route, "mapped_portion": mapped_portions.get(route["id"])}
            for route in ROUTE_BY_ID.values()
        ],
        "source_url": LPTRP_SOURCE,
        "city_notice_url": CITY_SOURCE,
        "status_note": "Published Bacolod LPTRP routes. Two lines have inferred street previews for limited portions; current operation and alignments may vary.",
    }
