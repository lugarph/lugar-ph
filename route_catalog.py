"""Published Bacolod LPTRP lines and map-derived road geometry.

The 24 line names and lengths come from Table 1 of the Bacolod LPTRP study.
The study's Figure 2 is a schematic, not street-level route geometry. Route
shapes are inferred by routing its named landmarks over OpenStreetMap roads.
Do not treat these as surveyed jeepney tracks or designated stops.
"""

from __future__ import annotations

from transit_network import distance_km, match_trip, public_network


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


def public_catalog() -> dict:
    network_routes = {
        feature["properties"]["id"]: feature["properties"]
        for feature in public_network()["features"]
    }
    return {
        "routes": [
            {
                **route,
                "color": network_routes[route["id"]]["color"],
                "mapped_portion": f"{len(network_routes[route['id']]['anchors'])} LPTRP map anchors",
                "geometry_status": network_routes[route["id"]]["status"],
            }
            for route in ROUTE_BY_ID.values()
        ],
        "source_url": LPTRP_SOURCE,
        "city_notice_url": CITY_SOURCE,
        "status_note": "All 24 planned lines are mapped from LPTRP landmarks onto OSM roads. Geometry and current operation still need local verification.",
    }


def match_jeepney(
    origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float
) -> dict | None:
    return match_trip(origin_lat, origin_lng, destination_lat, destination_lng)
