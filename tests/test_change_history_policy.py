import copy
import json
import unittest

from memoryendpoints.change_history import (
    AGENT_CREDENTIAL_SESSION,
    COMPANY_MASTER_CREDENTIAL_SESSION,
    COMPANY_SOFT_DELETE,
    COMPANY_STORAGE_QUOTA_BYTES,
    FREE_COMPANY_ROUTINE_HISTORY_RETENTION_DAYS,
    HUMAN_OWNER_SESSION,
    PENDING_HUMAN_REVIEW,
    UNDONE_BY_HUMAN,
    ChangeHistoryPolicyError,
    HumanOwnerSessionRequired,
    agent_mutation_projection,
    apply_agent_mutation,
    authorize_permanent_company_purge,
    execute_clear_all_history,
    history_records_for_human,
    plan_clear_all_history,
    prune_routine_history,
    required_permanent_purge_confirmation,
    restore_soft_deleted_company,
    review_history_record,
    summarize_company_history_usage,
)


class ChangeHistoryPolicyTests(unittest.TestCase):
    def _update(self, history_id="history-update", recorded_at="2026-01-03T00:00:00Z"):
        return apply_agent_mutation(
            history_id=history_id,
            company_id="company-one",
            agent_id="useful-human-readable-agent",
            operation="update",
            resource_type="memory",
            resource_id="memory-one",
            before_snapshot={"summary": "before", "companyMasterTokenSecret": "must-not-survive"},
            after_snapshot={"summary": "after", "nested": {"invite_secret": "must-not-survive"}},
            recorded_at=recorded_at,
        )

    def _company_delete(self, recorded_at="2020-01-01T00:00:00Z"):
        return apply_agent_mutation(
            history_id="history-company-delete",
            company_id="company-one",
            agent_id="company-housekeeper",
            operation="delete",
            resource_type="company",
            resource_id="company-one",
            before_snapshot={"companyId": "company-one", "name": "Example Company", "active": True},
            after_snapshot=None,
            recorded_at=recorded_at,
        )

    def test_free_policy_constants_are_seven_days_and_two_hundred_mib(self):
        self.assertEqual(7, FREE_COMPANY_ROUTINE_HISTORY_RETENTION_DAYS)
        self.assertEqual(200 * 1024 * 1024, COMPANY_STORAGE_QUOTA_BYTES)

    def test_agent_update_applies_immediately_but_history_is_hidden_and_redacted(self):
        before = {"summary": "before", "companyMasterTokenSecret": "must-not-survive"}
        after = {"summary": "after", "nested": {"invite_secret": "must-not-survive"}}
        original_before = copy.deepcopy(before)
        original_after = copy.deepcopy(after)
        result = apply_agent_mutation(
            history_id="history-update",
            company_id="company-one",
            agent_id="useful-human-readable-agent",
            operation="update",
            resource_type="memory",
            resource_id="memory-one",
            before_snapshot=before,
            after_snapshot=after,
            recorded_at="2026-01-03T00:00:00Z",
        )

        self.assertTrue(result["application"]["applied"])
        self.assertEqual("after", result["application"]["currentState"]["summary"])
        history = result["historyRecord"]
        self.assertEqual(PENDING_HUMAN_REVIEW, history["review"]["state"])
        self.assertTrue(history["visibility"]["humanOwnerSessionOnly"])
        self.assertTrue(history["visibility"]["includedInCompanyExport"])
        self.assertEqual("[REDACTED_SECRET]", history["beforeSnapshot"]["companyMasterTokenSecret"])
        self.assertEqual("[REDACTED_SECRET]", history["afterSnapshot"]["nested"]["invite_secret"])
        self.assertNotIn("must-not-survive", json.dumps(result))
        self.assertEqual(original_before, before)
        self.assertEqual(original_after, after)

        agent_view = agent_mutation_projection(result)
        serialized_agent_view = json.dumps(agent_view)
        self.assertTrue(agent_view["applied"])
        self.assertNotIn("history", serialized_agent_view.lower())
        self.assertNotIn("before", serialized_agent_view.lower())
        self.assertNotIn("undo", serialized_agent_view.lower())
        self.assertNotIn("review", serialized_agent_view.lower())

    def test_agent_delete_is_immediate_and_agent_cannot_read_forensic_history(self):
        result = apply_agent_mutation(
            history_id="history-delete",
            company_id="company-one",
            agent_id="cleanup-agent",
            operation="delete",
            resource_type="task",
            resource_id="task-one",
            before_snapshot={"taskId": "task-one", "label": "Current task"},
            after_snapshot=None,
            recorded_at="2026-01-03T00:00:00Z",
        )
        agent_view = agent_mutation_projection(result)
        self.assertTrue(agent_view["deleted"])
        self.assertIsNone(agent_view["currentState"])
        for denied_session in (AGENT_CREDENTIAL_SESSION, COMPANY_MASTER_CREDENTIAL_SESSION):
            with self.subTest(session=denied_session):
                with self.assertRaises(HumanOwnerSessionRequired):
                    history_records_for_human([result["historyRecord"]], session_kind=denied_session)
        human_records = history_records_for_human(
            [result["historyRecord"]],
            session_kind=HUMAN_OWNER_SESSION,
            now="2026-01-04T00:00:00Z",
        )
        self.assertEqual("Current task", human_records[0]["beforeSnapshot"]["label"])

    def test_human_history_access_is_seven_days_without_truncating_agent_state(self):
        old = self._update("history-old", "2026-01-02T23:59:59Z")
        boundary = self._update("history-boundary", "2026-01-03T00:00:00Z")
        company = self._company_delete(recorded_at="2000-01-01T00:00:00Z")
        visible = history_records_for_human(
            [old["historyRecord"], boundary["historyRecord"], company["historyRecord"]],
            session_kind=HUMAN_OWNER_SESSION,
            now="2026-01-10T00:00:00Z",
        )
        self.assertEqual(
            {"history-boundary", "history-company-delete"},
            {record["historyId"] for record in visible},
        )
        self.assertEqual("after", old["application"]["currentState"]["summary"])
        self.assertEqual("after", boundary["application"]["currentState"]["summary"])

    def test_only_human_owner_can_review_and_undo_without_clobbering_newer_state(self):
        result = self._update()
        record = result["historyRecord"]
        with self.assertRaises(HumanOwnerSessionRequired):
            review_history_record(
                record,
                current_state=result["application"]["currentState"],
                action="undo",
                human_actor_id="owner-one",
                reviewed_at="2026-01-04T00:00:00Z",
                session_kind=AGENT_CREDENTIAL_SESSION,
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            review_history_record(
                record,
                current_state={"summary": "a newer change"},
                action="undo",
                human_actor_id="owner-one",
                reviewed_at="2026-01-04T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
            )

        undone = review_history_record(
            record,
            current_state=result["application"]["currentState"],
            action="undo",
            human_actor_id="owner-one",
            reviewed_at="2026-01-04T00:00:00Z",
            session_kind=HUMAN_OWNER_SESSION,
        )
        self.assertTrue(undone["application"]["applied"])
        self.assertEqual("before", undone["application"]["currentState"]["summary"])
        self.assertEqual(UNDONE_BY_HUMAN, undone["historyRecord"]["review"]["state"])
        self.assertTrue(undone["historyRecord"]["undo"]["used"])

    def test_routine_undo_expires_but_company_soft_delete_restore_never_expires(self):
        routine = self._update(recorded_at="2026-01-03T00:00:00Z")
        with self.assertRaises(ChangeHistoryPolicyError):
            review_history_record(
                routine["historyRecord"],
                current_state=routine["application"]["currentState"],
                action="undo",
                human_actor_id="owner-one",
                reviewed_at="2026-01-10T00:00:01Z",
                session_kind=HUMAN_OWNER_SESSION,
            )

        company = self._company_delete(recorded_at="2001-01-01T00:00:00Z")
        restored = restore_soft_deleted_company(
            company["historyRecord"],
            human_actor_id="owner-one",
            restored_at="2099-12-31T23:59:59Z",
            session_kind=HUMAN_OWNER_SESSION,
        )
        self.assertEqual("Example Company", restored["application"]["currentState"]["name"])
        self.assertFalse(restored["historyRecord"]["softDelete"]["isDeleted"])

    def test_pruning_uses_strict_seven_day_boundary_and_never_prunes_company_delete(self):
        old = self._update("history-old", "2026-01-02T23:59:59Z")["historyRecord"]
        boundary = self._update("history-boundary", "2026-01-03T00:00:00Z")["historyRecord"]
        company = self._company_delete(recorded_at="2000-01-01T00:00:00Z")["historyRecord"]
        result = prune_routine_history(
            [old, boundary, company],
            company_id="company-one",
            now="2026-01-10T00:00:00Z",
        )
        self.assertEqual(["history-old"], result["prunedHistoryIds"])
        self.assertEqual(
            {"history-boundary", "history-company-delete"},
            {record["historyId"] for record in result["records"]},
        )
        company_record = next(
            record for record in result["records"] if record["historyClass"] == COMPANY_SOFT_DELETE
        )
        self.assertTrue(company_record["quota"]["counted"])
        usage = summarize_company_history_usage(result["records"], company_id="company-one")
        self.assertGreater(usage["softDeleteHistoryBytes"], 0)
        self.assertEqual(COMPANY_STORAGE_QUOTA_BYTES, usage["companyLimitBytes"])

    def test_clear_all_history_is_human_export_gated_and_preserves_company_delete(self):
        routine = self._update()["historyRecord"]
        company = self._company_delete()["historyRecord"]
        records = [routine, company]
        original = copy.deepcopy(records)
        with self.assertRaises(ChangeHistoryPolicyError):
            plan_clear_all_history(
                records,
                company_id="company-one",
                human_actor_id="owner-one",
                requested_at="2026-01-11T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
                export_opportunity_acknowledged=False,
            )
        with self.assertRaises(HumanOwnerSessionRequired):
            plan_clear_all_history(
                records,
                company_id="company-one",
                human_actor_id="owner-one",
                requested_at="2026-01-11T00:00:00Z",
                session_kind=COMPANY_MASTER_CREDENTIAL_SESSION,
                export_opportunity_acknowledged=True,
            )

        plan = plan_clear_all_history(
            records,
            company_id="company-one",
            human_actor_id="owner-one",
            requested_at="2026-01-11T00:00:00Z",
            session_kind=HUMAN_OWNER_SESSION,
            export_opportunity_acknowledged=True,
            export_receipt_digest="sha256-public-receipt",
        )
        self.assertEqual(["history-update"], plan["historyIdsToClear"])
        self.assertEqual(["history-company-delete"], plan["historyIdsPreserved"])
        result = execute_clear_all_history(
            records,
            plan,
            human_actor_id="owner-one",
            completed_at="2026-01-11T00:00:01Z",
            session_kind=HUMAN_OWNER_SESSION,
        )
        self.assertEqual(["history-update"], result["clearedHistoryIds"])
        self.assertEqual(["history-company-delete"], result["preservedHistoryIds"])
        self.assertEqual(1, len(result["remainingRecords"]))
        self.assertTrue(result["exportDownloaded"])
        self.assertEqual(original, records)

    def test_permanent_company_purge_is_separate_human_only_and_exactly_confirmed(self):
        record = self._company_delete()["historyRecord"]
        phrase = required_permanent_purge_confirmation("company-one")
        with self.assertRaises(HumanOwnerSessionRequired):
            authorize_permanent_company_purge(
                record,
                human_actor_id="not-a-human-session",
                authorized_at="2026-01-11T00:00:00Z",
                session_kind=AGENT_CREDENTIAL_SESSION,
                export_opportunity_acknowledged=True,
                confirmation_phrase=phrase,
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            authorize_permanent_company_purge(
                record,
                human_actor_id="owner-one",
                authorized_at="2026-01-11T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
                export_opportunity_acknowledged=True,
                confirmation_phrase="DELETE",
            )
        authorization = authorize_permanent_company_purge(
            record,
            human_actor_id="owner-one",
            authorized_at="2026-01-11T00:00:00Z",
            session_kind=HUMAN_OWNER_SESSION,
            export_opportunity_acknowledged=True,
            confirmation_phrase=phrase,
        )
        self.assertTrue(authorization["irreversible"])
        self.assertTrue(authorization["humanOwnerSessionVerified"])
        self.assertTrue(authorization["removeUnderlyingCompanyData"])


if __name__ == "__main__":
    unittest.main()
