"""Check that optional modes do not displace a researched jeepney ride."""

import unittest

from main import routes


class RouteOptionTests(unittest.TestCase):
    def test_jeepney_connection_is_the_only_recommendation(self):
        result = routes(10.6768, 122.9500, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["jeepney"])
        self.assertIsNone(result["jeepney_notice"])

    def test_unverified_connection_leads_with_walk(self):
        result = routes(10.80, 123.15, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["walk", "tricycle"])
        self.assertEqual(result["options"][1]["availability"], "unconfirmed")
        self.assertIsNone(result["options"][1]["fare_php"])
        self.assertIn("no mapped jeepney connection", result["jeepney_notice"])
        self.assertIn("does not mean no jeepney serves them", result["jeepney_notice"])

    def test_north_terminal_to_sm_uses_researched_corridor(self):
        result = routes(10.70655, 122.96312, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["jeepney"])
        self.assertGreater(result["distance_km"], 6)

    def test_two_ride_itinerary_is_returned_when_needed(self):
        result = routes(10.61779, 123.00592, 10.6722, 122.9443)
        option = result["options"][0]
        self.assertEqual(option["id"], "jeepney")
        self.assertEqual(option["itinerary"]["ride_count"], 2)
        self.assertEqual(len(option["itinerary"]["legs"]), 2)


if __name__ == "__main__":
    unittest.main()
