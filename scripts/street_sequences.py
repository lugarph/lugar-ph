"""Draw jeepney lines from a route plan's street sequence.

Route plans describe a line as the streets it takes, in order:
"Centro Balulang – Balulang Road – M. Velez St. – Masterson Ave. – ...".
Each street is matched to named OpenStreetMap ways, and the line is routed
through the corner where each street meets the next one, so the drawn path
turns where the plan says it does. Named places (terminals, markets, malls)
come from a coordinate table.

Names in plans rarely match OpenStreetMap exactly ("CM Recto Ave." is
"Claro M. Recto Avenue", "Max Suniel St." is "Maximo Suniel Street"), so
streets match on their main word, with the words before it allowed to be
initials or short forms. When several streets share a surname, the corner
nearest the line's previous point wins.

The result is still an estimate: the plan gives streets, not turns or stops.
Street geometry is (c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from osm_routes import CACHE_DIR, OVERPASS_URLS, USER_AGENT, Point, densify, km, route_path


CORNER_REACH_KM = 0.12  # streets whose ends come this close are treated as meeting
DETOUR_RATIO, DETOUR_SLACK_KM = 1.6, 1.5  # a waypoint may lengthen the way to the next known place by this much
MAX_OSRM_POINTS = 90  # the public OSRM server rejects very long waypoint lists

STREET_TYPES = {
    "st": "street", "street": "street", "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "rd": "road", "road": "road", "blvd": "boulevard", "boulevard": "boulevard", "hwy": "highway",
    "higway": "highway", "highway": "highway", "dr": "drive", "drive": "drive", "ext": "extension",
    "extn": "extension", "extension": "extension", "bridge": "bridge", "circle": "circle",
    "lane": "lane", "ln": "lane", "diversion": "diversion", "bypass": "bypass",
}
# Words that describe the kind of road rather than name it.
GENERIC = {"street", "avenue", "road", "boulevard", "highway", "drive", "extension", "lane", "circle", "national", "old", "new", "main"}


def fold(text: str) -> str:
    """Lowercase ASCII letters, digits, and single spaces: "Osmeña St." -> "osmena st"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"(\d+)\s+(st|nd|rd|th)\b", r"\1\2", text.lower())  # "8 th" -> "8th"
    text = re.sub(r"(?<=\b[a-z])\.(?=[a-z]\b)", "", text)  # "j.r" -> "jr"
    text = re.sub(r"\bby\s*pass\b", "bypass", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def tokens(name: str) -> list[str]:
    return [STREET_TYPES.get(word, word) for word in fold(name).split()]


def core(name: str) -> list[str]:
    """The naming words of a street, without its type: "C.M. Recto Ave." -> ["cm", "recto"]."""
    words = [word for word in tokens(name) if word not in GENERIC and word not in ("sr", "senior")]
    return words or tokens(name)


def compatible(plan: list[str], osm: list[str]) -> bool:
    """True when a plan's short street name can stand for an OpenStreetMap name.

    The last words must agree ("recto"). Each earlier plan word must be a
    later-or-equal earlier OSM word, a prefix of one ("max" for "maximo"), or
    initials for a run of them ("cm" for "claro m"). OSM words the plan leaves
    out, such as first names, may be skipped ("palma gil" for "j palma gil").
    """
    if not plan or not osm:
        return False
    if plan[-1] != osm[-1] and not (len(plan[-1]) >= 5 and osm[-1].startswith(plan[-1])):
        return False
    earlier = osm[:-1]
    position = 0
    for word in plan[:-1]:
        if position < len(earlier) and (earlier[position] == word or earlier[position].startswith(word)):
            position += 1
            continue
        initials = "".join(item[0] for item in earlier[position : position + len(word)])
        if len(word) <= 3 and initials == word:
            position += len(word)
            continue
        if len(word) == 1 and word in (item[0] for item in earlier[position:]):
            position = next(index for index in range(position, len(earlier)) if earlier[index][0] == word) + 1
            continue
        if len(word) <= 2 and position == len(earlier):
            continue  # the plan gives initials the OSM name leaves out: "V. Castro" for "Castro"
        later = next((index for index in range(position + 1, len(earlier)) if earlier[index] == word), None)
        if len(word) > 2 and later is not None:
            position = later + 1  # the plan leaves out a first name
            continue
        return False
    return True


@dataclass
class Streets:
    """Named ways in a city: node coordinates and each way's nodes, grouped by name."""
    nodes: dict[int, Point]
    ways: dict[str, list[list[int]]]  # OSM name -> node lists
    cores: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cores = {name: core(name) for name in self.ways}
        self._matches: dict[str, list[str]] = {}
        self._pieces: dict[str, list[list[tuple[int, Point]]]] = {}

    def matching(self, name: str) -> list[str]:
        """OSM street names a plan's street name may refer to."""
        if name not in self._matches:
            wanted = core(name)
            # Every compatible street, not just exact matches: the corner and
            # detour checks pick the one the line actually takes.
            self._matches[name] = [osm for osm, words in self.cores.items() if words == wanted or compatible(wanted, words)]
        return self._matches[name]

    def points(self, names: list[str]) -> list[tuple[int, Point]]:
        return [(node, self.nodes[node]) for osm in names for way in self.ways[osm] for node in way]

    def pieces(self, name: str) -> list[list[tuple[int, Point]]]:
        """A street name's ways grouped into connected stretches; one name can label streets in several districts."""
        if name not in self._pieces:
            groups: list[set[int]] = []
            for way in self.ways[name]:
                nodes = set(way)
                touching = [group for group in groups if group & nodes]
                for group in touching:
                    nodes |= group
                    groups.remove(group)
                groups.append(nodes)
            self._pieces[name] = [[(node, self.nodes[node]) for node in group] for group in groups]
        return self._pieces[name]



def fetch_streets(city: str, bbox: tuple[float, float, float, float]) -> Streets:
    """Named roads inside (south, west, north, east), cached per city under scripts/.cache."""
    cache = CACHE_DIR / f"streets-{city}.json"
    if not cache.exists():
        south, west, north, east = bbox
        query = (
            f"[out:json][timeout:180];way[highway][name]({south},{west},{north},{east});"
            "out body;>;out skel qt;"
        )
        data = urllib.parse.urlencode({"data": query}).encode()
        for attempt, url in enumerate([*OVERPASS_URLS, *OVERPASS_URLS]):
            try:
                request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=240) as response:
                    elements = json.load(response)["elements"]
                break
            except OSError as exc:
                print(f"    Overpass {url} failed ({exc}); retrying", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError("All Overpass servers failed")
        nodes = {element["id"]: [element["lon"], element["lat"]] for element in elements if element["type"] == "node"}
        ways: dict[str, list[list[int]]] = {}
        for element in elements:
            if element["type"] == "way":
                for key in ("name", "alt_name", "old_name", "official_name", "short_name"):
                    for value in element.get("tags", {}).get(key, "").split(";"):
                        if value.strip():
                            ways.setdefault(value.strip(), []).append(element["nodes"])
        CACHE_DIR.mkdir(exist_ok=True)
        cache.write_text(json.dumps({"nodes": nodes, "ways": ways}), encoding="utf-8")
    data = json.loads(cache.read_text(encoding="utf-8"))
    return Streets({int(key): value for key, value in data["nodes"].items()}, data["ways"])


def _clean(item: str) -> tuple[str, str]:
    """A sequence item and its parenthesised note: "8 th St. (Nazareth)" -> ("8 th St.", "Nazareth")."""
    note = " ".join(re.findall(r"\(([^)]*)\)", item))
    return re.sub(r"\([^)]*\)?", " ", item).strip(" .–-"), note.strip()


TYPE_WORD = re.compile(r"^(St|Ave|Avenue|Blvd|Road|Rd|Extn|Dr|Drive|Highway|Hwy)\.?$", re.I)


def _unglue(item: str) -> list[str]:
    """Split items missing a dash between them: "Masterson Ave. Vamenta Blvd." -> two streets.

    A street-type word ends a name when a capitalised word follows it, unless
    it opens the item, as in "St. Michael St.".
    """
    words = item.split()
    parts, current = [], []
    for index, word in enumerate(words):
        current.append(word)
        following = words[index + 1] if index + 1 < len(words) else ""
        if index > 0 and TYPE_WORD.match(word) and following[:1].isupper() and not TYPE_WORD.match(following):
            parts.append(" ".join(current))
            current = []
    if current:
        parts.append(" ".join(current))
    return parts


def split_sequence(text: str) -> list[str]:
    """A plan's "A – B - C" text as its items."""
    items = re.split(r"\s+[–—-]+\s+|\s*[–—]\s*|\s+-(?=\S)|(?<=\S)-\s+|(?<=Market)-(?=\S)", text.replace("\xa0", " "))
    return [part.strip() for item in items for part in _unglue(item.strip()) if part.strip(" .–-")]


@dataclass
class Resolved:
    kind: str  # "place" or "street"
    label: str
    point: Point | None = None
    streets: list[str] = field(default_factory=list)


def resolve(item: str, streets: Streets, places: dict[str, Point], aliases: dict[str, str]) -> Resolved | None:
    """What a sequence item names: a known place, or one or more OSM streets."""
    main, note = _clean(item)
    for text in (main, note, item):
        if not text:
            continue
        key = fold(aliases.get(fold(text), text))
        for name, point in places.items():
            if fold(name) == key:
                return Resolved("place", name, point=point)
        matches = streets.matching(aliases.get(fold(text), text))
        if matches:
            return Resolved("street", text, streets=matches)
    return None


def _corner(first: list[tuple[int, Point]], second: list[tuple[int, Point]], near: Point, target: Point | None) -> Point | None:
    """Where two streets meet on the way to the target, choosing the meeting point nearest `near`."""
    shared = {node for node, _ in first} & {node for node, _ in second}
    if shared:
        lookup = dict(first)
        corners = [lookup[node] for node in shared if _on_the_way(lookup[node], near, target)]
        return min(corners, key=lambda point: km(point, near)) if corners else None
    # Streets split by a bridge or roundabout may not share a node: take their closest approach.
    best, best_score = None, math.inf
    for _, a in first:
        for _, b in second:
            gap = km(a, b)
            if gap <= CORNER_REACH_KM and _on_the_way(a, near, target):
                score = gap * 20 + km(a, near)
                if score < best_score:
                    best, best_score = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], score
    return best


