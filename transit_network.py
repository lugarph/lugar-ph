"""Multi-city jeepney trip planning over a stop graph with up to three rides."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import asin, ceil, cos, floor, hypot, radians, sin, sqrt
from pathlib import Path
from typing import Callable


DATA_DIR = Path(__file__).resolve().parent / "data"
CITY_METADATA = {
    "bacolod": {"name": "Bacolod City", "center": [10.6825, 122.9545], "zoom": 13, "source_label": "Bacolod LPTRP", "source_url": "https://ncts.upd.edu.ph/tssp/wp-content/uploads/2024/01/TSSP2023-09-Tiglao-1.pdf"},
    "iloilo": {"name": "Iloilo City", "center": [10.7130, 122.5570], "zoom": 13, "source_label": "Iloilo LPTRP 2023", "source_url": "https://ilonggoengineer.com/wp-content/uploads/2025/04/mc-2023-036.pdf"},
    "cebu": {"name": "Cebu City", "center": [10.3157, 123.8854], "zoom": 13, "source_label": "Cebu DOTC GTFS", "source_url": "https://www.transit.land/feeds/f-wcb4-cebu~dotc"},
    "tacloban": {"name": "Tacloban City", "center": [11.2440, 125.0000], "zoom": 13, "source_label": "Tacloban LPTRP 2024", "source_url": "https://tacloban.gov.ph/ordinance/page/5/"},
}
NETWORK_FILES = {
    "bacolod": DATA_DIR / "jeepney_network.geojson",
    "iloilo": DATA_DIR / "iloilo_jeepney_network.geojson",
    "cebu": DATA_DIR / "cebu_jeepney_network.geojson",
    "tacloban": DATA_DIR / "tacloban_jeepney_network.geojson",
}
NETWORKS = {city: json.loads(path.read_text(encoding="utf-8")) for city, path in NETWORK_FILES.items()}
NETWORK = NETWORKS["bacolod"]

# A shape that ends where it starts is a GTFS-style round trip drawn in the
# direction of travel, so it may only be ridden forward.
ROUND_TRIP_GAP_KM = 0.5


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    radius = 6371.0
    dlat, dlng = radians(b_lat - a_lat), radians(b_lng - a_lng)
    value = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(value))


@dataclass(frozen=True)
class Anchor:
    name: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Line:
    city: str
    id: str
    number: str
    name: str
    color: str
    source_url: str | None
    status: str
    coordinates: tuple[tuple[float, float], ...]
    cumulative_km: tuple[float, ...]
    anchors: tuple[Anchor, ...] = ()  # published landmarks, in the order the geometry visits them
    round_trip: bool = False


def _place_name(name: str) -> str:
    # Source data title-cases acronyms ("Sm", "Bgc").
    return name.upper() if len(name) <= 3 else name


def _line(city: str, feature: dict) -> Line:
    coordinates = tuple(tuple(point) for point in feature["geometry"]["coordinates"])
    cumulative = [0.0]
    for first, second in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + distance_km(first[1], first[0], second[1], second[0]))
    properties = feature["properties"]
    start, end = coordinates[0], coordinates[-1]
    return Line(
        city=city, id=properties["id"], number=str(properties["number"]), name=properties["name"],
        color=properties["color"], source_url=properties.get("source_url") or CITY_METADATA[city]["source_url"], status=properties["status"],
        coordinates=coordinates, cumulative_km=tuple(cumulative),
        anchors=tuple(
            Anchor(_place_name(anchor["name"]), anchor["lat"], anchor["lng"])
            for anchor in properties.get("anchors", []) if "endpoint" not in anchor["name"]
        ),
        round_trip=distance_km(start[1], start[0], end[1], end[0]) < ROUND_TRIP_GAP_KM,
    )


LINES_BY_CITY = {city: tuple(_line(city, feature) for feature in network["features"]) for city, network in NETWORKS.items()}
LINE_BY_ID = {line.id: line for lines in LINES_BY_CITY.values() for line in lines}
LANDMARKS_BY_CITY = {
    city: tuple({anchor.name: anchor for line in lines for anchor in line.anchors}.values())
    for city, lines in LINES_BY_CITY.items()
}


def _slice(line: Line, start: int, end: int) -> list[tuple[float, float]]:
    return list(line.coordinates[start : end + 1]) if start <= end else list(reversed(line.coordinates[end : start + 1]))


def _point_json(point: tuple[float, float], name: str) -> dict:
    return {"name": name, "lng": point[0], "lat": point[1]}


# Trip planning is a round-based search (RAPTOR-style) over a stop graph: each
# line is resampled into stops, stops on different lines within a short walk
# are linked as transfers, and round r finds the cheapest way to reach every
# stop using exactly r rides. Jeepneys run on frequency, not timetables, so the
# search minimises a generalised cost in ride-km equivalents instead of time.
WALK_WEIGHT = 2.2  # per km walked to the first line or from the last one
TRANSFER_WALK_WEIGHT = 3.0  # per km walked between lines
TRANSFER_PENALTY = 2.0  # flat cost of waiting for and boarding another jeepney
MAX_ACCESS_WALK_KM = 0.75
MAX_TRANSFER_WALK_KM = 0.32
MIN_RIDE_KM = 0.25
MAX_RIDES = 3
STOP_SPACING_KM = 0.1
GRID_DEGREES = 0.003  # ~0.33 km cells for the spatial stop index
PREFER_FEWER_RIDES_RATIO = 1.3  # fewer rides win while within 30% of the cheapest trip
ALTERNATIVE_MAX_RATIO = 1.8
MAX_ALTERNATIVES = 2
LESS_WALKING_MIN_KM = 0.15
FASTER_MIN_MINUTES = 3
RIDE_KMH, WALK_KMH, BOARDING_MINUTES, TRANSFER_MINUTES = 12, 4.8, 6, 8
STRAIGHT_LINE_DETOUR = 1.25  # street walks are longer than the crow flies when no router answer is available
LANDMARK_RADIUS_KM = 0.35
NEAREST_LINE_SEARCH_KM = 5.0
# LTFRB regular fare for traditional jeepneys, effective 28 September 2026.
FARE_BASE_PHP, FARE_BASE_KM, FARE_PER_KM_PHP = 14, 4, 2
INF = float("inf")

# (walk starts, walk ends) as (lat, lng) -> {"km": matrix, "source_names": [...], "destination_names": [...]}
WalkMatrix = Callable[[list[tuple[float, float]], list[tuple[float, float]]], "dict | None"]


@dataclass(frozen=True)
class Weights:
    walk: float = WALK_WEIGHT
    transfer_walk: float = TRANSFER_WALK_WEIGHT
    transfer: float = TRANSFER_PENALTY


DEFAULT_WEIGHTS = Weights()
# A second search with walking made expensive surfaces "less walking" alternatives.
LOW_WALK_WEIGHTS = Weights(walk=WALK_WEIGHT * 4, transfer_walk=TRANSFER_WALK_WEIGHT * 4)

Stop = tuple[int, int]  # (line position in the city, stop position on that line)


@dataclass
class StopGraph:
    lines: tuple[Line, ...]
    stops: tuple[tuple[int, ...], ...]  # coordinate indexes used as stops, per line
    stop_km: tuple[tuple[float, ...], ...]  # distance along the line at each stop
    grid: dict[tuple[int, int], tuple[Stop, ...]]
    transfers: dict[Stop, tuple[tuple[float, int, int], ...]] = field(default_factory=dict)

    def point(self, stop: Stop) -> tuple[float, float]:
        line, index = stop
        return self.lines[line].coordinates[self.stops[line][index]]

    def latlng(self, stop: Stop) -> tuple[float, float]:
        lng, lat = self.point(stop)
        return lat, lng

    def nearby(self, lat: float, lng: float, radius_km: float) -> list[tuple[float, int, int]]:
        row, col = _cell(lat, lng)
        reach = ceil(radius_km / (GRID_DEGREES * 108))  # cells to cover the radius, with slack for latitude
        # Equirectangular distance is exact enough at city scale and much cheaper than haversine.
        lat_km, lng_km = 110.57, 111.32 * cos(radians(lat))
        found = []
        for d_row in range(-reach, reach + 1):
            for d_col in range(-reach, reach + 1):
                for stop in self.grid.get((row + d_row, col + d_col), ()):
                    point = self.point(stop)
                    walk = hypot((point[1] - lat) * lat_km, (point[0] - lng) * lng_km)
                    if walk <= radius_km:
                        found.append((walk, *stop))
        return found

    def nearest_per_line(self, lat: float, lng: float, radius_km: float, exclude_line: int = -1) -> list[tuple[float, int, int]]:
        """The closest stop of each line within reach: riders board where they meet a line, not further along it."""
        nearest: dict[int, tuple[float, int, int]] = {}
        for walk, line, stop in self.nearby(lat, lng, radius_km):
            if line != exclude_line and walk < nearest.get(line, (INF,))[0]:
                nearest[line] = (walk, line, stop)
        return list(nearest.values())


@dataclass(frozen=True)
class Label:
    """Cheapest known arrival at a stop after alighting in one search round."""

    cost: float
    board: int  # stop on the same line where this ride was boarded
    prev: Stop | None  # where the previous ride was left; None means walked from the origin
    walk_km: float  # walk from the origin or the previous stop to the boarding stop


@dataclass(frozen=True)
class Journey:
    rides: tuple[tuple[int, int, int], ...]  # (line, board stop, alight stop)
    ride_kms: tuple[float, ...]
    straight_walks: tuple[float, ...]  # origin walk, each transfer walk, destination walk
    street_walks: tuple[float | None, ...] | None = None  # the same walks along streets, when routed

    @property
    def walks(self) -> tuple[float, ...]:
        street = self.street_walks or (None,) * len(self.straight_walks)
        return tuple(routed if routed is not None else straight * STRAIGHT_LINE_DETOUR for straight, routed in zip(self.straight_walks, street))

    @property
    def ride_km(self) -> float:
        return sum(self.ride_kms)

    @property
    def access_walk_km(self) -> float:
        return self.walks[0] + self.walks[-1]

    @property
    def walk_km(self) -> float:
        return sum(self.walks)

    @property
    def ride_minutes(self) -> int:
        return max(6, round(self.ride_km / RIDE_KMH * 60 + BOARDING_MINUTES + TRANSFER_MINUTES * (len(self.rides) - 1)))

    @property
    def minutes(self) -> int:
        return self.ride_minutes + round(self.walk_km / WALK_KMH * 60)

    @property
    def fare_php(self) -> int:
        return sum(_fare(km) for km in self.ride_kms)

    def cost(self, weights: Weights = DEFAULT_WEIGHTS) -> float:
        transfer_walk = self.walk_km - self.access_walk_km
        return self.ride_km + self.access_walk_km * weights.walk + transfer_walk * weights.transfer_walk + (len(self.rides) - 1) * weights.transfer


def _fare(ride_km: float) -> int:
    return FARE_BASE_PHP + FARE_PER_KM_PHP * ceil(round(max(0.0, ride_km - FARE_BASE_KM), 3))


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return floor(lat / GRID_DEGREES), floor(lng / GRID_DEGREES)


def _stop_indexes(line: Line) -> tuple[int, ...]:
    indexes, next_km = [0], STOP_SPACING_KM
    for index, km in enumerate(line.cumulative_km):
        if km >= next_km:
            indexes.append(index)
            next_km = km + STOP_SPACING_KM
    if indexes[-1] != len(line.coordinates) - 1:
        indexes.append(len(line.coordinates) - 1)
    return tuple(indexes)


@lru_cache(maxsize=None)
def _graph(city: str) -> StopGraph:
    lines = LINES_BY_CITY[city]
    stops = tuple(_stop_indexes(line) for line in lines)
    grid: dict[tuple[int, int], list[Stop]] = defaultdict(list)
    for line_pos, (line, indexes) in enumerate(zip(lines, stops)):
        for stop_pos, coordinate_index in enumerate(indexes):
            lng, lat = line.coordinates[coordinate_index]
            grid[_cell(lat, lng)].append((line_pos, stop_pos))
    graph = StopGraph(
        lines=lines, stops=stops,
        stop_km=tuple(tuple(line.cumulative_km[index] for index in indexes) for line, indexes in zip(lines, stops)),
        grid={cell: tuple(members) for cell, members in grid.items()},
    )
    for line_pos, indexes in enumerate(stops):
        for stop_pos in range(len(indexes)):
            lat, lng = graph.latlng((line_pos, stop_pos))
            nearest = graph.nearest_per_line(lat, lng, MAX_TRANSFER_WALK_KM, exclude_line=line_pos)
            if nearest:
                graph.transfers[(line_pos, stop_pos)] = tuple(nearest)
    return graph


def _scan_line(stop_km: tuple[float, ...], boards: dict[int, float], forward_only: bool = False) -> dict[int, tuple[float, int]]:
    """Cheapest (cost, boarding stop) for alighting at each stop.

    Riding from i to j costs board[i] + |km[j] - km[i]|, so a sweep in each
    direction only needs the running minimum of board[i] -/+ km[i] over stops
    at least MIN_RIDE_KM behind the current one.
    """
    count = len(stop_km)
    board = [boards.get(index, INF) for index in range(count)]
    best = [(INF, -1)] * count
    running, running_stop, index = INF, -1, 0
    for stop in range(count):
        while index < count and stop_km[index] <= stop_km[stop] - MIN_RIDE_KM:
            if board[index] - stop_km[index] < running:
                running, running_stop = board[index] - stop_km[index], index
            index += 1
        if running + stop_km[stop] < best[stop][0]:
            best[stop] = (running + stop_km[stop], running_stop)
    if not forward_only:
        running, running_stop, index = INF, -1, count - 1
        for stop in reversed(range(count)):
            while index >= 0 and stop_km[index] >= stop_km[stop] + MIN_RIDE_KM:
                if board[index] + stop_km[index] < running:
                    running, running_stop = board[index] + stop_km[index], index
                index -= 1
            if running - stop_km[stop] < best[stop][0]:
                best[stop] = (running - stop_km[stop], running_stop)
    return {stop: value for stop, value in enumerate(best) if value[0] < INF}


def _journey(graph: StopGraph, rounds: list[dict[Stop, Label]], stop: Stop, end_walk: float) -> Journey:
    rides, walks = [], [end_walk]
    for arrivals in reversed(rounds):
        label = arrivals[stop]
        rides.append((stop[0], label.board, stop[1]))
        walks.append(label.walk_km)
        if label.prev is None:
            break
        stop = label.prev
    rides.reverse()
    walks.reverse()
    ride_kms = tuple(abs(graph.stop_km[line][alight] - graph.stop_km[line][board]) for line, board, alight in rides)
    return Journey(rides=tuple(rides), ride_kms=ride_kms, straight_walks=tuple(walks))


def _search(graph: StopGraph, origin: tuple[float, float], destination: tuple[float, float], weights: Weights) -> dict[int, Journey]:
    """Cheapest journey for each ride count from 1 to MAX_RIDES."""
    egress = graph.nearest_per_line(*destination, MAX_ACCESS_WALK_KM)
    boards: dict[int, dict[int, tuple[float, Stop | None, float]]] = defaultdict(dict)
    for walk, line, stop in graph.nearest_per_line(*origin, MAX_ACCESS_WALK_KM):
        boards[line][stop] = (walk * weights.walk, None, walk)
    rounds: list[dict[Stop, Label]] = []
    journeys: dict[int, Journey] = {}
    for rides in range(1, MAX_RIDES + 1):
        if not boards or not egress:
            break
        arrivals: dict[Stop, Label] = {}
        for line, line_boards in boards.items():
            costs = {stop: entry[0] for stop, entry in line_boards.items()}
            for stop, (cost, board) in _scan_line(graph.stop_km[line], costs, graph.lines[line].round_trip).items():
                _, prev, walk = line_boards[board]
                arrivals[(line, stop)] = Label(cost, board, prev, walk)
        rounds.append(arrivals)
        finish = min(
            ((arrivals[(line, stop)].cost + walk * weights.walk, (line, stop), walk) for walk, line, stop in egress if (line, stop) in arrivals),
            default=None,
        )
        if finish:
            journeys[rides] = _journey(graph, rounds, finish[1], finish[2])
        boards = defaultdict(dict)
        for stop, label in arrivals.items():
            for walk, line, other_stop in graph.transfers.get(stop, ()):
                cost = label.cost + walk * weights.transfer_walk + weights.transfer
                if cost < boards[line].get(other_stop, (INF,))[0]:
                    boards[line][other_stop] = (cost, stop, walk)
    return journeys


def _walk_ends(graph: StopGraph, journey: Journey, origin: tuple[float, float], destination: tuple[float, float]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """(start, end) of every walk in the journey, as (lat, lng)."""
    starts = [origin] + [graph.latlng((line, alight)) for line, _, alight in journey.rides]
    ends = [graph.latlng((line, board)) for line, board, _ in journey.rides] + [destination]
    return list(zip(starts, ends))


def _with_street_walks(
    graph: StopGraph, journeys: list[Journey], origin: tuple[float, float], destination: tuple[float, float], walk_matrix: WalkMatrix,
) -> tuple[list[Journey], dict[tuple[float, float], str]]:
    """Replace straight-line walks with street distances from one many-to-many router call."""
    sources: dict[tuple[float, float], int] = {}
    targets: dict[tuple[float, float], int] = {}
    for journey in journeys:
        for start, end in _walk_ends(graph, journey, origin, destination):
            sources.setdefault(start, len(sources))
            targets.setdefault(end, len(targets))
    result = walk_matrix(list(sources), list(targets))
    if not result:
        return journeys, {}
    streets = {point: name for point, name in zip(sources, result["source_names"]) if name}
    streets.update({point: name for point, name in zip(targets, result["destination_names"]) if name})
    routed = [
        replace(journey, street_walks=tuple(result["km"][sources[start]][targets[end]] for start, end in _walk_ends(graph, journey, origin, destination)))
        for journey in journeys
    ]
    return routed, streets


def _tags(journey: Journey, primary: Journey) -> list[str]:
    tags = []
    if len(journey.rides) < len(primary.rides):
        tags.append("Fewer transfers")
    if journey.walk_km <= primary.walk_km - LESS_WALKING_MIN_KM:
        tags.append("Less walking")
    if journey.minutes <= primary.minutes - FASTER_MIN_MINUTES:
        tags.append("Faster")
    return tags


def _highlight(primary: Journey, shown: list[Journey]) -> str:
    """Why the recommended trip leads the list."""
    if all(primary.minutes <= other.minutes for other in shown):
        return "Fastest"
    if all(len(primary.rides) <= len(other.rides) for other in shown):
        return "Fewest transfers"
    if all(primary.walk_km <= other.walk_km for other in shown):
        return "Least walking"
    return "Recommended"


def _dominated(journey: Journey, shown: list[Journey]) -> bool:
    """True when a shown trip is at least as good on rides, walking, and time."""
    return any(
        len(other.rides) <= len(journey.rides) and other.walk_km <= journey.walk_km and other.minutes <= journey.minutes
        for other in shown
    )


def _line_ids(graph: StopGraph, journey: Journey) -> tuple[str, ...]:
    return tuple(graph.lines[line].id for line, _, _ in journey.rides)


def _landmark(city: str, lat: float, lng: float) -> str | None:
    nearest = min(
        ((distance_km(lat, lng, anchor.lat, anchor.lng), anchor.name) for anchor in LANDMARKS_BY_CITY[city]),
        default=(INF, None),
    )
    return nearest[1] if nearest[0] <= LANDMARK_RADIUS_KM else None


def _stop_json(city: str, point: tuple[float, float], streets: dict[tuple[float, float], str]) -> dict:
    lat, lng = point
    landmark, street = _landmark(city, lat, lng), streets.get(point)
    if landmark and street:
        label = f"near {landmark}, {street}"
    elif landmark or street:
        label = f"near {landmark}" if landmark else f"on {street}"
    else:
        label = None
    return {"lat": lat, "lng": lng, "landmark": landmark, "street": street, "label": label}


def _signboard(line: Line) -> str:
    """The route name as painted on the jeepney, without planning qualifiers."""
    name = line.name.split(" via ")[0]
    return name[: -len(" Loop")] if name.endswith(" Loop") else name


def _heading(line: Line, forward: bool) -> str | None:
    if line.round_trip or len(line.anchors) < 2:
        return None
    return (line.anchors[-1] if forward else line.anchors[0]).name


def _itinerary(graph: StopGraph, journey: Journey, city: str, streets: dict[tuple[float, float], str]) -> dict:
    lines = [graph.lines[line] for line, _, _ in journey.rides]
    walks = journey.walks
    legs, waypoints, transfers = [], [], []
    for position, ((line_pos, board, alight), ride_km) in enumerate(zip(journey.rides, journey.ride_kms)):
        line = lines[position]
        board_stop = _stop_json(city, graph.latlng((line_pos, board)), streets)
        alight_stop = _stop_json(city, graph.latlng((line_pos, alight)), streets)
        start, end = graph.stops[line_pos][board], graph.stops[line_pos][alight]
        legs.append({
            "route_id": line.id, "route_number": line.number, "route_name": line.name, "color": line.color,
            "signboard": _signboard(line), "heading": _heading(line, alight > board), "round_trip": line.round_trip,
            "board": board_stop, "alight": alight_stop,
            "geometry": {"type": "LineString", "coordinates": _slice(line, start, end)},
            "geometry_status": line.status, "road_distance_km": round(ride_km, 2),
            "ride_minutes": max(1, round(ride_km / RIDE_KMH * 60)), "fare_php": _fare(ride_km),
        })
        board_point = _point_json(graph.point((line_pos, board)), f"Board line {line.number}")
        if position:
            transfers.append({"from": waypoints[-1], "to": board_point, "walk_km": round(walks[position], 2)})
        waypoints.extend([board_point, _point_json(graph.point((line_pos, alight)), f"Get off line {line.number}")])
    return {
        "city": city, "ride_count": len(legs),
        "lines": [{"id": line.id, "number": line.number, "name": line.name, "color": line.color} for line in lines],
        "legs": legs, "waypoints": waypoints, "transfers": transfers,
        "access": {"origin_walk_km": round(walks[0], 2), "destination_walk_km": round(walks[-1], 2), "transfer_walk_km": round(journey.walk_km - journey.access_walk_km, 2)},
        "walk_basis": "street" if journey.street_walks and None not in journey.street_walks else "estimated",
        "geometry_type": "published_or_inferred_road_corridor",
        "road_distance_km": round(journey.ride_km + journey.walk_km, 2),
        "ride_km": round(journey.ride_km, 2), "walk_km": round(journey.walk_km, 2),
        "ride_minutes": journey.ride_minutes, "duration_minutes": journey.minutes, "fare_php": journey.fare_php,
        "source_url": lines[0].source_url,
        "note": "Routes are inferred from published route plans. Confirm the signboard and direction before boarding.",
    }


def plan_trips(
    origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float,
    city: str = "bacolod", walk_matrix: WalkMatrix | None = None,
) -> list[dict]:
    """The recommended itinerary first, then up to two distinct alternatives.

    With a walk_matrix, candidate trips are compared on street walking
    distances instead of straight-line estimates.
    """
    if city not in LINES_BY_CITY or distance_km(origin_lat, origin_lng, destination_lat, destination_lng) < 0.25:
        return []
    graph = _graph(city)
    origin, destination = (origin_lat, origin_lng), (destination_lat, destination_lng)
    found = [*_search(graph, origin, destination, DEFAULT_WEIGHTS).values(), *_search(graph, origin, destination, LOW_WALK_WEIGHTS).values()]
    candidates = list({journey.rides: journey for journey in found}.values())
    if not candidates:
        return []
    streets: dict[tuple[float, float], str] = {}
    if walk_matrix:
        candidates, streets = _with_street_walks(graph, candidates, origin, destination, walk_matrix)
    cheapest = min(journey.cost() for journey in candidates)
    primary = min(
        (journey for journey in candidates if journey.cost() <= cheapest * PREFER_FEWER_RIDES_RATIO),
        key=lambda journey: (len(journey.rides), journey.cost()),
    )
    shown = [primary]
    for journey in sorted(candidates, key=lambda item: item.cost()):
        if len(shown) > MAX_ALTERNATIVES:
            break
        if (
            _tags(journey, primary)
            and journey.cost() <= primary.cost() * ALTERNATIVE_MAX_RATIO
            and _line_ids(graph, journey) not in {_line_ids(graph, other) for other in shown}
            and not _dominated(journey, shown)
        ):
            shown.append(journey)
    # Recommended first, then alternatives from quickest to slowest.
    shown[1:] = sorted(shown[1:], key=lambda journey: (journey.minutes, journey.walk_km))
    trips = []
    for journey in shown:
        trip = _itinerary(graph, journey, city, streets)
        trip["tags"] = _tags(journey, primary)
        # A lone route has nothing to be "fastest" against.
        trip["highlight"] = _highlight(primary, shown) if journey is primary and len(shown) > 1 else None
        trip["compared_to_best"] = None if journey is primary else {
            "minutes": journey.minutes - primary.minutes,
            "walk_m": round((journey.walk_km - primary.walk_km) * 1000),
            "fare_php": journey.fare_php - primary.fare_php,
            "rides": len(journey.rides) - len(primary.rides),
        }
        trips.append(trip)
    return trips


def match_trip(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float, city: str = "bacolod") -> dict | None:
    trips = plan_trips(origin_lat, origin_lng, destination_lat, destination_lng, city)
    return trips[0] if trips else None


def _nearest_line_point(graph: StopGraph, lat: float, lng: float) -> dict | None:
    walk, line, stop = min(
        (distance_km(lat, lng, *graph.latlng((line, stop))), line, stop)
        for line, indexes in enumerate(graph.stops) for stop in range(len(indexes))
    )
    if walk > NEAREST_LINE_SEARCH_KM:
        return None
    point_lat, point_lng = graph.latlng((line, stop))
    return {"lat": point_lat, "lng": point_lng, "walk_km": round(walk, 2), "line_number": graph.lines[line].number}


def trip_help(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float, city: str = "bacolod") -> dict:
    """Why no trip was planned, with the nearest mapped line to each pin."""
    if distance_km(origin_lat, origin_lng, destination_lat, destination_lng) < 0.25:
        return {"reason": "too_close", "origin": None, "destination": None}
    graph = _graph(city)
    origin = _nearest_line_point(graph, origin_lat, origin_lng)
    destination = _nearest_line_point(graph, destination_lat, destination_lng)
    far = [
        name for name, nearest in (("origin", origin), ("destination", destination))
        if nearest is None or nearest["walk_km"] > MAX_ACCESS_WALK_KM
    ]
    reason = "no_connection" if not far else "both_far" if len(far) == 2 else f"{far[0]}_far"
    return {"reason": reason, "origin": origin, "destination": destination}


def landmarks(city: str = "bacolod") -> list[dict]:
    """Named places along the city's jeepney lines, for instant search suggestions."""
    return [{"name": anchor.name, "lat": anchor.lat, "lng": anchor.lng} for anchor in sorted(LANDMARKS_BY_CITY[city], key=lambda anchor: anchor.name)]


def public_network(city: str = "bacolod") -> dict:
    return NETWORKS[city]


def route_ids() -> set[str]:
    return set(LINE_BY_ID)
