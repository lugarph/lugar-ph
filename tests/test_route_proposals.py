"""Community route suggestions stay pending and collect one vote per browser."""

from contextlib import contextmanager
from hashlib import pbkdf2_hmac
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from models import Base
from transit_network import NETWORKS


@contextmanager
def proposal_app():
    with TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'routes.db'}")
        Base.metadata.create_all(engine)
        main._proposal_times.clear()
        main._login_attempts.clear()
        with patch.object(main, "SessionLocal", sessionmaker(bind=engine)), TestClient(main.app) as client:
            yield client
        engine.dispose()


def new_route():
    return {
        "city": "bacolod", "kind": "new", "number": "TEST", "name": "Market – Plaza",
        "mode": "jeepney", "coordinates": [[122.95, 10.67], [122.96, 10.68]],
        "author": "Local Rider", "reason": "I rode this line last week from the market to the plaza.",
    }


def test_new_route_is_pending_city_scoped_and_does_not_change_published_network():
    before = len(NETWORKS["bacolod"]["features"])
    with proposal_app() as client:
        created = client.post("/api/route-proposals", json=new_route())
        assert created.status_code == 201
        assert created.json()["status"] == "pending"
        assert created.json()["coordinates"] == new_route()["coordinates"]
        assert len(client.get("/api/route-proposals?city=bacolod").json()["proposals"]) == 1
        assert client.get("/api/route-proposals?city=cebu").json()["proposals"] == []
        assert len(client.get("/api/jeepney-network?city=bacolod").json()["features"]) == before


def test_correction_requires_a_line_in_the_same_city_and_an_actual_change():
    feature = NETWORKS["bacolod"]["features"][0]
    properties = feature["properties"]
    payload = {**new_route(), "kind": "correction", "route_slug": properties["id"],
               "number": str(properties["number"]), "name": properties["name"],
               "coordinates": feature["geometry"]["coordinates"]}
    with proposal_app() as client:
        assert client.post("/api/route-proposals", json=payload).status_code == 422
        wrong_city = {**payload, "city": "cebu", "name": "Changed route name"}
        assert client.post("/api/route-proposals", json=wrong_city).status_code == 422
        changed = {**payload, "name": "Changed route name"}
        response = client.post("/api/route-proposals", json=changed)
        assert response.status_code == 201
        assert response.json()["route_slug"] == properties["id"]


def test_votes_toggle_per_browser_and_review_closes_voting(monkeypatch):
    with proposal_app() as client:
        proposal_id = client.post("/api/route-proposals", json=new_route()).json()["id"]
        client.get("/api/route-proposals?city=bacolod")
        first = client.post(f"/api/route-proposals/{proposal_id}/vote")
        assert first.json() == {"votes": 1, "voted": True}
        assert client.get("/api/route-proposals?city=bacolod").json()["proposals"][0]["voted"]
        with TestClient(main.app) as other:
            assert other.post(f"/api/route-proposals/{proposal_id}/vote").json()["votes"] == 2
        assert client.post(f"/api/route-proposals/{proposal_id}/vote").json() == {"votes": 1, "voted": False}
        assert client.patch(f"/api/route-proposals/{proposal_id}/review", json={"status": "accepted", "note": "Checked against the city route plan."}).status_code == 401
        monkeypatch.setenv("ROUTE_REVIEW_TOKEN", "review-secret")
        reviewed = client.patch(f"/api/route-proposals/{proposal_id}/review", headers={"X-Review-Token": "review-secret"}, json={"status": "accepted", "note": "Checked against the city route plan."})
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "accepted"
        assert client.post(f"/api/route-proposals/{proposal_id}/vote").status_code == 409


def test_rejects_distant_or_malformed_route_points():
    with proposal_app() as client:
        assert client.post("/api/route-proposals", json={**new_route(), "coordinates": [[0, 0], [1, 1]]}).status_code == 422
        assert client.post("/api/route-proposals", json={**new_route(), "coordinates": [[122.95, 10.67], [122.95, 10.67]]}).status_code == 422


