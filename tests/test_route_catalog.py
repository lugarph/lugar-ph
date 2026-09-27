"""Guard researched connections against accidental citywide route claims."""

import unittest

from road_geometry import SEGMENTS, trip_segment
from route_catalog import ROUTE_BY_ID, distance_km, match_jeepney, public_catalog


AYALA = (10.6768, 122.9500)
SM = (10.6722, 122.9443)
LA_SALLE = (10.6785, 122.9626)
NORTH_TERMINAL = (10.70655, 122.96312)


class RouteCatalogTests(unittest.TestCase):
    def test_stored_street_traces_remain_contiguous_in_bacolod(self):
        for segment_id, feature in SEGMENTS.items():
            with self.subTest(segment=segment_id):
                coordinates = feature["geometry"]["coordinates"]
                self.assertGreater(len(coordinates), 30)
                self.assertTrue(all(10.66 < lat < 10.72 and 122.93 < lng < 122.98 for lng, lat in coordinates))
                self.assertLess(
                    max(distance_km(a[1], a[0], b[1], b[0]) for a, b in zip(coordinates, coordinates[1:])),
                    0.3,
                )

    def test_published_catalog_has_24_distinct_routes(self):
        catalog = public_catalog()
        self.assertEqual(len(catalog["routes"]), 24)
        self.assertEqual(len(ROUTE_BY_ID), 24)
        self.assertEqual([route["number"] for route in catalog["routes"]], list(range(1, 25)))
        self.assertEqual(sum(bool(route["mapped_portion"]) for route in catalog["routes"]), 2)

    def test_ayala_to_sm_uses_published_bata_line(self):
        match = match_jeepney(*AYALA, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertEqual(match["legs"][0]["route_id"], "bata-libertad")
        self.assertEqual(match["geometry_type"], "inferred_road_alignment")
        self.assertGreater(len(match["legs"][0]["geometry"]["coordinates"]), 30)
        self.assertGreater(match["road_distance_km"], 1.4)
        self.assertEqual([point["name"] for point in match["waypoints"]], [
            "Ayala Malls Capitol Central area", "SM City Bacolod area"
        ])

    def test_ayala_to_la_salle_requires_sm_transfer(self):
        match = match_jeepney(*AYALA, *LA_SALLE)
        self.assertEqual([leg["route_id"] for leg in match["legs"]], [
            "bata-libertad", "shopping-libertad-lasalle"
        ])
        self.assertEqual(match["ride_count"], 2)
        self.assertGreater(len(match["legs"][1]["geometry"]["coordinates"]), 100)
        self.assertEqual(
            match["legs"][0]["geometry"]["coordinates"][-1],
            match["legs"][1]["geometry"]["coordinates"][0],
        )

    def test_north_terminal_uses_lacson_corridor_to_sm(self):
        match = match_jeepney(*NORTH_TERMINAL, *SM)
        self.assertEqual(match["ride_count"], 1)
        self.assertEqual(match["legs"][0]["route_id"], "bata-libertad")
        self.assertGreater(match["road_distance_km"], 6)
        self.assertIn("Lacson Street", trip_segment("northterminal-sm")["properties"]["anchors"])

    def test_north_terminal_to_la_salle_transfers_at_sm(self):
        match = match_jeepney(*NORTH_TERMINAL, *LA_SALLE)
        self.assertEqual([leg["route_id"] for leg in match["legs"]], [
            "bata-libertad", "shopping-libertad-lasalle"
        ])

    def test_unresearched_places_and_reverse_direction_are_not_guessed(self):
        self.assertIsNone(match_jeepney(10.7, 122.97, *SM))
        self.assertIsNone(match_jeepney(*SM, *AYALA))
        self.assertIsNone(match_jeepney(*AYALA, *AYALA))


if __name__ == "__main__":
    unittest.main()
