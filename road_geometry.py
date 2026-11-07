"""Reviewed MVP street traces for the two supported Bacolod trip segments.

The supplied LPTRP diagram establishes the line topology. Coordinates come
from OpenStreetMap road routing through its named landmarks. These are
inferred road alignments, not surveyed jeepney tracks or designated stops.
"""

from __future__ import annotations

import json
from pathlib import Path


GEOMETRY_FILE = Path(__file__).resolve().parent / "data" / "road_segments.geojson"
if not GEOMETRY_FILE.exists():
    raise SystemExit("Route data is missing. It lives in a Git submodule; run: git submodule update --init")
_features = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))["features"]
SEGMENTS = {feature["properties"]["id"]: feature for feature in _features}


def trip_segment(segment_id: str) -> dict:
    return SEGMENTS[segment_id]
