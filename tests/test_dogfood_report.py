import unittest

from scripts import dogfood_memoryendpoints


class DogfoodReportTests(unittest.TestCase):
    def test_combined_report_preserves_audit_readback_evidence(self):
        report = dogfood_memoryendpoints.combine_reports(
            [
                {
                    "mode": "local_wsgi",
                    "ok": True,
                    "localDogfoodVerified": True,
                    "liveDogfoodVerified": False,
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
        self.assertEqual(3, report["auditLogCount"])
        self.assertTrue(report["auditTrailReadbackVerified"])
        self.assertFalse(report["rawCredentialValuesStored"])


if __name__ == "__main__":
    unittest.main()
