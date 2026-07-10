import unittest

from scripts import verify_live_connector_contract as verifier


class LiveConnectorContractVerificationTests(unittest.TestCase):
    def test_connector_contract_check_requires_current_message_ack_contract(self):
        payload = {
            "data": {
                "schemaVersion": "memoryendpoints.connector_contract.v1",
                "memoryFlow": {
                    "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
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
            }
        }

        check = verifier.connector_contract_check(payload)

        self.assertTrue(check["broadcastFanoutAdvertised"])
        self.assertTrue(check["ackIsolationAdvertised"])
        self.assertTrue(check["visibleAgentsConfirmationAdvertised"])
        self.assertTrue(check["recipientCountConfirmationAdvertised"])
        self.assertTrue(check["browserCorsHeadersVerified"])

    def test_connector_contract_check_rejects_missing_ack_isolation_fields(self):
        payload = {
            "data": {
                "memoryFlow": {
                    "reviewQueueFilters": ["status", "source_prefix", "tag", "memory_type", "actor_agent_id"],
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
            }
        }

        check = verifier.capability_matrix_check(payload)

        self.assertTrue(check["broadcastFanoutAdvertised"])
        self.assertTrue(check["ackIsolationAdvertised"])
        self.assertTrue(check["visibleAgentsConfirmationAdvertised"])
        self.assertTrue(check["browserCorsAdvertised"])

    def test_build_report_fails_when_current_message_contract_is_missing(self):
        passing_preflight = {"verified": True}
        protected = {"verified": True}
        contract = {
            "reviewQueueFiltersVerified": True,
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
