"""Community route suggestions stay pending and collect one vote per browser."""

from contextlib import contextmanager
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
        assert client.patch(f"/api/route-proposals/{proposal_id}/review", json={"status": "accepted", "note": "Checked against the city route plan."}).status_code == 403
        monkeypatch.setenv("ROUTE_REVIEW_TOKEN", "review-secret")
        reviewed = client.patch(f"/api/route-proposals/{proposal_id}/review", headers={"X-Review-Token": "review-secret"}, json={"status": "accepted", "note": "Checked against the city route plan."})
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "accepted"
        assert client.post(f"/api/route-proposals/{proposal_id}/vote").status_code == 409


def test_rejects_distant_or_malformed_route_points():
    with proposal_app() as client:
        assert client.post("/api/route-proposals", json={**new_route(), "coordinates": [[0, 0], [1, 1]]}).status_code == 422
        assert client.post("/api/route-proposals", json={**new_route(), "coordinates": [[122.95, 10.67], [122.95, 10.67]]}).status_code == 422
