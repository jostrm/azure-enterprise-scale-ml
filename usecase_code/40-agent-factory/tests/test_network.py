from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent_factory.network import repair_foundry_dns


class DnsRepairTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.target = SimpleNamespace(group_id="/subscriptions/sub/resourceGroups/project",
                                      account_id="/subscriptions/sub/resourceGroups/project/providers/Microsoft.CognitiveServices/accounts/foundry",
                                      account_name="foundry")
        self.group = {
            "id": "/dns/group", "etag": "etag-1",
            "properties": {"privateDnsZoneConfigs": [{
                "name": "existing-policy-entry", "properties": {
                    "privateDnsZoneId": "/subscriptions/hub/resourceGroups/dns/providers/Microsoft.Network/privateDnsZones/privatelink.cognitiveservices.azure.com",
                },
            }]},
        }
        self.endpoint = {"properties": {"privateLinkServiceConnections": [{"properties": {
            "privateLinkServiceId": self.target.account_id,
            "privateLinkServiceConnectionState": {"status": "Approved"},
        }}]}}

    def test_plan_never_writes_and_keeps_policy_group(self):
        self.session.arm.side_effect = [self.endpoint, {"value": [self.group]}, {}, {}, {}]
        result = repair_foundry_dns(self.session, self.target, dns_subscription_id="hub", dns_resource_group="dns")
        self.assertEqual(2, len(result["missing_zones"]))
        self.assertFalse(result["applied"])
        self.session.request.assert_not_called()

    def test_etag_and_all_existing_associations_are_preserved(self):
        def apply(method, url, body, **kwargs):
            self.assertEqual("etag-1", kwargs["headers"]["If-Match"])
            self.assertEqual("existing-policy-entry", body["properties"]["privateDnsZoneConfigs"][0]["name"])
            self.group["properties"] = body["properties"]
            return {}
        self.session.request.side_effect = apply
        self.session.arm.side_effect = [self.endpoint, {"value": [self.group]}, {}, {}, {}, self.group]
        result = repair_foundry_dns(self.session, self.target, dns_subscription_id="hub", dns_resource_group="dns", apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual(3, len(self.group["properties"]["privateDnsZoneConfigs"]))

    def test_missing_etag_blocks_mutation(self):
        del self.group["etag"]
        self.session.arm.side_effect = [self.endpoint, {"value": [self.group]}, {}, {}, {}]
        with self.assertRaisesRegex(RuntimeError, "ETag"):
            repair_foundry_dns(self.session, self.target, dns_subscription_id="hub", dns_resource_group="dns", apply=True)
        self.session.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
