"""Guard the inferred network and its up-to-three-ride planner."""

import unittest

from route_catalog import ROUTE_BY_ID, distance_km, match_jeepney, public_catalog
from transit_network import (
    LINE_BY_ID, LINES_BY_CITY, MAX_ACCESS_WALK_KM, SHARED_STOP_KM, MAX_TRANSFER_WALK_KM, MIN_RIDE_KM, NETWORK, NETWORKS, STRAIGHT_LINE_DETOUR,
    _fare, _scan_line, plan_trips, trip_help,
)


AYALA = (10.6768, 122.9500)
SM = (10.6722, 122.9443)
LA_SALLE = (10.6785, 122.9626)
NORTH_TERMINAL = (10.70655, 122.96312)
ALANGILAN_EDGE = (10.65956, 123.07579)
ROBINSONS = (10.6913003, 122.9583181)
SOUTH_BACOLOD = (10.63613, 122.94726)


def _group(leg: dict) -> list[dict]:
    """The chosen jeep for a ride plus every interchangeable one."""
    return [leg, *leg["also"]]


def _group_ids(leg: dict) -> set[str]:
    return {jeep["route_id"] for jeep in _group(leg)}


def _group_headings(leg: dict, route_id: str | None = None) -> list[str]:
    return [jeep["heading"] for jeep in _group(leg) if route_id in (None, jeep["route_id"])]


