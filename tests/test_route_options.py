"""Check that optional modes do not displace a researched jeepney ride."""

import unittest
from unittest.mock import patch

from main import routes


class RouteOptionTests(unittest.TestCase):
    def setUp(self):
        # Keep tests offline: without the street router, walks fall back to estimates.
        patcher = patch("main.walking_matrix", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_jeepney_connection_is_the_only_recommendation(self):
        result = routes(10.6768, 122.9500, 10.6722, 122.9443)
        self.assertEqual(result["options"][0]["id"], "jeepney")
        self.assertTrue(all(option["mode"] == "jeepney" for option in result["options"]))
        self.assertIsNone(result["jeepney_notice"])

    def test_unmapped_connection_returns_no_non_jeepney_modes(self):
        result = routes(10.80, 123.15, 10.6722, 122.9443)
        self.assertEqual(result["options"], [])
        self.assertIn("No mapped jeepney connection", result["jeepney_notice"])
        self.assertEqual(result["no_route"]["reason"], "origin_far")
        self.assertIn("jeepney routes only", result["estimate_note"])

    def test_other_city_uses_its_own_network(self):
        result = routes(10.3180, 123.9037, 10.3116, 123.9186, city="cebu")
        self.assertEqual(result["city"], "cebu")
        self.assertEqual(result["options"][0]["id"], "jeepney")

    def test_north_terminal_to_sm_uses_researched_corridor(self):
        result = routes(10.70655, 122.96312, 10.6722, 122.9443)
        self.assertEqual(result["options"][0]["id"], "jeepney")
        self.assertGreater(result["distance_km"], 6)

    def test_two_ride_itinerary_is_returned_when_needed(self):
        result = routes(10.61779, 123.00592, 10.6722, 122.9443)
        option = result["options"][0]
        self.assertEqual(option["id"], "jeepney")
        self.assertEqual(option["itinerary"]["ride_count"], 2)
        self.assertEqual(len(option["itinerary"]["legs"]), 2)

    def test_alternatives_follow_the_recommended_option(self):
        result = routes(10.6768, 122.9500, 10.6785, 122.9626)
        options = result["options"]
        self.assertGreater(len(options), 1)
        self.assertEqual([option["id"] for option in options], ["jeepney"] + [f"jeepney-alt-{index}" for index in range(1, len(options))])
        self.assertTrue(options[0]["recommended"])
        self.assertTrue(all(option["fare_php"] >= 14 for option in options))
        self.assertIn("20% less", result["fare_note"])
        self.assertTrue(all(option["tags"] and not option["recommended"] for option in options[1:]))

    def test_three_ride_description(self):
        option = routes(10.65956, 123.07579, 10.63613, 122.94726)["options"][0]
        self.assertEqual(option["itinerary"]["ride_count"], 3)
        self.assertIn("transfer 2 times", option["description"])


if __name__ == "__main__":
    unittest.main()
