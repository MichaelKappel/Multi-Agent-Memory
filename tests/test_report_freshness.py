import unittest

from scripts import build_readiness_reports, enterprise_readiness_audit


class ReportFreshnessTests(unittest.TestCase):
    def test_enterprise_report_matches_current_head(self):
        head = "abc123"
        report = {"gitHeadAtVerification": head, "expectedSourceSha": head}

        self.assertTrue(
            enterprise_readiness_audit.report_matches_head(
                report,
                head,
                [("gitHeadAtVerification",), ("expectedSourceSha",)],
            )
        )

    def test_enterprise_report_rejects_stale_head(self):
        blocker = enterprise_readiness_audit.stale_report_blocker(
            "Local route verification",
            {"gitHeadAtVerification": "old456"},
            "new789",
            [("gitHeadAtVerification",)],
        )

        self.assertIn("stale", blocker)
        self.assertIn("old456", blocker)
        self.assertIn("new789", blocker)

    def test_enterprise_check_passed_accepts_current_no_write_evidence(self):
        checks = [
            {"name": "live_latest_code_verifier", "ok": True},
            {"name": "package_check", "ok": False},
        ]

        self.assertTrue(enterprise_readiness_audit.check_passed(checks, "live_latest_code_verifier"))
        self.assertFalse(enterprise_readiness_audit.check_passed(checks, "package_check"))

    def test_build_report_freshness_reads_nested_sha(self):
        report = {"build": {"sourceSha": "abc123"}}

        self.assertEqual(
            "abc123",
            build_readiness_reports.report_sha(report, [("build", "sourceSha")]),
        )
        self.assertTrue(
            build_readiness_reports.report_matches_head(
                report,
                "abc123",
                [("build", "sourceSha")],
            )
        )

    def test_build_report_rejects_stale_enterprise_summary(self):
        enterprise = {"summary": {"currentGitHead": "old456"}}

        self.assertFalse(build_readiness_reports.enterprise_summary_is_current(enterprise, "new789"))

    def test_latest_code_live_deployed_uses_current_deploy_and_sha_evidence(self):
        deploy = {"claimBoundary": {"newCodeLiveDeployed": True}}
        live_latest = {"sourceShaMatchesExpected": True}

        self.assertTrue(build_readiness_reports.latest_code_live_deployed(deploy, live_latest))
        self.assertFalse(build_readiness_reports.latest_code_live_deployed(deploy, {"sourceShaMatchesExpected": False}))

    def test_github_blocker_includes_previous_public_safe_evidence(self):
        blocker = build_readiness_reports.github_blocker_text(
            {
                "blocker": "Could not read GitHub Actions public API.",
                "previousReport": {"blocker": "Previous CI did not start."},
            }
        )

        self.assertIn("Could not read", blocker)
        self.assertIn("Previous CI did not start", blocker)

    def test_report_freshness_model_requires_post_commit_no_write_evidence(self):
        self.assertIn("point_in_time_snapshots", build_readiness_reports.REPORT_FRESHNESS_MODEL)
        self.assertIn("no-write checks", build_readiness_reports.REPORT_FRESHNESS_MODEL)
        self.assertIn("current-worktree", enterprise_readiness_audit.REPORT_FRESHNESS_MODEL)

    def test_dogfood_gap_state_distinguishes_live_core_from_full_contract(self):
        current, needed = build_readiness_reports.dogfood_gap_state(
            {"liveCoreDogfoodVerified": True, "liveDogfoodVerified": False}
        )

        self.assertIn("Live core MATM dogfood is verified", current)
        self.assertIn("latest protected audit-log", current)
        self.assertIn("protected audit-log readback", needed)

    def test_dogfood_gap_state_reports_full_live_contract(self):
        current, needed = build_readiness_reports.dogfood_gap_state(
            {"liveCoreDogfoodVerified": True, "liveDogfoodVerified": True}
        )

        self.assertIn("Full live dogfood contract verified", current)
        self.assertIn("After each latest-code deploy", needed)


if __name__ == "__main__":
    unittest.main()
