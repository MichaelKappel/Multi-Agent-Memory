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

    def test_enterprise_dogfood_state_accepts_successful_current_evidence(self):
        state = enterprise_readiness_audit.dogfood_verification_state(
            {"localDogfoodVerified": False, "liveCoreDogfoodVerified": True, "liveDogfoodVerified": False},
            {"localDogfoodVerified": True, "liveCoreDogfoodVerified": True, "liveDogfoodVerified": True},
            current_check_passed=True,
        )

        self.assertTrue(state["localDogfoodVerified"])
        self.assertTrue(state["liveCoreDogfoodVerified"])
        self.assertTrue(state["liveDogfoodVerified"])

    def test_enterprise_dogfood_state_ignores_failed_current_evidence(self):
        state = enterprise_readiness_audit.dogfood_verification_state(
            {"localDogfoodVerified": False, "liveCoreDogfoodVerified": True, "liveDogfoodVerified": False},
            {"localDogfoodVerified": True, "liveCoreDogfoodVerified": True, "liveDogfoodVerified": True},
            current_check_passed=False,
        )

        self.assertFalse(state["localDogfoodVerified"])
        self.assertTrue(state["liveCoreDogfoodVerified"])
        self.assertFalse(state["liveDogfoodVerified"])

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

    def test_source_dirty_paths_ignore_generated_reports(self):
        dirty = build_readiness_reports.source_dirty_paths(
            [
                " M docs/reports/final-readiness-report.md",
                " M memoryendpoints/app.py",
                "?? docs/reports/local-only.json",
                "?? scripts/new_tool.py",
            ]
        )

        self.assertEqual(["memoryendpoints/app.py", "scripts/new_tool.py"], dirty)

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

    def test_local_dogfood_verified_accepts_dedicated_local_report(self):
        self.assertTrue(
            build_readiness_reports.local_dogfood_verified(
                {"mode": "live_http", "localDogfoodVerified": False, "liveDogfoodVerified": True},
                {"mode": "local_wsgi", "localDogfoodVerified": True},
            )
        )
        self.assertFalse(
            build_readiness_reports.local_dogfood_verified(
                {"mode": "live_http", "localDogfoodVerified": False},
                {"mode": "local_wsgi", "localDogfoodVerified": False},
            )
        )

    def test_dogfood_memory_loop_summary_reports_source_readback(self):
        summary = build_readiness_reports.dogfood_memory_loop_summary(
            {
                "meetingMemoryPromotionVerified": True,
                "meetingMemoryReadbackVerified": True,
                "meetingMemorySourceReadbackVerified": True,
            }
        )

        self.assertIn("dogfooded into hosted memory", summary)
        self.assertIn("source meeting-message id readback", summary)

    def test_dogfood_memory_loop_summary_lists_missing_checks(self):
        summary = build_readiness_reports.dogfood_memory_loop_summary(
            {
                "meetingMemoryPromotionVerified": True,
                "meetingMemoryReadbackVerified": False,
                "meetingMemorySourceReadbackVerified": False,
            }
        )

        self.assertIn("promoted-memory readback", summary)
        self.assertIn("source-id readback", summary)

    def test_dogfood_memory_loop_summary_distinguishes_local_proof(self):
        summary = build_readiness_reports.dogfood_memory_loop_summary(
            {},
            {
                "meetingMemoryPromotionVerified": True,
                "meetingMemoryReadbackVerified": True,
                "meetingMemorySourceReadbackVerified": True,
            },
        )

        self.assertIn("local WSGI dogfood", summary)
        self.assertIn("live dogfood must be rerun", summary)

    def test_dogfood_memory_loop_evidence_separates_local_and_live_scope(self):
        evidence = build_readiness_reports.dogfood_memory_loop_evidence(
            {
                "mode": "combined",
                "runs": [
                    {
                        "mode": "local_wsgi",
                        "meetingMemoryPromotionVerified": True,
                        "meetingMemoryReadbackVerified": True,
                        "meetingMemorySourceReadbackVerified": True,
                    },
                    {
                        "mode": "live_http",
                        "meetingMemoryPromotionVerified": False,
                        "meetingMemoryReadbackVerified": False,
                        "meetingMemorySourceReadbackVerified": False,
                    },
                ],
            }
        )

        self.assertTrue(evidence["meetingMemoryPromotionVerified"])
        self.assertTrue(evidence["meetingMemoryReadbackVerified"])
        self.assertTrue(evidence["meetingMemorySourceReadbackVerified"])
        self.assertTrue(evidence["localMeetingMemorySourceReadbackVerified"])
        self.assertFalse(evidence["liveMeetingMemorySourceReadbackVerified"])
        self.assertEqual("local_verified_live_pending", evidence["meetingMemoryEvidenceScope"])

    def test_current_message_contract_evidence_separates_behavior_from_discovery(self):
        evidence = build_readiness_reports.current_message_contract_evidence(
            {
                "ok": True,
                "sourceSha": "abc123",
                "broadcast": {
                    "ok": True,
                    "uniqueRecipientNotificationIds": True,
                    "distinctNotificationIdCount": 3,
                    "expectedNotificationIdCount": 3,
                },
                "acknowledgementIsolation": {
                    "ok": True,
                    "visibleAfterAckAgents": ["human-verifier-agent", "swarm-observer-agent"],
                },
                "messageTypesVerified": {
                    "broadcast": True,
                    "targetedToBackend": True,
                    "targetedToHuman": True,
                },
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
            },
            {
                "ok": False,
                "sourceSha": "abc123",
                "connectorContract": {
                    "broadcastFanoutAdvertised": False,
                    "ackIsolationAdvertised": False,
                    "visibleAgentsConfirmationAdvertised": False,
                    "recipientCountConfirmationAdvertised": True,
                },
                "capabilityMatrix": {
                    "broadcastFanoutAdvertised": True,
                    "ackIsolationAdvertised": False,
                    "visibleAgentsConfirmationAdvertised": True,
                },
            },
        )

        self.assertTrue(evidence["behaviorVerified"])
        self.assertFalse(evidence["discoveryVerified"])
        self.assertFalse(evidence["contractVerified"])
        self.assertTrue(evidence["uniqueRecipientNotificationIds"])
        self.assertTrue(evidence["ackIsolationVerified"])
        self.assertIn("discovery still lacks", evidence["state"])
        self.assertIn("verify_live_connector_contract", evidence["needed"])

    def test_current_message_contract_evidence_accepts_full_contract(self):
        evidence = build_readiness_reports.current_message_contract_evidence(
            {
                "ok": True,
                "broadcast": {"ok": True, "uniqueRecipientNotificationIds": True},
                "acknowledgementIsolation": {"ok": True},
                "messageTypesVerified": {
                    "broadcast": True,
                    "targetedToBackend": True,
                    "targetedToHuman": True,
                },
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
            },
            {
                "ok": True,
                "connectorContract": {
                    "broadcastFanoutAdvertised": True,
                    "ackIsolationAdvertised": True,
                    "visibleAgentsConfirmationAdvertised": True,
                    "recipientCountConfirmationAdvertised": True,
                },
                "capabilityMatrix": {
                    "broadcastFanoutAdvertised": True,
                    "ackIsolationAdvertised": True,
                    "visibleAgentsConfirmationAdvertised": True,
                },
            },
        )

        self.assertTrue(evidence["contractVerified"])
        self.assertIn("Full live current-message", evidence["state"])

    def test_live_memory_submit_consistency_accepts_durable_readback(self):
        evidence = build_readiness_reports.live_memory_submit_consistency_evidence(
            {
                "ok": True,
                "sourceSha": "abc123",
                "probeCount": 2,
                "passedCount": 2,
                "failedCount": 0,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "probes": [
                    {
                        "ok": True,
                        "mismatches": [],
                        "readbackAttemptsUsed": 1,
                        "durableReadback": {
                            "exactSearchCount": 1,
                            "reviewQueueMatchCount": 1,
                            "auditMatchCount": 1,
                        },
                    },
                    {
                        "ok": True,
                        "mismatches": [],
                        "readbackAttemptsUsed": 2,
                        "durableReadback": {
                            "exactSearchCount": 1,
                            "reviewQueueMatchCount": 1,
                            "auditMatchCount": 1,
                        },
                    },
                ],
            }
        )

        self.assertTrue(evidence["verified"])
        self.assertTrue(evidence["probeReadbackVerified"])
        self.assertEqual(2, evidence["maxReadbackAttemptsUsed"])
        self.assertIn("response/readback consistency is verified", evidence["state"])

    def test_live_memory_submit_consistency_rejects_response_overclaim(self):
        evidence = build_readiness_reports.live_memory_submit_consistency_evidence(
            {
                "ok": True,
                "probeCount": 1,
                "passedCount": 1,
                "failedCount": 0,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "probes": [
                    {
                        "ok": False,
                        "mismatches": ["response_visible_search_without_exact_readback"],
                        "durableReadback": {
                            "exactSearchCount": 0,
                            "reviewQueueMatchCount": 1,
                            "auditMatchCount": 1,
                        },
                    }
                ],
            }
        )

        self.assertFalse(evidence["verified"])
        self.assertFalse(evidence["probeReadbackVerified"])
        self.assertIn("not fully proven", evidence["state"])
        self.assertIn("verify_live_memory_submit_consistency", evidence["needed"])

    def test_hosted_long_term_memory_evidence_requires_promoted_hosted_records(self):
        evidence = build_readiness_reports.hosted_long_term_memory_evidence(
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "searchReadback": {
                    "allExpectedSourcesFound": True,
                    "expectedSourcePathCount": 2,
                    "matchedSourcePathCount": 2,
                    "missingSourcePaths": [],
                    "unexpectedHostedSourcePaths": [],
                    "memorySource": "hosted_workspace_store",
                    "filesystemDocsIncluded": False,
                    "currentAllPromoted": True,
                    "currentReviewStatusCounts": {"promoted": 2},
                    "currentPromotionStateCounts": {"promoted": 2},
                },
            },
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "verification": {"allPromoted": True},
            },
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "verification": {"remainingDuplicateCount": 0},
            },
        )

        self.assertTrue(evidence["verified"])
        self.assertTrue(evidence["sourcePathsVerified"])
        self.assertTrue(evidence["hostedStoreVerified"])
        self.assertTrue(evidence["currentAllPromoted"])
        self.assertTrue(evidence["duplicateCleanupVerified"])
        self.assertIn("Hosted long-term memory is promoted", evidence["state"])

    def test_hosted_long_term_memory_evidence_rejects_filesystem_or_pending_records(self):
        evidence = build_readiness_reports.hosted_long_term_memory_evidence(
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "searchReadback": {
                    "allExpectedSourcesFound": True,
                    "expectedSourcePathCount": 2,
                    "matchedSourcePathCount": 2,
                    "missingSourcePaths": [],
                    "unexpectedHostedSourcePaths": [],
                    "memorySource": "filesystem_docs",
                    "filesystemDocsIncluded": True,
                    "currentAllPromoted": False,
                    "currentReviewStatusCounts": {"pending": 2},
                    "currentPromotionStateCounts": {"review_pending": 2},
                },
            },
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "verification": {"allPromoted": False},
            },
            {
                "ok": True,
                "rawCredentialValuesStored": False,
                "rawWorkspaceIdStored": False,
                "verification": {"remainingDuplicateCount": 0},
            },
        )

        self.assertFalse(evidence["verified"])
        self.assertFalse(evidence["hostedStoreVerified"])
        self.assertFalse(evidence["currentAllPromoted"])
        self.assertIn("not fully proven", evidence["state"])


if __name__ == "__main__":
    unittest.main()
