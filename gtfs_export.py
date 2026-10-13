"""Static GTFS feed of one city's jeepney network.

Jeepneys are hail-and-ride: riders flag one down anywhere along its route and
get off wherever they ask, and the jeeps run on frequency, not a timetable.
The feed says so rather than presenting them as scheduled buses:

- every route allows continuous pickup and drop-off;
- stops are the planner's points every 100 m along each line, not signposted stops;
- each direction has one template trip, timed with the planner's riding speed
  (timepoint=0, so times are approximate) and repeated by an assumed headway
  in frequencies.txt;
- fares list only the base fare, because GTFS fares can't express a per-km fare.

The non-standard `lugar_status` column in routes.txt keeps each line's geometry
source, so lines inferred from route plans stay distinguishable from traced ones.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.exc import SQLAlchemyError

from live_network import LiveNetwork, load_live_network
from models import SessionLocal
from transit_network import (
    CITY_METADATA, FARE_BASE_KM, FARE_BASE_PHP, FARE_PER_KM_PHP, LANDMARKS_BY_CITY, LINES_BY_CITY, RIDE_KMH,
    STOP_SPACING_KM, Anchor, Line, _stop_indexes, _stop_json,
)


PUBLISHER_URL = "https://lugarph.app"
CONTACT_URL = "https://github.com/andrewnyu/lugar-ph/issues"
TIMEZONE = "Asia/Manila"
# An assumption, not observed data: nobody has counted departures on these
# lines. Ten minutes is a typical wait for a city jeepney in daytime.
DEFAULT_HEADWAY_SECONDS = 600
# Also assumed: most city jeepneys run from early morning into the evening.
SERVICE_START_SECONDS, SERVICE_END_SECONDS = 5 * 3600, 22 * 3600
FEED_VALID_DAYS = 365
SERVICE_ID = "daily"
FARE_ID = "jeepney_base_fare"
ROUTE_TYPE_BUS = 3
CONTINUOUS_STOPPING = 0  # GTFS: pick up or drop off anywhere along the route

GEOMETRY_NOTES = {
    "osm_route_relation": "Path mapped street by street in OpenStreetMap.",
    "archived_dotc_gtfs_shape": "Path from the archived 2017 DOTC GTFS feed.",
    "community_verified": "Path drawn by a rider and approved by a Lugar.ph reviewer; not snapped to roads.",
}
INFERRED_NOTE = "Path estimated from the published route plan, not traced street by street."
HAIL_AND_RIDE_NOTE = "Hail-and-ride: flag the jeep anywhere along the route and ask the driver to stop where you need."
FEED_NOTES = (
    "Hail-and-ride jeepneys with no fixed stops or timetables. "
    f"Stops are points every {round(STOP_SPACING_KM * 1000)} m along each route; times assume {RIDE_KMH} km/h; "
    f"the {DEFAULT_HEADWAY_SECONDS // 60}-minute headway and service hours are assumptions, not observed data. "
    f"Fares list only the LTFRB base fare (PHP {FARE_BASE_PHP} for the first {FARE_BASE_KM} km); "
    f"longer rides cost PHP {FARE_PER_KM_PHP} more per km, which GTFS fares cannot express. "
    "UV Express routes have no fare. "
    "routes.txt lugar_status gives each line's geometry source; inferred_* lines are estimated from route plans, not traced."
)


@dataclass(frozen=True)
class _Trip:
    id: str
    direction: int
    headsign: str | None
    start: int  # coordinate index where the trip starts
    end: int  # coordinate index where it ends


def _network(city: str, live: LiveNetwork | None) -> tuple[tuple[Line, ...], tuple[Anchor, ...]]:
    """The published lines: checked-in data with the latest approved revisions applied."""
    if live is None:
        try:
            with SessionLocal() as session:
                live = load_live_network(city, session)
        except SQLAlchemyError:
            # No database or no migrations yet, so nothing has been approved beyond Git.
            return LINES_BY_CITY[city], LANDMARKS_BY_CITY[city]
    return live.graph.lines, live.anchors


def _turnaround(line: Line) -> int | None:
    """Coordinate index of a circuit's far terminal, where outbound becomes return."""
    if not line.circuit or line.turnaround_km is None:
        return None
    index = line.cumulative_km.index(line.turnaround_km)
    return index if 0 < index < len(line.coordinates) - 1 else None


