"""Check that optional modes do not displace a researched jeepney ride."""

import unittest

from main import routes


class RouteOptionTests(unittest.TestCase):
    def test_jeepney_connection_is_the_only_recommendation(self):
        result = routes(10.6768, 122.9500, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["jeepney"])
        self.assertIsNone(result["jeepney_notice"])

    def test_unverified_connection_leads_with_walk(self):
        result = routes(10.7, 122.97, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["walk", "tricycle"])
        self.assertEqual(result["options"][1]["availability"], "unconfirmed")
        self.assertIsNone(result["options"][1]["fare_php"])
        self.assertIn("No verified jeepney", result["jeepney_notice"])

    def test_north_terminal_to_sm_uses_researched_corridor(self):
        result = routes(10.70655, 122.96312, 10.6722, 122.9443)
        self.assertEqual([option["id"] for option in result["options"]], ["jeepney"])
        self.assertGreater(result["distance_km"], 6)


if __name__ == "__main__":
    unittest.main()