def _on_the_way(point: Point, previous: Point, target: Point | None) -> bool:
    """True when passing through the point is not a long detour on the way to the target.

    A plan's "Quirino St." one street after Cogon Market is the one downtown,
    not a Quirino Street in Iponan: going there and back to the next terminal
    would be far longer than the trip itself.
    """
    if target is None:
        return True
    return km(previous, point) + km(point, target) <= DETOUR_RATIO * km(previous, target) + DETOUR_SLACK_KM


def waypoints(sequence: list[str], start: Point | None, end: Point | None, streets: Streets, places: dict[str, Point], aliases: dict[str, str], trace: list | None = None) -> tuple[list[Point], list[str]]:
    """Points to route through, from start to end, and the items that could not be placed.

    Each street contributes the corner where it meets the next street, or the
    point where the line touches it. A terminal with no known position is left
    out, so the line starts or ends at the nearest street the plan names.
    """
    found = [resolve(item, streets, places, aliases) for item in sequence]
    missing = [item for item, match in zip(sequence, found) if match is None]
    resolved = [match for match in found if match is not None]
    if start is None:
        first = next((item for item in resolved if item.kind == "place"), None)
        start = first.point if first else streets.points(resolved[0].streets)[0][1]
    points = [start]
    for index, current in enumerate(resolved):
        if trace is not None:
            trace.append((current.label, len(points)))  # index of the point this item adds, before de-duplication
        if current.kind == "place":
            points.append(current.point)
            continue
        following = resolved[index + 1] if index + 1 < len(resolved) else None
        # The next known place: a terminal, market, or bridge, else the line's end.
        target = next((item.point for item in resolved[index + 1 :] if item.kind == "place"), end)
        here = streets.points(current.streets)
        if following is not None and following.kind == "street":
            corner = _corner(here, streets.points(following.streets), points[-1], target)
            if corner is not None:
                points.append(corner)
                continue
        # No corner found: make sure the line at least touches this street near where it is.
        aim = following.point if following is not None and following.kind == "place" else (target or points[-1])
        candidates = [point for _, point in here if _on_the_way(point, points[-1], target)]
        if not candidates:
            missing.append(f"{current.label} (only found off the route)")
            continue
        points.append(min(candidates, key=lambda point: km(point, points[-1]) + 0.5 * km(point, aim)))
    if end is not None:
        points.append(end)
    if trace is not None:
        trace[:] = [(label, points[index]) for label, index in trace if index < len(points)]
    deduped = [points[0]]
    for point in points[1:]:
        if km(point, deduped[-1]) > 0.02:
            deduped.append(point)
    return deduped, missing


def route_through(points: list[Point]) -> list[Point]:
    """A driving path through the points, in chunks the public OSRM server accepts."""
    path: list[Point] = []
    for start in range(0, len(points) - 1, MAX_OSRM_POINTS - 1):
        chunk = points[start : start + MAX_OSRM_POINTS]
        if len(chunk) < 2:
            break
        coordinates = route_path(chunk)
        path.extend(coordinates if not path else coordinates[1:])
    return densify(path)