def _trips(line: Line) -> tuple[_Trip, ...]:
    """One template trip per direction, mirroring the planner's "toward" headings."""
    last, turn = len(line.coordinates) - 1, _turnaround(line)
    if turn is None:
        # A circuit without a known far terminal is one loop; any other line is drawn one way only.
        headsign = line.anchors[-1].name if not line.circuit and line.turnaround_km is not None else None
        return (_Trip(f"{line.id}-0", 0, headsign, 0, last),)
    return (
        _Trip(f"{line.id}-0", 0, line.anchors[-1].name, 0, turn),
        _Trip(f"{line.id}-1", 1, line.anchors[0].name, turn, last),
    )


def _stop_points(line: Line) -> tuple[int, ...]:
    """Coordinate indexes of the line's stops: the planner's stops, its terminals, and its far terminal."""
    indexes, turn = _stop_indexes(line), _turnaround(line)
    if turn is not None and turn not in indexes:
        # The far terminal replaces a planner stop that sits within half a spacing of it.
        last, turn_km = len(line.coordinates) - 1, line.cumulative_km[turn]
        kept = [index for index in indexes if index in (0, last) or abs(line.cumulative_km[index] - turn_km) >= STOP_SPACING_KM / 2]
        indexes = tuple(sorted([*kept, turn]))
    # A repeated final point gives the planner a second stop in the same place; GTFS needs distance to grow.
    return tuple(index for position, index in enumerate(indexes)
                 if position == 0 or line.cumulative_km[index] > line.cumulative_km[indexes[position - 1]])


def _stop_id(city: str, line: Line, position: int) -> str:
    return f"{city}-{line.id}-{position:03d}"


def _stop_name(city: str, line: Line, index: int, anchors: tuple[Anchor, ...]) -> str:
    lng, lat = line.coordinates[index]
    label = _stop_json(city, (lat, lng), {}, anchors)["label"]
    if label:
        return label[0].upper() + label[1:]
    return f"Line {line.number}, km {line.cumulative_km[index]:.1f}"


def _clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _coordinate(value: float) -> str:
    return f"{value:.6f}"


def _km(value: float) -> str:
    return f"{value:.6f}"


def _text_color(color: str) -> str:
    """Dark text on light line colours, white on dark ones, as on the app's line chips."""
    def channel(value: str) -> float:
        c = int(value, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(color[index:index + 2]) for index in (0, 2, 4))
    return "17212F" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 else "FFFFFF"


def _route_desc(line: Line) -> str:
    geometry = INFERRED_NOTE if line.estimated_path else GEOMETRY_NOTES.get(line.status, "Path from published route data.")
    vehicle = "UV Express van, not a jeepney; fare paid to the driver. " if line.mode == "uv_express" else ""
    return f"{vehicle}{geometry} {HAIL_AND_RIDE_NOTE}"


