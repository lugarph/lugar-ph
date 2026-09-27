"""Multi-city jeepney trip planning over a stop graph with up to three rides."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from math import asin, ceil, cos, floor, hypot, radians, sin, sqrt
from pathlib import Path


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


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    radius = 6371.0
    dlat, dlng = radians(b_lat - a_lat), radians(b_lng - a_lng)
    value = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(value))


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


def _line(city: str, feature: dict) -> Line:
    coordinates = tuple(tuple(point) for point in feature["geometry"]["coordinates"])
    cumulative = [0.0]
    for first, second in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + distance_km(first[1], first[0], second[1], second[0]))
    properties = feature["properties"]
    return Line(
        city=city, id=properties["id"], number=str(properties["number"]), name=properties["name"],
        color=properties["color"], source_url=properties.get("source_url") or CITY_METADATA[city]["source_url"], status=properties["status"],
        coordinates=coordinates, cumulative_km=tuple(cumulative),
    )


LINES_BY_CITY = {city: tuple(_line(city, feature) for feature in network["features"]) for city, network in NETWORKS.items()}
LINE_BY_ID = {line.id: line for lines in LINES_BY_CITY.values() for line in lines}


def _slice(line: Line, start: int, end: int) -> list[tuple[float, float]]:
    return list(line.coordinates[start : end + 1]) if start <= end else list(reversed(line.coordinates[end : start + 1]))


def _ride_distance(line: Line, start: int, end: int) -> float:
    return abs(line.cumulative_km[end] - line.cumulative_km[start])


def _point_json(point: tuple[float, float], name: str) -> dict:
    return {"name": name, "lng": point[0], "lat": point[1]}


def _leg(line: Line, start: int, end: int) -> dict:
    return {
        "route_id": line.id, "route_number": line.number, "route_name": line.name, "color": line.color,
        "board_near": f"the nearest point on line {line.number}", "alight_near": f"the nearest point on line {line.number}",
        "geometry": {"type": "LineString", "coordinates": _slice(line, start, end)},
        "geometry_status": line.status, "road_distance_km": round(_ride_distance(line, start, end), 2),
    }


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
INF = float("inf")


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
    walks: tuple[float, ...]  # origin walk, each transfer walk, destination walk
    ride_km: float

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

    def cost(self, weights: Weights = DEFAULT_WEIGHTS) -> float:
        transfer_walk = self.walk_km - self.access_walk_km
        return self.ride_km + self.access_walk_km * weights.walk + transfer_walk * weights.transfer_walk + (len(self.rides) - 1) * weights.transfer


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
            lng, lat = graph.point((line_pos, stop_pos))
            nearest = graph.nearest_per_line(lat, lng, MAX_TRANSFER_WALK_KM, exclude_line=line_pos)
            if nearest:
                graph.transfers[(line_pos, stop_pos)] = tuple(nearest)
    return graph


def _scan_line(stop_km: tuple[float, ...], boards: dict[int, float]) -> dict[int, tuple[float, int]]:
    """Cheapest (cost, boarding stop) for alighting at each stop, riding either direction.

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
    ride_km = sum(abs(graph.stop_km[line][alight] - graph.stop_km[line][board]) for line, board, alight in rides)
    return Journey(rides=tuple(rides), walks=tuple(walks), ride_km=ride_km)


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
            for stop, (cost, board) in _scan_line(graph.stop_km[line], costs).items():
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


def _tags(journey: Journey, primary: Journey) -> list[str]:
    tags = []
    if len(journey.rides) < len(primary.rides):
        tags.append("Fewer transfers")
    if journey.walk_km <= primary.walk_km - LESS_WALKING_MIN_KM:
        tags.append("Less walking")
    if journey.minutes <= primary.minutes - FASTER_MIN_MINUTES:
        tags.append("Faster")
    return tags


def _dominated(journey: Journey, shown: list[Journey]) -> bool:
    """True when a shown trip is at least as good on rides, walking, and time."""
    return any(
        len(other.rides) <= len(journey.rides) and other.walk_km <= journey.walk_km and other.minutes <= journey.minutes
        for other in shown
    )


def _line_ids(graph: StopGraph, journey: Journey) -> tuple[str, ...]:
    return tuple(graph.lines[line].id for line, _, _ in journey.rides)


def _itinerary(graph: StopGraph, journey: Journey, city: str, tags: list[str]) -> dict:
    lines = [graph.lines[line] for line, _, _ in journey.rides]
    legs, waypoints, transfers = [], [], []
    for position, (line_pos, board, alight) in enumerate(journey.rides):
        line = lines[position]
        legs.append(_leg(line, graph.stops[line_pos][board], graph.stops[line_pos][alight]))
        board_point = _point_json(graph.point((line_pos, board)), f"Board line {line.number}")
        if position:
            transfers.append({"from": waypoints[-1], "to": board_point, "walk_km": round(journey.walks[position], 2)})
        waypoints.extend([board_point, _point_json(graph.point((line_pos, alight)), f"Alight line {line.number}")])
    return {
        "city": city, "ride_count": len(legs), "tags": tags,
        "lines": [{"id": line.id, "number": line.number, "name": line.name, "color": line.color} for line in lines],
        "legs": legs, "waypoints": waypoints, "transfers": transfers,
        "access": {"origin_walk_km": round(journey.walks[0], 2), "destination_walk_km": round(journey.walks[-1], 2), "transfer_walk_km": round(journey.walk_km - journey.access_walk_km, 2)},
        "geometry_type": "published_or_inferred_road_corridor",
        "road_distance_km": round(journey.ride_km + journey.walk_km, 2),
        "ride_km": round(journey.ride_km, 2), "walk_km": round(journey.walk_km, 2),
        "ride_minutes": journey.ride_minutes, "duration_minutes": journey.minutes,
        "source_url": lines[0].source_url,
        "note": "Walk to the nearest mapped jeepney corridor. Confirm the signboard, direction, and current operation locally before boarding.",
    }


def plan_trips(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float, city: str = "bacolod") -> list[dict]:
    """The recommended itinerary first, then up to two distinct alternatives."""
    if city not in LINES_BY_CITY or distance_km(origin_lat, origin_lng, destination_lat, destination_lng) < 0.25:
        return []
    graph = _graph(city)
    origin, destination = (origin_lat, origin_lng), (destination_lat, destination_lng)
    by_rides = _search(graph, origin, destination, DEFAULT_WEIGHTS)
    if not by_rides:
        return []
    cheapest = min(journey.cost() for journey in by_rides.values())
    primary = next(journey for _, journey in sorted(by_rides.items()) if journey.cost() <= cheapest * PREFER_FEWER_RIDES_RATIO)
    candidates = [*by_rides.values(), *_search(graph, origin, destination, LOW_WALK_WEIGHTS).values()]
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
    return [_itinerary(graph, journey, city, _tags(journey, primary)) for journey in shown]


def match_trip(origin_lat: float, origin_lng: float, destination_lat: float, destination_lng: float, city: str = "bacolod") -> dict | None:
    trips = plan_trips(origin_lat, origin_lng, destination_lat, destination_lng, city)
    return trips[0] if trips else None


def public_network(city: str = "bacolod") -> dict:
    return NETWORKS[city]


def route_ids() -> set[str]:
    return set(LINE_BY_ID)
