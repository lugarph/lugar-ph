"""Corrections survive rebuilds, and an approved line can't hide a later fix in the routes repo."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from live_network import merged_network
from models import Base, RoutePublication, RouteRevision
from transit_network import NETWORKS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import osm_routes  # noqa: E402
import sync_approved_routes  # noqa: E402

CITY = "naga"


def feature(line_id, status="inferred_from_official_route_structure", path=((123.18, 13.62), (123.19, 13.63))):
    return {"type": "Feature",
            "properties": {"id": line_id, "number": "1", "name": "A \u2013 B", "color": "#2563eb", "status": status,
                           "distance_km": 1.5, "anchors": []},
            "geometry": {"type": "LineString", "coordinates": [list(point) for point in path]}}


def write_file(path, *features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": list(features)}), encoding="utf-8")


def read_file(path):
    return {item["properties"]["id"]: item for item in json.loads(path.read_text(encoding="utf-8"))["features"]}


@contextmanager
def database():
    with TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'routes.db'}")
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            yield session
        engine.dispose()


def publish(session, line, published):
    revision = RouteRevision(city=CITY, route_slug=line, feature_json=json.dumps(published) if published else None,
                             action="approved", actor="test", note="test")
    session.add(revision)
    session.flush()
    session.add(RoutePublication(city=CITY, route_slug=line, revision_id=revision.id,
                                 feature_json=json.dumps(published) if published else None))
    session.commit()


class TestRebuildKeepsCorrections:
    def test_corrected_line_survives_and_others_are_replaced(self, tmp_path):
        path = tmp_path / "city.geojson"
        fixed = feature("fixed", status="community_verified", path=((123.2, 13.7), (123.21, 13.71)))
        write_file(path, fixed, feature("plain"), feature("added", status="community_verified"))
        rebuilt_plain = feature("plain", path=((123.3, 13.8), (123.31, 13.81)))

        osm_routes.write_network(path, [feature("fixed"), rebuilt_plain])

        stored = read_file(path)
        assert stored["fixed"] == fixed
        assert stored["plain"] == rebuilt_plain
        assert "added" in stored, "a line only people added isn't in the generated list, and must stay"

    def test_first_build_of_a_new_city_writes_the_file(self, tmp_path):
        path = tmp_path / "new.geojson"
        osm_routes.write_network(path, [feature("one")])
        assert list(read_file(path)) == ["one"]

    def test_output_is_the_routes_repo_format(self, tmp_path):
        path = tmp_path / "city.geojson"
        osm_routes.write_network(path, [feature("one")])
        assert "[123.18, 13.62],\n" in path.read_text(encoding="utf-8")

    def test_osm_import_skips_a_corrected_line(self, tmp_path):
        path = tmp_path / "city.geojson"
        fixed = feature("fixed", status="community_verified")
        write_file(path, fixed)
        with patch.object(osm_routes, "fetch_relations", return_value={}), patch.object(osm_routes, "circuit") as circuit:
            osm_routes.overlay(path, {"fixed": ([1], None, None)})
        circuit.assert_not_called()
        assert read_file(path)["fixed"] == fixed


class TestPrune:
    def run(self, tmp_path, session, *file_features, check=False):
        path = tmp_path / "naga.geojson"
        write_file(path, *file_features)
        with patch.dict(sync_approved_routes.NETWORK_FILES, {CITY: path}):
            return sync_approved_routes.prune_publications(session, [CITY], check=check)

    def test_retires_only_what_the_file_has_caught_up_with(self, tmp_path):
        synced, unsynced = feature("synced", status="community_verified"), feature("unsynced", status="community_verified")
        with database() as session:
            publish(session, "synced", synced)
            publish(session, "unsynced", unsynced)
            publish(session, "gone", None)
            publish(session, "still-there", None)
            retired, kept = self.run(tmp_path, session, synced, feature("unsynced"), feature("still-there"))
            assert sorted(retired) == ["naga/gone", "naga/synced"]
            assert sorted(kept) == ["naga/still-there", "naga/unsynced"]
            left = {item.route_slug for item in session.query(RoutePublication).all()}
            assert left == {"still-there", "unsynced"}
            assert session.query(RouteRevision).count() == 4, "history is never deleted"

    def test_check_changes_nothing(self, tmp_path):
        synced = feature("synced", status="community_verified")
        with database() as session:
            publish(session, "synced", synced)
            retired, _ = self.run(tmp_path, session, synced, check=True)
            assert retired == ["naga/synced"]
            assert session.query(RoutePublication).count() == 1

    def test_a_later_fix_in_the_file_shows_once_the_publication_is_retired(self, tmp_path):
        line = NETWORKS[CITY]["features"][0]
        slug = line["properties"]["id"]
        approved = {**line, "properties": {**line["properties"], "name": "Approved in the app"}}
        fixed_later = {**line, "properties": {**line["properties"], "name": "Fixed in the routes repo"}}
        name = lambda network: next(f for f in network["features"] if f["properties"]["id"] == slug)["properties"]["name"]  # noqa: E731

        with patch.dict(NETWORKS, {CITY: {"type": "FeatureCollection", "features": [fixed_later]}}):
            hidden = merged_network(CITY, ((slug, json.dumps(approved)),))
            assert name(hidden) == "Approved in the app", "while published, the database version wins"
            assert name(merged_network(CITY, ())) == "Fixed in the routes repo"


class TestRollbackAfterPrune:
    @contextmanager
    def app(self):
        with TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'routes.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            with patch.object(main, "SessionLocal", sessions), patch.object(main, "_require_admin", return_value="admin"), \
                    patch.object(main, "_require_same_origin"), TestClient(main.app) as client:
                yield client, sessions
            engine.dispose()

    def revision(self, sessions, slug, version):
        with sessions() as session:
            revision = RouteRevision(city=CITY, route_slug=slug, feature_json=json.dumps(version), action="approved", actor="t", note="note")
            session.add(revision)
            session.commit()
            return revision.id

    def test_rollback_recreates_a_retired_publication(self):
        line = NETWORKS[CITY]["features"][0]
        slug = line["properties"]["id"]
        older = {**line, "properties": {**line["properties"], "name": "Older version"}}
        with self.app() as (client, sessions):
            revision_id = self.revision(sessions, slug, older)
            response = client.post(f"/api/admin/routes/{slug}/rollback", json={"revision_id": revision_id, "note": "Bad correction, restoring"})
            assert response.status_code == 200, response.text
            with sessions() as session:
                publication = session.get(RoutePublication, (CITY, slug))
                assert json.loads(publication.feature_json)["properties"]["name"] == "Older version"

    def test_rollback_to_what_the_file_already_has_is_refused(self):
        line = NETWORKS[CITY]["features"][0]
        slug = line["properties"]["id"]
        with self.app() as (client, sessions):
            revision_id = self.revision(sessions, slug, line)
            response = client.post(f"/api/admin/routes/{slug}/rollback", json={"revision_id": revision_id, "note": "Same as the file already"})
            assert response.status_code == 409