class RouteCatalogTests(unittest.TestCase):
    def test_stored_street_traces_remain_contiguous_in_bacolod(self):
        self.assertEqual(len(NETWORK["features"]), 24)
        for feature in NETWORK["features"]:
            with self.subTest(route=feature["properties"]["id"]):
                coordinates = feature["geometry"]["coordinates"]
                self.assertGreater(len(coordinates), 20)
                self.assertTrue(all(10.58 < lat < 10.73 and 122.89 < lng < 123.10 for lng, lat in coordinates))
                self.assertLess(
                    max(distance_km(a[1], a[0], b[1], b[0]) for a, b in zip(coordinates, coordinates[1:])),
                    0.5,
                )

    def test_published_catalog_has_24_distinct_routes(self):
        catalog = public_catalog()
        self.assertEqual(len(catalog["routes"]), 24)
        self.assertGreater(len(ROUTE_BY_ID), 100)
        self.assertEqual([route["number"] for route in catalog["routes"]], list(range(1, 25)))
        self.assertEqual(sum(bool(route["mapped_portion"]) for route in catalog["routes"]), 24)
        statuses = [route["geometry_status"] for route in catalog["routes"]]
        self.assertEqual(statuses.count("osm_route_relation"), 11)
        self.assertEqual(statuses.count("inferred_from_lptrp_anchors"), 13)

    def test_additional_city_catalogs_have_mapped_jeepney_lines(self):
        self.assertEqual(len(public_catalog("iloilo")["routes"]), 25)
        self.assertEqual(len(public_catalog("tacloban")["routes"]), 19)
        self.assertEqual(len(public_catalog("cebu")["routes"]), 64)
        self.assertEqual(set(NETWORKS), {"bacolod", "iloilo", "cebu", "tacloban"})

    def test_ayala_to_sm_uses_published_bata_line(self):
        match = match_jeepney(*AYALA, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertTrue({"bata-libertad", "northbound-libertad"} & _group_ids(match["legs"][0]))
        self.assertEqual(match["geometry_type"], "published_or_inferred_road_corridor")
        self.assertGreater(len(match["legs"][0]["geometry"]["coordinates"]), 10)
        self.assertGreater(match["road_distance_km"], 1.0)
        # Some option boards right at Ayala and gets off right at SM.
        self.assertTrue(any(
            trip["access"]["origin_walk_km"] < 0.2 and trip["access"]["destination_walk_km"] < 0.2
            for trip in plan_trips(*AYALA, *SM)
        ))

    def test_ayala_to_la_salle_is_reachable_with_at_most_one_transfer(self):
        match = match_jeepney(*AYALA, *LA_SALLE)
        self.assertIn(match["ride_count"], {1, 2})
        # Search radii are straight-line; reported walks include the street detour estimate.
        self.assertLessEqual(match["access"]["origin_walk_km"], MAX_ACCESS_WALK_KM * STRAIGHT_LINE_DETOUR)
        self.assertLessEqual(match["access"]["destination_walk_km"], MAX_ACCESS_WALK_KM * STRAIGHT_LINE_DETOUR)

    def test_north_terminal_uses_lacson_corridor_to_sm(self):
        match = match_jeepney(*NORTH_TERMINAL, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertTrue({"bata-libertad", "northbound-libertad", "pepsi-bata-bgc"} & _group_ids(match["legs"][0]))
        self.assertGreater(match["road_distance_km"], 4.5)  # down Lacson Street, about 5 km

    def test_north_terminal_to_la_salle_rides_the_mapped_shopping_line(self):
        # OpenStreetMap shows line 5 passing La Salle on its way back to Shopping, so one ride is enough.
        match = match_jeepney(*NORTH_TERMINAL, *LA_SALLE)
        self.assertEqual(match["ride_count"], 1)
        self.assertIn("shopping-northbound", _group_ids(match["legs"][0]))
        self.assertEqual(match["legs"][0]["heading"], "Shopping")

    def test_remote_places_and_zero_length_trips_are_not_guessed(self):
        self.assertIsNone(match_jeepney(10.80, 123.15, *SM))
        self.assertIsNone(match_jeepney(*AYALA, *AYALA))

    def test_paglaum_to_sm_allows_two_rides(self):
        match = match_jeepney(10.61779, 123.00592, *SM)
        self.assertEqual(match["ride_count"], 2)
        self.assertLessEqual(match["access"]["origin_walk_km"], 0.1)

    def test_far_corners_use_three_rides(self):
        match = match_jeepney(*ALANGILAN_EDGE, *SOUTH_BACOLOD)
        self.assertEqual(match["ride_count"], 3)
        self.assertEqual(len(match["transfers"]), 2)
        self.assertEqual(len(match["waypoints"]), 6)
        self.assertTrue(all(transfer["walk_km"] <= MAX_TRANSFER_WALK_KM * STRAIGHT_LINE_DETOUR for transfer in match["transfers"]))
        self.assertTrue(all(leg["road_distance_km"] >= MIN_RIDE_KM for leg in match["legs"]))
        # Each transfer walks from where the previous ride ends to where the next one starts.
        for previous, transfer, following in zip(match["legs"], match["transfers"], match["legs"][1:]):
            self.assertEqual([transfer["from"]["lng"], transfer["from"]["lat"]], list(previous["geometry"]["coordinates"][-1]))
            self.assertEqual([transfer["to"]["lng"], transfer["to"]["lat"]], list(following["geometry"]["coordinates"][0]))

    def test_alternatives_are_distinct_and_explain_their_advantage(self):
        trips = plan_trips(*AYALA, *LA_SALLE)
        self.assertGreaterEqual(len(trips), 2)
        self.assertLessEqual(len(trips), 3)
        self.assertEqual(trips[0]["tags"], [])
        primary = trips[0]
        for alternative in trips[1:]:
            self.assertTrue(alternative["tags"])
            if "Less walking" in alternative["tags"]:
                self.assertLess(alternative["walk_km"], primary["walk_km"])
            if "Fewer transfers" in alternative["tags"]:
                self.assertLess(alternative["ride_count"], primary["ride_count"])
        self.assertEqual(len({tuple(line["id"] for line in trip["lines"]) for trip in trips}), len(trips))

    def test_line_scan_rides_forward_only_and_skips_hops(self):
        stop_km = (0.0, 0.1, 0.5, 0.6, 1.0)
        arrivals = _scan_line(stop_km, {2: 1.0, 0: 1.2})
        self.assertAlmostEqual(arrivals[4][0], 1.5)
        self.assertEqual(arrivals[4][1], 2)  # the cheaper total wins
        self.assertEqual(set(_scan_line(stop_km, {2: 1.0})), {4})  # never backwards, never a 100 m hop

    def test_circuits_continue_past_their_start(self):
        stop_km = (0.0, 0.5, 1.0, 1.5, 2.0)  # a 2 km circuit; stop 4 is back at the start
        arrivals = _scan_line(stop_km, {3: 0.0}, circuit_km=2.0)
        self.assertAlmostEqual(arrivals[1][0], 1.0)  # 1.5 -> 2.0, then on to 0.5
        self.assertNotIn(1, _scan_line(stop_km, {3: 0.0}))  # an open line ends at its last stop

    def test_every_line_is_a_circuit_in_riding_order(self):
        for city in ("bacolod", "iloilo", "tacloban"):
            with self.subTest(city=city):
                self.assertTrue(all(line.circuit for line in LINES_BY_CITY[city]))
        self.assertGreater(sum(line.circuit for line in LINES_BY_CITY["cebu"]), 60)

    def test_return_trips_use_the_other_half_of_the_circuit(self):
        there = match_jeepney(*AYALA, *SM)["legs"][0]
        back = match_jeepney(*SM, *AYALA)["legs"][0]
        # Jeeps toward Libertad serve Ayala -> SM; the way back is served by jeeps heading elsewhere.
        self.assertIn("Libertad", _group_headings(there))
        self.assertNotIn("Libertad", _group_headings(back))
        line = LINE_BY_ID[there["route_id"]]
        # Rides follow the drawn order: the ride's first point is the boarding stop, not the reverse.
        self.assertEqual(list(there["geometry"]["coordinates"][0]), [there["board"]["lng"], there["board"]["lat"]])
        self.assertTrue(line.circuit)

    def test_rides_say_which_signboard_to_look_for_and_where_to_get_off(self):
        leg = match_jeepney(*AYALA, *SM)["legs"][0]
        self.assertIn("Libertad", _group_headings(leg))
        self.assertEqual(leg["board"]["label"], "near Ayala")
        self.assertEqual(leg["alight"]["label"], "near SM")
        self.assertNotIn("Loop", leg["signboard"])

    def test_fares_follow_the_regular_jeepney_matrix(self):
        self.assertEqual(_fare(1.0), 14)
        self.assertEqual(_fare(4.0), 14)
        self.assertEqual(_fare(4.2), 16)
        self.assertEqual(_fare(6.5), 20)
        match = match_jeepney(*NORTH_TERMINAL, *LA_SALLE)
        self.assertEqual(match["fare_php"], sum(leg["fare_php"] for leg in match["legs"]))

    def test_street_walks_replace_estimates_and_name_the_stops(self):
        def router(sources, destinations):
            return {
                "km": [[0.4] * len(destinations) for _ in sources],
                "source_names": ["Lacson Street"] * len(sources),
                "destination_names": ["Lacson Street"] * len(destinations),
            }

        trip = plan_trips(*AYALA, *SM, walk_matrix=router)[0]
        self.assertEqual(trip["walk_basis"], "street")
        self.assertEqual(trip["access"]["origin_walk_km"], 0.4)
        self.assertEqual(trip["legs"][0]["board"]["label"], "near Ayala, Lacson Street")

    def test_unavailable_router_falls_back_to_detour_estimates(self):
        estimated = plan_trips(*AYALA, *SM, walk_matrix=lambda sources, destinations: None)[0]
        self.assertEqual(estimated["walk_basis"], "estimated")
        self.assertEqual(estimated, match_jeepney(*AYALA, *SM) | {"tags": estimated["tags"], "highlight": estimated["highlight"], "compared_to_best": None})

    def test_alternatives_compare_themselves_to_the_recommendation(self):
        trips = plan_trips(*AYALA, *LA_SALLE)
        self.assertIsNone(trips[0]["compared_to_best"])
        self.assertIn(trips[0]["highlight"], {"Fastest", "Fewest transfers", "Least walking", "Recommended"})
        for alternative in trips[1:]:
            self.assertIsNone(alternative["highlight"])
            self.assertEqual(alternative["compared_to_best"]["minutes"], alternative["duration_minutes"] - trips[0]["duration_minutes"])
        minutes = [trip["duration_minutes"] for trip in trips[1:]]
        self.assertEqual(minutes, sorted(minutes))

    def test_trip_help_points_to_the_nearest_line(self):
        help = trip_help(10.6555, 123.0100, *LA_SALLE)
        self.assertEqual(help["reason"], "origin_far")
        self.assertGreater(help["origin"]["walk_km"], MAX_ACCESS_WALK_KM)
        self.assertLessEqual(help["destination"]["walk_km"], MAX_ACCESS_WALK_KM)
        self.assertEqual(trip_help(*AYALA, *AYALA)["reason"], "too_close")
        self.assertIsNone(trip_help(10.80, 123.15, *SM)["origin"])  # outside the mapped area

    def test_rides_list_every_jeep_that_serves_them(self):
        trips = plan_trips(*ROBINSONS, *AYALA)
        leg = trips[0]["legs"][0]
        others = leg["also"]
        self.assertGreaterEqual(len(others), 3)
        numbers = [leg["route_number"], *(jeep["route_number"] for jeep in others)]
        self.assertEqual(len(numbers), len(set(numbers)))
        for jeep in others:
            line = LINE_BY_ID[jeep["route_id"]]
            for stop in (leg["board"], leg["alight"]):
                self.assertLessEqual(min(distance_km(stop["lat"], stop["lng"], lat, lng) for lng, lat in line.coordinates), SHARED_STOP_KM + 0.01)
        # A trip that only swaps in one of those jeeps is not listed separately.
        listed = {trip["legs"][0]["route_number"] for trip in trips[1:] if trip["ride_count"] == 1}
        self.assertFalse(listed & set(numbers))

    def test_lines_mapped_in_openstreetmap_keep_their_credit(self):
        expected = {"bacolod": 11, "iloilo": 10, "cebu": 28, "tacloban": 6}
        for city, network in NETWORKS.items():
            mapped = [feature for feature in network["features"] if feature["properties"]["status"] == "osm_route_relation"]
            self.assertEqual(len(mapped), expected[city], city)
            for feature in mapped:
                properties, coordinates = feature["properties"], feature["geometry"]["coordinates"]
                with self.subTest(route=properties["id"]):
                    self.assertTrue(properties["osm_relations"])
                    self.assertIn("OpenStreetMap contributors", properties["attribution"])
                    self.assertTrue(LINE_BY_ID[properties["id"]].circuit)
                    self.assertLess(max(distance_km(a[1], a[0], b[1], b[0]) for a, b in zip(coordinates, coordinates[1:])), 0.5)

    def test_uv_express_routes_are_not_priced_as_jeepneys(self):
        uv = {line.id for line in LINES_BY_CITY["bacolod"] if line.mode == "uv_express"}
        self.assertEqual(uv, {"granada-burgos", "alangilan-burgos"})
        self.assertIsNone(_fare(5.0, "uv_express"))
        self.assertEqual(_fare(5.0), 16)

    def test_estimated_paths_are_flagged_on_rides(self):
        legs = [leg for trip in plan_trips(*ALANGILAN_EDGE, *SOUTH_BACOLOD) for leg in trip["legs"]]
        for leg in legs:
            line = LINE_BY_ID[leg["route_id"]]
            self.assertEqual(leg["estimated_path"], line.status.startswith("inferred"))
            self.assertEqual(leg["mode"], line.mode)


if __name__ == "__main__":
    unittest.main()
