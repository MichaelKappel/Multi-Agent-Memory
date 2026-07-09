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


if __name__ == "__main__":
    unittest.main()
