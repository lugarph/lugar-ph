"""Guard the inferred network and its one-transfer planner."""

import unittest

from route_catalog import ROUTE_BY_ID, distance_km, match_jeepney, public_catalog
from transit_network import NETWORK, NETWORKS


AYALA = (10.6768, 122.9500)
SM = (10.6722, 122.9443)
LA_SALLE = (10.6785, 122.9626)
NORTH_TERMINAL = (10.70655, 122.96312)


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
        self.assertEqual(len(match["transfer_points"]), 2)

    def test_remote_places_and_zero_length_trips_are_not_guessed(self):
        self.assertIsNone(match_jeepney(10.80, 123.15, *SM))
        self.assertIsNone(match_jeepney(*AYALA, *AYALA))

    def test_paglaum_to_sm_allows_two_rides(self):
        match = match_jeepney(10.61779, 123.00592, *SM)
        self.assertEqual(match["ride_count"], 2)
        self.assertLessEqual(match["access"]["origin_walk_km"], 0.1)


if __name__ == "__main__":
    unittest.main()
