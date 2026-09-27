"""Guard the inferred network and its up-to-three-ride planner."""

import unittest

from route_catalog import ROUTE_BY_ID, distance_km, match_jeepney, public_catalog
from transit_network import MAX_TRANSFER_WALK_KM, MIN_RIDE_KM, NETWORK, NETWORKS, _scan_line, plan_trips


AYALA = (10.6768, 122.9500)
SM = (10.6722, 122.9443)
LA_SALLE = (10.6785, 122.9626)
NORTH_TERMINAL = (10.70655, 122.96312)
ALANGILAN_EDGE = (10.65956, 123.07579)
SOUTH_BACOLOD = (10.63613, 122.94726)


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
        self.assertTrue(all(route["geometry_status"] == "inferred_from_lptrp_anchors" for route in catalog["routes"]))

    def test_additional_city_catalogs_have_mapped_jeepney_lines(self):
        self.assertEqual(len(public_catalog("iloilo")["routes"]), 25)
        self.assertEqual(len(public_catalog("tacloban")["routes"]), 19)
        self.assertEqual(len(public_catalog("cebu")["routes"]), 64)
        self.assertEqual(set(NETWORKS), {"bacolod", "iloilo", "cebu", "tacloban"})

    def test_ayala_to_sm_uses_published_bata_line(self):
        match = match_jeepney(*AYALA, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertIn(match["legs"][0]["route_id"], {"bata-libertad", "northbound-libertad"})
        self.assertEqual(match["geometry_type"], "published_or_inferred_road_corridor")
        self.assertGreater(len(match["legs"][0]["geometry"]["coordinates"]), 30)
        self.assertGreater(match["road_distance_km"], 1.4)
        self.assertLess(match["access"]["origin_walk_km"], 0.2)
        self.assertLess(match["access"]["destination_walk_km"], 0.2)

    def test_ayala_to_la_salle_is_reachable_with_at_most_one_transfer(self):
        match = match_jeepney(*AYALA, *LA_SALLE)
        self.assertIn(match["ride_count"], {1, 2})
        self.assertLessEqual(match["access"]["origin_walk_km"], 0.75)
        self.assertLessEqual(match["access"]["destination_walk_km"], 0.75)

    def test_north_terminal_uses_lacson_corridor_to_sm(self):
        match = match_jeepney(*NORTH_TERMINAL, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertIn(match["legs"][0]["route_id"], {"bata-libertad", "northbound-libertad", "pepsi-bata-bgc"})
        self.assertGreater(match["road_distance_km"], 6)

    def test_north_terminal_to_la_salle_uses_two_rides(self):
        match = match_jeepney(*NORTH_TERMINAL, *LA_SALLE)
        self.assertEqual(match["ride_count"], 2)
        self.assertEqual(len(match["transfers"]), 1)
        self.assertLessEqual(match["transfers"][0]["walk_km"], 0.32)

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
        self.assertTrue(all(transfer["walk_km"] <= MAX_TRANSFER_WALK_KM for transfer in match["transfers"]))
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

    def test_line_scan_rides_both_directions_and_skips_hops(self):
        stop_km = (0.0, 0.1, 0.5, 0.6, 1.0)
        arrivals = _scan_line(stop_km, {2: 1.0, 4: 0.2})
        self.assertEqual(arrivals[0], (1.2, 4))  # a cheaper boarding further away wins
        self.assertAlmostEqual(arrivals[4][0], 1.5)
        self.assertEqual(arrivals[4][1], 2)
        self.assertNotIn(3, _scan_line(stop_km, {2: 1.0}))  # 100 m is below the minimum ride


if __name__ == "__main__":
    unittest.main()
