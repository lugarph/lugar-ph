"""The splash page and the one-page-per-city addresses."""

from fastapi.testclient import TestClient

import main
from transit_network import CITY_METADATA


client = TestClient(main.app)


def test_splash_page_introduces_the_app_and_links_every_city():
    response = client.get("/")
    assert response.status_code == 200
    assert "Which jeepney do I take?" in response.text
    for city, metadata in CITY_METADATA.items():
        assert f'href="/{city}"' in response.text
        assert metadata["name"] in response.text


def test_each_city_has_its_own_planner_page():
    for city, metadata in CITY_METADATA.items():
        response = client.get(f"/{city}")
        assert response.status_code == 200
        assert f"<title>{metadata['name']} jeepney routes — Lugar.ph</title>" in response.text
        assert f'city: "{city}",' in response.text


def test_other_spellings_redirect_to_the_canonical_city_address():
    for path in ("/cagayan-de-oro", "/CDO", "/Bacolod"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 308
        assert response.headers["location"] == f"/{main.CITY_ALIASES.get(path[1:].lower(), path[1:].lower())}"


def test_unknown_city_shows_the_city_picker_with_a_404():
    response = client.get("/manila")
    assert response.status_code == 404
    assert "doesn't cover “manila” yet" in response.text
    assert 'href="/bacolod"' in response.text


def test_city_pages_do_not_shadow_the_api_or_health_check():
    assert client.get("/health").json() == {"status": "ok"}
    cities = client.get("/api/cities").json()["cities"]
    assert {city["id"] for city in cities} == set(CITY_METADATA)
    assert all(city["lines"] > 0 for city in cities)
