"""Each city's jeepney network as a static, hail-and-ride GTFS feed."""

import csv
import io
import json
import zipfile
from collections import defaultdict
from datetime import date
from functools import lru_cache

from fastapi.testclient import TestClient

import main
from gtfs_export import DEFAULT_HEADWAY_SECONDS, export_city
from live_network import _build
from transit_network import CITY_METADATA, LINES_BY_CITY, NETWORKS


BUILD_DATE = date(2026, 10, 13)
REQUIRED_FILES = {
    "agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt", "shapes.txt",
    "frequencies.txt", "calendar.txt", "feed_info.txt", "fare_attributes.txt", "fare_rules.txt",
}
client = TestClient(main.app)


def read_feed(data: bytes) -> dict[str, list[dict]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8")))) for name in archive.namelist()}


@lru_cache(maxsize=None)
def exported(city: str, day: date = BUILD_DATE) -> bytes:
    return export_city(city, build_date=day)


def feed(city: str) -> dict[str, list[dict]]:
    return read_feed(exported(city))


def seconds(clock: str) -> int:
    hours, minutes, secs = map(int, clock.split(":"))
    return hours * 3600 + minutes * 60 + secs


def test_every_city_exports_one_route_per_line_with_the_required_files():
    for city, metadata in CITY_METADATA.items():
        tables = feed(city)
        assert REQUIRED_FILES <= tables.keys(), city
        assert [row["agency_name"] for row in tables["agency.txt"]] == [f"{metadata['name']} jeepneys"]
        assert tables["agency.txt"][0]["agency_timezone"] == "Asia/Manila"
        assert len(tables["routes.txt"]) == len(LINES_BY_CITY[city])
        assert all(tables.values()), city


def test_foreign_keys_resolve():
    for city in CITY_METADATA:
        tables = feed(city)
        agencies = {row["agency_id"] for row in tables["agency.txt"]}
        routes = {row["route_id"] for row in tables["routes.txt"]}
        trips = {row["trip_id"] for row in tables["trips.txt"]}
        shapes = {row["shape_id"] for row in tables["shapes.txt"]}
        stops = {row["stop_id"] for row in tables["stops.txt"]}
        services = {row["service_id"] for row in tables["calendar.txt"]}
        fares = {row["fare_id"] for row in tables["fare_attributes.txt"]}
        assert {row["agency_id"] for row in tables["routes.txt"]} <= agencies
        for trip in tables["trips.txt"]:
            assert trip["route_id"] in routes and trip["shape_id"] in shapes and trip["service_id"] in services, trip
        assert {row["trip_id"] for row in tables["stop_times.txt"]} == trips
        assert {row["stop_id"] for row in tables["stop_times.txt"]} == stops  # every stop is served
        assert {row["trip_id"] for row in tables["frequencies.txt"]} == trips
        for rule in tables["fare_rules.txt"]:
            assert rule["fare_id"] in fares and rule["route_id"] in routes


def test_stop_times_run_in_order_along_the_shape():
    for city in CITY_METADATA:
        tables = feed(city)
        shape_km = defaultdict(list)
        for point in tables["shapes.txt"]:
            shape_km[point["shape_id"]].append((int(point["shape_pt_sequence"]), float(point["shape_dist_traveled"])))
        for shape_id, points in shape_km.items():
            sequences, distances = zip(*points)
            assert list(sequences) == sorted(sequences), shape_id
            assert all(b > a for a, b in zip(distances, distances[1:])), shape_id
        shape_of = {trip["trip_id"]: trip["shape_id"] for trip in tables["trips.txt"]}
        by_trip = defaultdict(list)
        for row in tables["stop_times.txt"]:
            by_trip[row["trip_id"]].append(row)
        for trip_id, rows in by_trip.items():
            assert len(rows) >= 2, trip_id
            sequences = [int(row["stop_sequence"]) for row in rows]
            times = [seconds(row["arrival_time"]) for row in rows]
            distances = [float(row["shape_dist_traveled"]) for row in rows]
            assert sequences == sorted(set(sequences)), trip_id
            assert all(b >= a for a, b in zip(times, times[1:])), trip_id
            assert all(b > a for a, b in zip(distances, distances[1:])), trip_id
            assert distances[-1] <= shape_km[shape_of[trip_id]][-1][1], trip_id
            assert all(row["arrival_time"] == row["departure_time"] and row["timepoint"] == "0" for row in rows)


def test_feed_models_hail_and_ride_service_on_an_assumed_headway():
    tables = feed("bacolod")
    assert all(row["continuous_pickup"] == row["continuous_drop_off"] == "0" for row in tables["routes.txt"])
    assert all(row["route_type"] == "3" and len(row["route_color"]) == 6 and "#" not in row["route_color"] for row in tables["routes.txt"])
    assert {(row["headway_secs"], row["exact_times"]) for row in tables["frequencies.txt"]} == {(str(DEFAULT_HEADWAY_SECONDS), "0")}
    assert DEFAULT_HEADWAY_SECONDS == 600
    calendar = tables["calendar.txt"][0]
    assert all(calendar[day] == "1" for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))
    # A circuit runs out to its far terminal and back, as the planner's "toward" headings do.
    banago = [trip for trip in tables["trips.txt"] if trip["route_id"] == "banago-libertad"]
    assert [(trip["direction_id"], trip["trip_headsign"]) for trip in banago] == [("0", "Libertad"), ("1", "Banago")]
    info = tables["feed_info.txt"][0]
    assert info["feed_publisher_name"] == "Lugar.ph" and info["feed_version"] == "2026-10-13"
    assert "base fare" in info["lugar_notes"] and "assumption" in info["lugar_notes"]
    assert tables["fare_attributes.txt"] == [{"fare_id": "jeepney_base_fare", "price": "14.00", "currency_type": "PHP",
                                               "payment_method": "0", "transfers": "0", "agency_id": "bacolod"}]