def test_admin_login_review_and_logout(monkeypatch):
    salt = bytes.fromhex("11" * 16)
    digest = pbkdf2_hmac("sha256", b"test-password", salt, 100_000).hex()
    monkeypatch.setenv("ROUTE_ADMIN_USERNAME", "reviewer")
    monkeypatch.setenv("ROUTE_ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$100000${salt.hex()}${digest}")
    origin = {"Origin": "http://testserver"}
    with proposal_app() as client:
        proposal_id = client.post("/api/route-proposals", json=new_route()).json()["id"]
        assert client.get("/admin/routes").status_code == 200
        assert client.get("/api/admin/session").json() == {"configured": True, "username": None}
        assert client.get("/api/admin/route-proposals").status_code == 401
        assert client.get("/api/admin/export-network").status_code == 401
        assert client.post("/api/admin/login", headers=origin, json={"username": "reviewer", "password": "wrong"}).status_code == 401
        login = client.post("/api/admin/login", headers=origin, json={"username": "reviewer", "password": "test-password"})
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        assert client.get("/api/admin/session").json()["username"] == "reviewer"
        assert client.get("/api/admin/route-proposals").json()["proposals"][0]["id"] == proposal_id
        assert client.get("/api/admin/export-network").json()["type"] == "FeatureCollection"
        decision = {"status": "accepted", "note": "Confirmed with the official route plan."}
        assert client.patch(f"/api/route-proposals/{proposal_id}/review", json=decision).status_code == 403
        assert client.patch(f"/api/route-proposals/{proposal_id}/review", headers=origin, json=decision).json()["status"] == "accepted"
        assert client.post("/api/admin/logout", headers=origin).status_code == 200
        assert client.get("/api/admin/session").json()["username"] is None
        assert client.get("/api/admin/route-proposals").status_code == 401


def test_approval_publishes_new_route_and_rollback_removes_it(monkeypatch):
    salt = bytes.fromhex("22" * 16)
    digest = pbkdf2_hmac("sha256", b"test-password", salt, 100_000).hex()
    monkeypatch.setenv("ROUTE_ADMIN_USERNAME", "reviewer")
    monkeypatch.setenv("ROUTE_ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$100000${salt.hex()}${digest}")
    origin = {"Origin": "http://testserver"}
    with proposal_app() as client:
        assert client.get("/admin").status_code == 200
        before = len(client.get("/api/jeepney-network").json()["features"])
        proposal_id = client.post("/api/route-proposals", json=new_route()).json()["id"]
        client.post("/api/admin/login", headers=origin, json={"username": "reviewer", "password": "test-password"})
        accepted = client.patch(f"/api/route-proposals/{proposal_id}/review", headers=origin,
                                json={"status": "accepted", "note": "Verified route with local riders."})
        assert accepted.status_code == 200
        slug = accepted.json()["route_slug"]
        assert len(client.get("/api/jeepney-network").json()["features"]) == before + 1
        assert len(client.get("/api/admin/export-network").json()["features"]) == before + 1
        assert any(line.id == slug and len(line.coordinates) > 2 for line in main._live("bacolod").graph.lines)
        assert any(route["id"] == slug for route in client.get("/api/jeepney-routes").json()["routes"])
        assert client.get(f"/api/jeepney-routes/{slug}/comments").status_code == 200
        history = client.get("/api/admin/route-revisions").json()
        baseline = next(item for item in history["revisions"] if item["action"] == "baseline")
        assert client.post(f"/api/admin/routes/{slug}/rollback", json={"revision_id": baseline["id"], "note": "Incorrectly approved route."}).status_code == 403
        restored = client.post(f"/api/admin/routes/{slug}/rollback", headers=origin,
                               json={"revision_id": baseline["id"], "note": "Incorrectly approved route."})
        assert restored.status_code == 200
        assert len(client.get("/api/jeepney-network").json()["features"]) == before
        assert not any(route["id"] == slug for route in client.get("/api/jeepney-routes").json()["routes"])
        assert client.patch(f"/api/route-proposals/{proposal_id}/review", headers=origin,
                            json={"status": "accepted", "note": "Duplicate decision."}).status_code == 409


def test_correction_rollback_restores_original_geometry(monkeypatch):
    monkeypatch.setenv("ROUTE_REVIEW_TOKEN", "review-secret")
    original = NETWORKS["bacolod"]["features"][0]
    slug = original["properties"]["id"]
    with proposal_app() as client:
        proposal = {**new_route(), "kind": "correction", "route_slug": slug,
                    "number": str(original["properties"]["number"]), "name": "Corrected name"}
        proposal_id = client.post("/api/route-proposals", json=proposal).json()["id"]
        accepted = client.patch(f"/api/route-proposals/{proposal_id}/review",
                                headers={"X-Review-Token": "review-secret"},
                                json={"status": "accepted", "note": "Verified route correction."})
        assert accepted.status_code == 200
        changed = next(item for item in client.get("/api/jeepney-network").json()["features"] if item["properties"]["id"] == slug)
        assert changed["properties"]["name"] == "Corrected name"
        assert changed["geometry"]["coordinates"] == proposal["coordinates"]
        with patch.object(main, "_admin_username", return_value="reviewer"):
            history = client.get("/api/admin/route-revisions").json()
            baseline = next(item for item in history["revisions"] if item["action"] == "baseline")
            rollback = client.post(f"/api/admin/routes/{slug}/rollback", headers={"Origin": "http://testserver"},
                                   json={"revision_id": baseline["id"], "note": "Return to mapped original."})
        assert rollback.status_code == 200
        restored = next(item for item in client.get("/api/jeepney-network").json()["features"] if item["properties"]["id"] == slug)
        assert restored == original
