"""Combine checked-in routes with the latest approved database revisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select

from models import RoutePublication
from transit_network import Anchor, NETWORKS, StopGraph, _line, build_graph


def merged_network(city: str, overlays: tuple[tuple[str, str | None], ...]) -> dict:
    """A null overlay removes a route, including one already synced into Git."""
    updates = dict(overlays)
    features = []
    for feature in NETWORKS[city]["features"]:
        slug = feature["properties"]["id"]
        if slug in updates:
            replacement = updates.pop(slug)
            if replacement is not None:
                features.append(json.loads(replacement))
        else:
            features.append(feature)
    features.extend(json.loads(value) for value in updates.values() if value is not None)
    return {**NETWORKS[city], "features": features}


@dataclass(frozen=True)
class LiveNetwork:
    network: dict
    graph: StopGraph
    anchors: tuple[Anchor, ...]


@lru_cache(maxsize=24)
def _build(city: str, overlays: tuple[tuple[str, str | None], ...]) -> LiveNetwork:
    network = merged_network(city, overlays)
    lines = tuple(_line(city, feature) for feature in network["features"])
    anchors = tuple({anchor.name: anchor for line in lines for anchor in (*line.anchors, *line.return_anchors)}.values())
    return LiveNetwork(network, build_graph(lines), anchors)


def load_live_network(city: str, session) -> LiveNetwork:
    # Read each request so another Vercel instance's approval is visible immediately.
    publications = session.scalars(select(RoutePublication).where(RoutePublication.city == city)).all()
    overlays = tuple(sorted((item.route_slug, item.feature_json) for item in publications))
    return _build(city, overlays)
