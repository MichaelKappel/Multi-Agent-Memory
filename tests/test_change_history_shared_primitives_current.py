"""Shared current edge coverage for the identical change-history policy module.

This file is intentionally byte-identical in MemoryEndpoints.com and
Multi-Agent-Memory.  It exercises policy failures and the accept path that
the broader lifecycle tests do not need to visit.
"""

import unittest

from memoryendpoints.change_history import (
    AGENT_CREDENTIAL_SESSION,
    COMPANY_MASTER_CREDENTIAL_SESSION,
    COMPANY_SOFT_DELETE,
    HUMAN_OWNER_SESSION,
    ChangeHistoryPolicyError,
    HumanOwnerSessionRequired,
    _assert_company_records,
    _history_id,
    _json_copy,
    _record_company,
    _required_text,
    _routine_expiry,
    _utc_datetime,
    apply_agent_mutation,
    authorize_permanent_company_purge,
    execute_clear_all_history,
    history_records_for_human,
    plan_clear_all_history,
    prune_routine_history,
    required_permanent_purge_confirmation,
    restore_soft_deleted_company,
    review_history_record,
)


class SharedChangeHistoryPrimitivesCurrentTests(unittest.TestCase):
    def _update(self, history_id="history-shared-update"):
        return apply_agent_mutation(
            history_id=history_id,
            company_id="company-one",
            agent_id="shared-policy-agent",
            operation="update",
            resource_type="memory",
            resource_id="memory-one",
            before_snapshot={"summary": "before"},
            after_snapshot={"summary": "after"},
            recorded_at="2026-01-03T00:00:00Z",
        )

    def _company_delete(self):
        return apply_agent_mutation(
            history_id="history-shared-delete",
            company_id="company-one",
            agent_id="shared-policy-agent",
            operation="delete",
            resource_type="company",
            resource_id="company-one",
            before_snapshot={"companyId": "company-one", "active": True},
            after_snapshot=None,
            recorded_at="2020-01-01T00:00:00Z",
        )

    def test_shared_policy_rejects_malformed_records_and_inputs(self):
        for function, args in (
            (_required_text, (" ", "label")),
            (_utc_datetime, ("2026-01-03T00:00:00", "recorded_at")),
            (_utc_datetime, ("not-a-timestamp", "recorded_at")),
            (_json_copy, (object(), "snapshot")),
            (_history_id, (None,)),
            (_record_company, ({},)),
            (_routine_expiry, ("2026-01-03T00:00:00Z", True)),
        ):
            with self.subTest(function=function.__name__):
                with self.assertRaises(ChangeHistoryPolicyError):
                    function(*args)

        valid = self._update()["historyRecord"]
        for records, company_id in (
            ([valid, dict(valid)], "company-one"),
            ([dict(valid, companyId="other-company")], "company-one"),
        ):
            with self.subTest(company_id=company_id, records=len(records)):
                with self.assertRaises(ChangeHistoryPolicyError):
                    _assert_company_records(records, company_id)

        with self.assertRaises(ChangeHistoryPolicyError):
            apply_agent_mutation(
                history_id="bad-operation",
                company_id="company-one",
                agent_id="agent-one",
                operation="replace",
                resource_type="memory",
                resource_id="memory-one",
                before_snapshot={},
                after_snapshot={},
                recorded_at="2026-01-03T00:00:00Z",
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            apply_agent_mutation(
                history_id="bad-delete",
                company_id="company-one",
                agent_id="agent-one",
                operation="delete",
                resource_type="memory",
                resource_id="memory-one",
                before_snapshot={},
                after_snapshot={},
                recorded_at="2026-01-03T00:00:00Z",
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            apply_agent_mutation(
                history_id="bad-update",
                company_id="company-one",
                agent_id="agent-one",
                operation="update",
                resource_type="memory",
                resource_id="memory-one",
                before_snapshot={},
                after_snapshot=None,
                recorded_at="2026-01-03T00:00:00Z",
            )

    def test_accept_review_and_non_pending_or_non_undoable_states_are_typed(self):
        result = self._update()
        accepted = review_history_record(
            result["historyRecord"],
            current_state=result["application"]["currentState"],
            action="accept",
            human_actor_id="owner-one",
            reviewed_at="2026-01-04T00:00:00Z",
            session_kind=HUMAN_OWNER_SESSION,
        )
        self.assertFalse(accepted["application"]["applied"])
        self.assertEqual("reviewed_accepted", accepted["historyRecord"]["review"]["state"])
        with self.assertRaises(ChangeHistoryPolicyError):
            review_history_record(
                accepted["historyRecord"],
                current_state=result["application"]["currentState"],
                action="accept",
                human_actor_id="owner-one",
                reviewed_at="2026-01-04T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            review_history_record(
                result["historyRecord"],
                current_state=result["application"]["currentState"],
                action="other",
                human_actor_id="owner-one",
                reviewed_at="2026-01-04T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
            )

        record = dict(result["historyRecord"])
        record["undo"] = {"available": False}
        with self.assertRaises(ChangeHistoryPolicyError):
            review_history_record(
                record,
                current_state=result["application"]["currentState"],
                action="undo",
                human_actor_id="owner-one",
                reviewed_at="2026-01-04T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
            )

    def test_history_clear_restore_and_purge_integrity_guards_are_fail_closed(self):
        routine = self._update()["historyRecord"]
        company = self._company_delete()["historyRecord"]
        records = [routine, company]
        with self.assertRaises(ChangeHistoryPolicyError):
            history_records_for_human(
                records,
                session_kind=HUMAN_OWNER_SESSION,
                now=None,
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            prune_routine_history(
                records,
                company_id="company-one",
                now="2026-01-10T00:00:00Z",
                retention_days=True,
            )
        with self.assertRaises(ChangeHistoryPolicyError):
            restore_soft_deleted_company(
                routine,
                human_actor_id="owner-one",
                restored_at="2026-01-04T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
            )
        with self.assertRaises(HumanOwnerSessionRequired):
            history_records_for_human(
                records,
                session_kind=AGENT_CREDENTIAL_SESSION,
                now="2026-01-10T00:00:00Z",
            )
        with self.assertRaises(HumanOwnerSessionRequired):
            history_records_for_human(
                records,
                session_kind=COMPANY_MASTER_CREDENTIAL_SESSION,
                now="2026-01-10T00:00:00Z",
            )

        plan = plan_clear_all_history(
            records,
            company_id="company-one",
            human_actor_id="owner-one",
            requested_at="2026-01-11T00:00:00Z",
            session_kind=HUMAN_OWNER_SESSION,
            export_opportunity_acknowledged=True,
        )
        corrupt = dict(plan, planDigest="0" * 64)
        with self.assertRaises(ChangeHistoryPolicyError):
            execute_clear_all_history(
                records,
                corrupt,
                human_actor_id="owner-one",
                completed_at="2026-01-11T00:00:01Z",
                session_kind=HUMAN_OWNER_SESSION,
            )
        changed = dict(plan, historyIdsToClear=["unexpected-history"])
        with self.assertRaises(ChangeHistoryPolicyError):
            execute_clear_all_history(
                records,
                changed,
                human_actor_id="owner-one",
                completed_at="2026-01-11T00:00:01Z",
                session_kind=HUMAN_OWNER_SESSION,
            )

        phrase = required_permanent_purge_confirmation("company-one")
        with self.assertRaises(ChangeHistoryPolicyError):
            authorize_permanent_company_purge(
                routine,
                human_actor_id="owner-one",
                authorized_at="2026-01-11T00:00:00Z",
                session_kind=HUMAN_OWNER_SESSION,
                export_opportunity_acknowledged=True,
                confirmation_phrase=phrase,
            )


if __name__ == "__main__":
    unittest.main()

