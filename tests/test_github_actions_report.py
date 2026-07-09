import unittest
from pathlib import Path

from scripts import check_github_actions


ROOT = Path(__file__).resolve().parents[1]


class GitHubActionsReportTests(unittest.TestCase):
    def test_ci_workflow_requires_source_sha_provenance(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("MEMORYENDPOINTS_SOURCE_SHA", workflow)
        self.assertIn("--expect-source-sha", workflow)
        self.assertIn("$GITHUB_SHA", workflow)

    def test_failed_run_with_zero_steps_is_external_gate(self):
        runs_payload = {
            "workflow_runs": [
                {
                    "id": 123,
                    "name": "CI",
                    "head_branch": "main",
                    "head_sha": "abc123",
                    "html_url": "https://github.com/example/repo/actions/runs/123",
                    "status": "completed",
                    "conclusion": "failure",
                    "run_number": 9,
                }
            ]
        }
        jobs_by_run_id = {
            123: {
                "jobs": [
                    {
                        "name": "Verify stdlib MATM app",
                        "status": "completed",
                        "conclusion": "failure",
                        "steps": [],
                    }
                ]
            }
        }

        report = check_github_actions.build_report(
            "example/repo",
            "main",
            "CI",
            runs_payload,
            jobs_by_run_id,
            generated_at="test-time",
        )

        self.assertFalse(report["ok"])
        self.assertEqual("abc123", report["latestObservedHeadSha"])
        self.assertEqual(1, report["latestObservedJobCount"])
        self.assertEqual(0, report["latestObservedJobStepCount"])
        self.assertIn("zero recorded steps", report["blocker"])
        self.assertTrue(report["valuesRedacted"])

    def test_public_annotation_becomes_specific_blocker(self):
        runs_payload = {
            "workflow_runs": [
                {
                    "id": 789,
                    "name": "CI",
                    "head_branch": "main",
                    "head_sha": "ghi789",
                    "html_url": "https://github.com/example/repo/actions/runs/789",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        }
        jobs_by_run_id = {
            789: {
                "jobs": [
                    {
                        "steps": [],
                        "checkRun": {
                            "annotations": [
                                {
                                    "annotationLevel": "failure",
                                    "path": ".github",
                                    "message": "The job was not started because your account is locked due to a billing issue.",
                                    "valuesRedacted": True,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        report = check_github_actions.build_report(
            "example/repo",
            "main",
            "CI",
            runs_payload,
            jobs_by_run_id,
            generated_at="test-time",
        )

        self.assertFalse(report["ok"])
        self.assertEqual(1, report["latestObservedJobAnnotationCount"])
        self.assertIn("billing issue", report["blocker"])
        self.assertIn(".github", report["latestObservedJobAnnotations"][0]["path"])

    def test_annotation_text_redacts_secret_like_values(self):
        sensitive_value = "abcdefghijklm" + "nopqrstuvwxyz"
        message = "token" + ": " + sensitive_value
        annotation = check_github_actions.safe_annotation(
            {
                "annotation_level": "failure",
                "path": ".github",
                "message": message,
            }
        )

        self.assertNotIn(sensitive_value, annotation["message"])
        self.assertIn("[redacted]", annotation["message"])

    def test_successful_run_passes(self):
        runs_payload = {
            "workflow_runs": [
                {
                    "id": 456,
                    "name": "CI",
                    "head_branch": "main",
                    "head_sha": "def456",
                    "html_url": "https://github.com/example/repo/actions/runs/456",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        }
        jobs_by_run_id = {456: {"jobs": [{"steps": [{"name": "Run tests"}]}]}}

        report = check_github_actions.build_report(
            "example/repo",
            "main",
            "CI",
            runs_payload,
            jobs_by_run_id,
            generated_at="test-time",
        )

        self.assertTrue(report["ok"])
        self.assertIsNone(report["blocker"])
        self.assertEqual(1, report["latestObservedJobStepCount"])


if __name__ == "__main__":
    unittest.main()
