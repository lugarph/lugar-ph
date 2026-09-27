"""Exercise the public-service adapters without making network requests."""

from unittest.mock import patch

from osm_services import search_places, walking_matrix, walking_route


def test_place_search_is_city_bounded_and_returns_map_coordinates():
    payload = [{
        "name": "SM City Bacolod",
        "display_name": "SM City Bacolod, Reclamation Area, Bacolod, Philippines",
        "lat": "10.6722",
        "lon": "122.9443",
        "type": "mall",
    }]
    with patch("osm_services._geocoder.get_json", return_value=payload) as get_json:
        results = search_places("bacolod", "SM City")

    requested_url = get_json.call_args.args[0]
    assert "bounded=1" in requested_url
    assert "countrycodes=ph" in requested_url
    assert results[0]["name"] == "SM City Bacolod"
    assert results[0]["lat"] == 10.6722
    assert results[0]["lng"] == 122.9443


def test_walking_route_returns_turns_street_distance_and_geometry():
    payload = {
        "routes": [{
            "distance": 341,
            "duration": 272.7,
            "geometry": {"type": "LineString", "coordinates": [[122.95, 10.67], [122.949, 10.674]]},
            "legs": [{
                "summary": "Gatuslao Street",
                "steps": [
                    {"distance": 47.2, "name": "", "maneuver": {"type": "depart", "bearing_after": 202}},
                    {"distance": 245.5, "name": "Gatuslao Street", "maneuver": {"type": "turn", "modifier": "right"}},
                    {"distance": 0, "name": "", "maneuver": {"type": "arrive"}},
                ],
            }],
        }],
    }
    with patch("osm_services._foot_router.get_json", return_value=payload):
        result = walking_route(10.6768, 122.9500, 10.6740, 122.9490)

    assert result["routing_status"] == "routed"
    assert result["street_name"] == "Gatuslao Street"
    assert result["distance_km"] == 0.34
    assert result["duration_minutes"] == 5
    assert "Turn right onto Gatuslao Street" in [step["instruction"] for step in result["steps"]]
    assert result["geometry"]["type"] == "LineString"


def test_walking_matrix_adds_snap_distance_and_cleans_street_names():
    payload = {
        "code": "Ok",
        "distances": [[100.0, None], [0.0, 500.0]],
        "sources": [{"distance": 20, "name": "Galo Street / Galo Street / Gatuslao Street"}, {"distance": 0, "name": ""}],
        "destinations": [{"distance": 5, "name": "Lacson Street"}, {"distance": 0, "name": ""}],
    }
    with patch("osm_services._foot_router.get_json", return_value=payload) as get_json:
        # The second destination is the second source itself, so that walk is zero.
        result = walking_matrix([(10.67, 122.95), (10.68, 122.96)], [(10.671, 122.951), (10.68, 122.96)])

    assert "sources=0;1" in get_json.call_args.args[0]
    assert "destinations=2;3" in get_json.call_args.args[0]
    assert get_json.call_args.kwargs["timeout"] <= 5
    assert result["km"][0] == [0.125, None]
    assert result["km"][1] == [0.005, 0.0]
    assert result["source_names"] == ["Galo Street", ""]
    assert result["destination_names"] == ["Lacson Street", ""]


def test_walking_matrix_returns_none_when_router_is_unavailable():
    with patch("osm_services._foot_router.get_json", side_effect=TimeoutError("busy")):
        assert walking_matrix([(10.67, 122.95)], [(10.68, 122.96)]) is None