def test_inferred_lines_are_distinguishable_from_traced_ones():
    for city in CITY_METADATA:
        statuses = {line.id: line.status for line in LINES_BY_CITY[city]}
        for route in feed(city)["routes.txt"]:
            assert route["lugar_status"] == statuses[route["route_id"]]
            assert ("estimated from the published route plan" in route["route_desc"]) == route["lugar_status"].startswith("inferred_")
    naga = feed("naga")["routes.txt"]
    assert all(route["lugar_status"].startswith("inferred_") and "estimated" in route["route_desc"] for route in naga)


def test_uv_express_routes_get_no_jeepney_fare():
    tables = feed("cebu")
    uv_express = {line.id for line in LINES_BY_CITY["cebu"] if line.mode == "uv_express"}
    fared = {rule["route_id"] for rule in tables["fare_rules.txt"]}
    assert fared == {line.id for line in LINES_BY_CITY["cebu"]} - uv_express


def test_ids_are_stable_between_exports():
    assert export_city("davao", build_date=BUILD_DATE) == exported("davao")
    later = read_feed(export_city("bacolod", build_date=date(2026, 12, 1)))
    for name, column in (("routes.txt", "route_id"), ("trips.txt", "trip_id"), ("stops.txt", "stop_id"), ("shapes.txt", "shape_id")):
        assert [row[column] for row in later[name]] == [row[column] for row in feed("bacolod")[name]], name
    assert feed("bacolod")["stops.txt"][0]["stop_id"] == "bacolod-banago-libertad-000"


def test_approved_revisions_replace_and_remove_lines():
    replaced = {**NETWORKS["bacolod"]["features"][0]}
    replaced["properties"] = {**replaced["properties"], "status": "community_verified", "anchors": [], "return_anchors": []}
    live = _build("bacolod", ((replaced["properties"]["id"], json.dumps(replaced)), ("bata-libertad", None)))
    routes = {row["route_id"]: row for row in read_feed(export_city("bacolod", live, BUILD_DATE))["routes.txt"]}
    assert "bata-libertad" not in routes
    assert routes["banago-libertad"]["lugar_status"] == "community_verified"


def test_city_feed_endpoint():
    response = client.get("/naga/gtfs.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="lugar-naga-gtfs.zip"' in response.headers["content-disposition"]
    assert REQUIRED_FILES <= read_feed(response.content).keys()
    redirect = client.get("/cagayan-de-oro/gtfs.zip", follow_redirects=False)
    assert redirect.status_code == 308 and redirect.headers["location"] == "/cdo/gtfs.zip"
    assert client.get("/manila/gtfs.zip").status_code == 404


def test_routes_screen_links_the_feed():
    assert 'href="`/${city}/gtfs.zip`"' in client.get("/bacolod").text
