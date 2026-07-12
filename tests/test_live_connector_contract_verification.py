import unittest

from memoryendpoints import site_data
from scripts import verify_live_connector_contract as verifier


class LiveConnectorContractVerificationTests(unittest.TestCase):
    def test_connector_contract_check_requires_current_message_ack_contract(self):
        payload = {
            "data": {
                "schemaVersion": "memoryendpoints.connector_contract.v1",
                "memoryFlow": {
                    "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
                    "searchQueryFilters": [
                        "q",
                        "scope",
                        "scope_id",
                        "source_prefix",
                        "tag",
                        "actor_agent_id",
                        "memory_type",
                        "review_status",
                        "promotion_state",
                        "event_id",
                    ],
                    "reviewQueueOperatorSummary": "Use operatorSummary.longTermMemoryReviews.",
                },
                "coordinationFlow": {
                    "broadcastFanout": "per_active_agent_notification",
                    "ackIsolation": "per_recipient_notification",
                },
                "responseContract": {
                    "postConfirmationFields": [
                        "visibleToAgents",
                        "expectedRecipientCount",
                        "visibleRecipientCount",
                    ],
                },
                "browserCors": {
                    "status": "live",
                    "preflightRequiresWorkspaceKey": False,
                    "allowedHeaders": [
                        "Authorization",
                        "Content-Type",
                        "Idempotency-Key",
                        "X-MemoryEndpoints-Key",
                    ],
                },
                "disconnectedDelivery": site_data.disconnected_delivery_contract(),
            }
        }

        check = verifier.connector_contract_check(payload)

        self.assertTrue(check["broadcastFanoutAdvertised"])
        self.assertTrue(check["ackIsolationAdvertised"])
        self.assertTrue(check["visibleAgentsConfirmationAdvertised"])
        self.assertTrue(check["recipientCountConfirmationAdvertised"])
        self.assertTrue(check["browserCorsHeadersVerified"])
        self.assertTrue(check["searchQueryFiltersVerified"])
        self.assertTrue(check["disconnectedPollingBaselineAdvertised"])
        self.assertTrue(check["disconnectedDatabaseTruthVerified"])
        self.assertTrue(check["disconnectedRoutesVerified"])
        self.assertTrue(check["disconnectedPollFieldsVerified"])
        self.assertTrue(check["disconnectedPaginationVerified"])
        self.assertTrue(check["disconnectedAttentionOrderingVerified"])
        self.assertTrue(check["disconnectedAcknowledgementVerified"])
        self.assertTrue(check["disconnectedClientLoopVerified"])
        self.assertTrue(check["disconnectedUnavailableTransportsExplicit"])
        self.assertTrue(check["disconnectedDeliveryClaimsSafe"])
        self.assertTrue(check["disconnectedMultiDeviceRuleVerified"])

    def test_connector_contract_check_rejects_missing_ack_isolation_fields(self):
        payload = {
            "data": {
                "memoryFlow": {
                    "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
                    "searchQueryFilters": ["q", "scope"],
                    "reviewQueueOperatorSummary": "Use operatorSummary.longTermMemoryReviews.",
                },
                "coordinationFlow": {
                    "broadcastFanout": "single_shared_notification",
                },
                "responseContract": {"postConfirmationFields": ["expectedRecipientCount"]},
                "browserCors": {
                    "status": "live",
                    "preflightRequiresWorkspaceKey": False,
                    "allowedHeaders": [
                        "Authorization",
                        "Content-Type",
                        "Idempotency-Key",
                        "X-MemoryEndpoints-Key",
                    ],
                },
            }
        }

        check = verifier.connector_contract_check(payload)

        self.assertFalse(check["broadcastFanoutAdvertised"])
        self.assertFalse(check["ackIsolationAdvertised"])
        self.assertFalse(check["visibleAgentsConfirmationAdvertised"])
        self.assertFalse(check["recipientCountConfirmationAdvertised"])
        self.assertFalse(check["searchQueryFiltersVerified"])
        self.assertFalse(check["disconnectedPollingBaselineAdvertised"])
        self.assertFalse(check["disconnectedDatabaseTruthVerified"])
        self.assertFalse(check["disconnectedPollFieldsVerified"])
        self.assertFalse(check["disconnectedPaginationVerified"])
        self.assertIn("event_id", check["missingSearchQueryFilters"])

    def test_protected_exact_memory_readback_requires_single_filtered_row(self):
        seed = {
            "ok": True,
            "items": [{"eventId": "mem-123"}],
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        exact = {
            "ok": True,
            "items": [{"eventId": "mem-123"}],
            "filters": {"eventId": "mem-123"},
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

        check = verifier.protected_exact_memory_readback_check(seed, exact, "mem-123")

        self.assertTrue(check["verified"])
        self.assertEqual(1, check["exactCount"])
        self.assertTrue(check["eventIdFilterEchoed"])
        self.assertNotIn("mem-123", check["eventIdHash"])

    def test_protected_exact_memory_readback_rejects_ignored_filter(self):
        seed = {
            "ok": True,
            "items": [{"eventId": "mem-123"}, {"eventId": "mem-456"}],
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        exact = {
            "ok": True,
            "items": [{"eventId": "mem-123"}, {"eventId": "mem-456"}],
            "filters": {},
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

        check = verifier.protected_exact_memory_readback_check(seed, exact, "mem-123")

        self.assertFalse(check["verified"])
        self.assertEqual(2, check["exactCount"])
        self.assertFalse(check["eventIdFilterEchoed"])

    def test_capability_matrix_check_requires_current_message_ack_contract(self):
        payload = {
            "data": {
                "reviewPromotionQueue": {
                    "queryFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
                    "operatorSummaryFields": ["longTermMemoryReviews"],
                    "longTermMemoryReviewHealth": "docs/long-term-memory source health",
                },
                "currentMessageLane": {
                    "broadcastFanout": "per_active_agent_notification",
                    "ackIsolation": "per_recipient_notification",
                    "postConfirmationFields": ["visibleToAgents"],
                },
                "connectorContract": {
                    "browserCors": {
                        "status": "live",
                        "preflightWithoutWorkspaceKey": True,
                    },
                },
                "disconnectedDelivery": site_data.disconnected_delivery_contract(),
            }
        }

        check = verifier.capability_matrix_check(payload)

        self.assertTrue(check["broadcastFanoutAdvertised"])
        self.assertTrue(check["ackIsolationAdvertised"])
        self.assertTrue(check["visibleAgentsConfirmationAdvertised"])
        self.assertTrue(check["browserCorsAdvertised"])
        self.assertTrue(check["disconnectedPollingBaselineAdvertised"])
        self.assertTrue(check["disconnectedDatabaseTruthVerified"])
        self.assertTrue(check["disconnectedPollFieldsVerified"])
        self.assertTrue(check["disconnectedPaginationVerified"])
        self.assertTrue(check["disconnectedDeliveryClaimsSafe"])

    def test_build_report_fails_when_current_message_contract_is_missing(self):
        passing_preflight = {"verified": True}
        protected = {"verified": True}
        contract = {
            "reviewQueueFiltersVerified": True,
            "searchQueryFiltersVerified": True,
            "reviewQueueOperatorSummaryVerified": True,
            "browserCorsHeadersVerified": True,
            "broadcastFanoutAdvertised": True,
            "ackIsolationAdvertised": False,
            "visibleAgentsConfirmationAdvertised": True,
            "recipientCountConfirmationAdvertised": True,
        }
        capability = {
            "reviewQueueFiltersVerified": True,
            "longTermReviewHealthAdvertised": True,
            "operatorSummaryFieldsIncludeLongTerm": True,
            "broadcastFanoutAdvertised": True,
            "ackIsolationAdvertised": True,
            "visibleAgentsConfirmationAdvertised": True,
        }

        report = verifier.build_report(
            "https://memoryendpoints.com",
            "abc123",
            contract,
            capability,
            passing_preflight,
            protected,
            workspace_id="workspace-secret",
            token="token-secret",
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawWorkspaceIdStored"])


if __name__ == "__main__":
    unittest.main()
