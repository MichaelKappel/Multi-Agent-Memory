import unittest

from memoryendpoints.site_data import PUBLIC_ROUTES, ROUTE_TABLE, agent_compatibility_contract, route_inventory


class PublicTourDiscoveryTests(unittest.TestCase):
    def test_public_tour_routes_are_discoverable_public_get_surfaces(self):
        routes = {item["route"]: item for item in ROUTE_TABLE}
        inventory = {item["route"]: item for item in route_inventory()["routes"]}

        for route in ("/tour", "/tour/knowledge"):
            self.assertIn(route, PUBLIC_ROUTES)
            self.assertEqual("public", routes[route]["access"])
            self.assertEqual(["GET"], routes[route]["methods"])
            self.assertEqual("public", inventory[route]["access"])
            self.assertEqual("L0", inventory[route]["agentCompatibility"]["lowestSafeAbilityLevel"])
            self.assertEqual("safe_read", inventory[route]["agentCompatibility"]["sideEffectStatus"])

    def test_agent_compatibility_lists_tour_as_static_browser_surface(self):
        contract = agent_compatibility_contract()
        abilities = contract["surfaceMatrix"]

        for route in ("/tour", "/tour/knowledge"):
            self.assertIn(route, abilities["staticHtml"]["routes"])
            self.assertIn(route, abilities["browserForms"]["routes"])


if __name__ == "__main__":
    unittest.main()