def feed_tables(city: str, live: LiveNetwork | None = None, build_date: date | None = None) -> dict[str, tuple[list[str], list[list]]]:
    """Each GTFS file of the city's feed as (header, rows)."""
    build_date = build_date or date.today()
    metadata = CITY_METADATA[city]
    lines, anchors = _network(city, live)
    start_date, end_date = build_date.strftime("%Y%m%d"), (build_date + timedelta(days=FEED_VALID_DAYS)).strftime("%Y%m%d")

    routes, trips, stops, stop_times, shapes, frequencies, fare_rules = [], [], [], [], [], [], []
    for line in lines:
        color = line.color.lstrip("#").upper()
        routes.append([
            line.id, city, line.number, line.name, _route_desc(line), ROUTE_TYPE_BUS, color, _text_color(color),
            CONTINUOUS_STOPPING, CONTINUOUS_STOPPING, line.status, line.source_url or "",
        ])
        if line.mode == "jeepney":
            fare_rules.append([FARE_ID, line.id])

        points = _stop_points(line)
        stop_ids = {index: _stop_id(city, line, position) for position, index in enumerate(points)}
        for index, stop_id in stop_ids.items():
            lng, lat = line.coordinates[index]
            stops.append([
                stop_id, _stop_name(city, line, index, anchors),
                f"Hail-and-ride point {line.cumulative_km[index]:.1f} km along line {line.number}",
                _coordinate(lat), _coordinate(lng), 0,
            ])

        for trip in _trips(line):
            trips.append([line.id, SERVICE_ID, trip.id, trip.headsign or "", trip.direction, trip.id])
            origin_km = line.cumulative_km[trip.start]
            written: tuple[str, str, str] | None = None
            sequence = 0
            for index in range(trip.start, trip.end + 1):
                lng, lat = line.coordinates[index]
                row = (_coordinate(lat), _coordinate(lng), _km(line.cumulative_km[index] - origin_km))
                # Repeated points (or ones too close to tell apart) would break the strictly increasing distance.
                if written and (row[:2] == written[:2] or row[2] == written[2]):
                    continue
                sequence += 1
                shapes.append([trip.id, *row[:2], sequence, row[2]])
                written = row
            trip_stops = [index for index in points if trip.start <= index <= trip.end]
            for sequence, index in enumerate(trip_stops, start=1):
                km = line.cumulative_km[index] - origin_km
                clock = _clock(SERVICE_START_SECONDS + round(km / RIDE_KMH * 3600))
                stop_times.append([trip.id, clock, clock, stop_ids[index], sequence, _km(km), 0])
            frequencies.append([trip.id, _clock(SERVICE_START_SECONDS), _clock(SERVICE_END_SECONDS), DEFAULT_HEADWAY_SECONDS, 0])

    tables = {
        "agency.txt": (
            ["agency_id", "agency_name", "agency_url", "agency_timezone"],
            # Jeepneys are run by many small operators with no shared website,
            # so the city's Lugar.ph page stands in as the agency URL.
            [[city, f"{metadata['name']} jeepneys", f"{PUBLISHER_URL}/{city}", TIMEZONE]],
        ),
        "routes.txt": (
            ["route_id", "agency_id", "route_short_name", "route_long_name", "route_desc", "route_type", "route_color",
             "route_text_color", "continuous_pickup", "continuous_drop_off", "lugar_status", "lugar_source_url"],
            routes,
        ),
        "trips.txt": (["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"], trips),
        "stops.txt": (["stop_id", "stop_name", "stop_desc", "stop_lat", "stop_lon", "location_type"], stops),
        "stop_times.txt": (
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "shape_dist_traveled", "timepoint"],
            stop_times,
        ),
        "shapes.txt": (["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"], shapes),
        "frequencies.txt": (["trip_id", "start_time", "end_time", "headway_secs", "exact_times"], frequencies),
        "calendar.txt": (
            ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
            [[SERVICE_ID, 1, 1, 1, 1, 1, 1, 1, start_date, end_date]],
        ),
        "feed_info.txt": (
            ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version",
             "feed_contact_url", "lugar_notes"],
            [["Lugar.ph", PUBLISHER_URL, "en", start_date, end_date, build_date.isoformat(), CONTACT_URL, FEED_NOTES]],
        ),
        "attributions.txt": (
            ["attribution_id", "organization_name", "is_producer", "attribution_url"],
            [["lugar", "Lugar.ph", 1, PUBLISHER_URL],
             ["osm", "OpenStreetMap contributors (ODbL)", 1, "https://www.openstreetmap.org/copyright"]],
        ),
    }
    if fare_rules:
        # Payment on board, no free transfers. Only the base fare: see FEED_NOTES.
        tables["fare_attributes.txt"] = (
            ["fare_id", "price", "currency_type", "payment_method", "transfers", "agency_id"],
            [[FARE_ID, f"{FARE_BASE_PHP:.2f}", "PHP", 0, 0, city]],
        )
        tables["fare_rules.txt"] = (["fare_id", "route_id"], fare_rules)
    return tables


def export_city(city: str, live: LiveNetwork | None = None, build_date: date | None = None) -> bytes:
    """The city's GTFS feed as a zip. The same network and build date always give the same bytes."""
    build_date = build_date or date.today()
    stamp = (build_date.year, build_date.month, build_date.day, 0, 0, 0)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, (header, rows) in feed_tables(city, live, build_date).items():
            text = io.StringIO()
            writer = csv.writer(text, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
            info = zipfile.ZipInfo(name, stamp)
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.getvalue().encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
