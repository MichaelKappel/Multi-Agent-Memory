import unittest

from scripts import dogfood_memoryendpoints


class DogfoodReportTests(unittest.TestCase):
    def test_combined_report_preserves_audit_readback_evidence(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "local_wsgi",
                    "ok": True,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": True,
                    "localDogfoodVerified": True,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": False,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 0,
                    "optionalStepFailureCount": 0,
                    "auditLogCount": 3,
                    "auditTrailReadbackVerified": True,
                }
            ]
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["localDogfoodVerified"])
        self.assertFalse(report["liveCoreDogfoodVerified"])
        self.assertTrue(report["latestDogfoodContractVerified"])
        self.assertTrue(report["localAuditTrailReadbackVerified"])
        self.assertEqual(3, report["auditLogCount"])
        self.assertTrue(report["auditTrailReadbackVerified"])
        self.assertFalse(report["rawCredentialValuesStored"])

    def test_combined_report_distinguishes_live_core_from_latest_contract(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "live_http",
                    "ok": False,
                    "coreDogfoodWorkflowVerified": True,
                    "latestDogfoodContractVerified": False,
                    "localDogfoodVerified": False,
                    "liveDogfoodVerified": False,
                    "liveCoreDogfoodVerified": True,
                    "rawCredentialValuesStored": False,
                    "rawPrivatePayloadsStored": False,
                    "requiredStepFailureCount": 1,
                    "optionalStepFailureCount": 1,
                    "auditLogCount": 0,
                    "auditTrailReadbackVerified": False,
                }
            ]
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["liveDogfoodVerified"])
        self.assertTrue(report["liveCoreDogfoodVerified"])
        self.assertFalse(report["latestDogfoodContractVerified"])
        self.assertFalse(report["liveAuditTrailReadbackVerified"])
        self.assertEqual(0, report["auditLogCount"])


if __name__ == "__main__":
    unittest.main()
