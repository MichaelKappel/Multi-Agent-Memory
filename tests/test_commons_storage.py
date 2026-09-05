import tempfile
import hashlib
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from memoryendpoints import storage as storage_module
from memoryendpoints.commons import CommonsContractError, request_digest
from memoryendpoints.commons_storage import CommonsRepository
from memoryendpoints.storage import FileStore, SQLiteStore
from memoryendpoints.config import utc_now
from tests.governed_test_support import DeterministicCredentialPepperMixin


def _candidate(character):
    digest = hashlib.sha256(str(character).encode("utf-8")).hexdigest()
    return "me_agent_v1.agenttoken-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


def _key(label):
    return (label + "-" + ("k" * 64))[:64]


def _browser_candidate(character="e"):
    digest = hashlib.sha256(str(character).encode("utf-8")).hexdigest()
    return "me_commonsbrowser_v1.commonsbrowser-%s.%s" % (
        digest[:20],
        (digest + digest)[:43],
    )


class CommonsStorageContractTests(
    DeterministicCredentialPepperMixin, unittest.TestCase
):
    STORE_TYPES = (FileStore, SQLiteStore)

    def _context(self, store_type, tempdir):
        suffix = "store.json" if store_type is FileStore else "store.sqlite3"
        store = store_type(Path(tempdir) / suffix)
        (
            workspace_id,
            _master_id,
            master_secret,
            _account_id,
            company_id,
            project_id,
            _human_secret,
        ) = store.create_free_account("Commons", "Commons", "Commons")
        settings = {
            "workspaceId": workspace_id,
            "projectId": project_id,
            "humanApprovalRequiredByDefault": False,
            "credentialTtlSeconds": 3600,
            "browserSessionTtlSeconds": 600,
            "enrollmentRequestTtlSeconds": 3600,
            "maximumActiveAgents": 100,
            "maximumPendingEnrollments": 10,
            "maximumRetainedAgents": 500,
            "maximumRetainedEnrollments": 500,
        }
        return (
            store,
            CommonsRepository(store, settings),
            workspace_id,
            project_id,
            company_id,
            master_secret,
        )

    def _enroll(self, repository, name, character):
        body = {
            "agentName": name,
            "displayName": name.title(),
            "candidateTokenSecret": _candidate(character),
        }
        result, replay = repository.enroll(
            name,
            name.title(),
            {
                "listed": True,
                "implementation": "contract test",
                "capabilities": ["commons"],
                "profileUrl": "",
                "capabilityUrl": "",
                "availability": "available",
            },
            body["candidateTokenSecret"],
            _key("enroll-" + name),
            request_digest(body),
        )
        self.assertFalse(replay)
        self.assertTrue(result["credentialAccepted"])
        self.assertNotIn("agentTokenSecret", result)
        return body["candidateTokenSecret"]

    def test_two_agent_revision_tombstone_cursor_and_session_contract(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, _master = self._context(store_type, tempdir)
                token_a = self._enroll(repository, "agent-alpha", "a")
                token_b = self._enroll(repository, "agent-beta", "b")
                auth_a = store.authenticate(token_a, workspace_id)
                auth_b = store.authenticate(token_b, workspace_id)
                self.assertEqual("project", auth_a["scopeType"])
                room_id = repository.room_id
                repository.set_membership(room_id, auth_a, "joined", _key("join-a"), request_digest({"join": "a"}))
                repository.set_membership(room_id, auth_b, "joined", _key("join-b"), request_digest({"join": "b"}))

                posted, replay = repository.publish(room_id, auth_a, "First public message", None, _key("post-a"), request_digest({"content": "First public message"}))
                self.assertFalse(replay)
                message_id = posted["messageId"]
                first_page = repository.list_messages(room_id, limit=1)
                self.assertEqual([message_id], [item["messageId"] for item in first_page["items"]])
                self.assertIsNotNone(first_page["nextCursor"])
                self.assertFalse(first_page["items"][0]["revisionHistoryIncluded"])

                reply, _ = repository.publish(room_id, auth_b, "A public reply", message_id, _key("reply-b"), request_digest({"content": "A public reply"}))
                polled = repository.list_messages(room_id, after=first_page["nextCursor"], limit=10)
                self.assertEqual([reply["messageId"]], [item["messageId"] for item in polled["items"]])
                forged = first_page["nextCursor"][:-1] + ("A" if first_page["nextCursor"][-1] != "A" else "B")
                with self.assertRaisesRegex(CommonsContractError, "cursor_invalid"):
                    repository.list_messages(room_id, after=forged)

                corrected, _ = repository.correct(message_id, auth_a, "Corrected public message", 1, _key("correct-a"), request_digest({"content": "Corrected public message"}))
                self.assertEqual(2, corrected["currentRevision"])
                self.assertEqual([1, 2], [item["revisionNumber"] for item in corrected["revisionHistory"]])
                with self.assertRaisesRegex(CommonsContractError, "revision_conflict"):
                    repository.acknowledge(
                        message_id,
                        auth_b,
                        posted["acknowledgementBinding"]["expectedRevision"],
                        posted["acknowledgementBinding"]["expectedRevisionId"],
                        posted["acknowledgementBinding"]["expectedState"],
                        posted["acknowledgementBinding"]["expectedWithdrawalId"],
                        _key("ack-stale"),
                        request_digest({"expectedRevision": 1}),
                    )
                acknowledged, _ = repository.acknowledge(
                    message_id,
                    auth_b,
                    corrected["acknowledgementBinding"]["expectedRevision"],
                    corrected["acknowledgementBinding"]["expectedRevisionId"],
                    corrected["acknowledgementBinding"]["expectedState"],
                    corrected["acknowledgementBinding"]["expectedWithdrawalId"],
                    _key("ack-current"),
                    request_digest({"expectedRevision": 2}),
                )
                self.assertTrue(acknowledged["acknowledgedByViewer"])

                reply_ack, _ = repository.acknowledge(
                    reply["messageId"],
                    auth_a,
                    reply["acknowledgementBinding"]["expectedRevision"],
                    reply["acknowledgementBinding"]["expectedRevisionId"],
                    reply["acknowledgementBinding"]["expectedState"],
                    reply["acknowledgementBinding"]["expectedWithdrawalId"],
                    _key("ack-reply-active"),
                    request_digest({"expectedRevision": 1, "expectedState": "current"}),
                )
                self.assertTrue(reply_ack["acknowledgedByViewer"])
                withdrawn, _ = repository.withdraw(reply["messageId"], auth_b, 1, _key("withdraw-b"), request_digest({"expectedRevision": 1}))
                self.assertEqual("withdrawn", withdrawn["state"])
                self.assertIsNone(withdrawn["content"])
                self.assertTrue(withdrawn["tombstone"]["withdrawn"])
                self.assertFalse(
                    repository.message(reply["messageId"], "agent-alpha")[
                        "acknowledgedByViewer"
                    ]
                )
                tombstone_ack, _ = repository.acknowledge(
                    reply["messageId"],
                    auth_a,
                    withdrawn["acknowledgementBinding"]["expectedRevision"],
                    withdrawn["acknowledgementBinding"]["expectedRevisionId"],
                    withdrawn["acknowledgementBinding"]["expectedState"],
                    withdrawn["acknowledgementBinding"]["expectedWithdrawalId"],
                    _key("ack-reply-tombstone"),
                    request_digest({"expectedRevision": 1, "expectedState": "withdrawn"}),
                )
                self.assertTrue(tombstone_ack["acknowledgedByViewer"])
                with self.assertRaisesRegex(CommonsContractError, "message_withdrawn"):
                    repository.correct(reply["messageId"], auth_b, "resurrection", 1, _key("resurrect-b"), request_digest({"content": "resurrection"}))

                session_secret = _browser_candidate()
                session_result, replay = repository.create_browser_session(
                    auth_a,
                    session_secret,
                    _key("browser-create"),
                    request_digest({"candidateBrowserSessionSecret": session_secret}),
                )
                self.assertFalse(replay)
                self.assertFalse(session_result["credentialReturnedOnce"])
                session_auth = repository.authenticate_browser_session(session_secret)
                self.assertEqual("commons_only", repository.current_browser_session(session_auth)["authority"])
                with self.assertRaisesRegex(CommonsContractError, "bearer_agent_credential_required"):
                    repository.create_browser_session(
                        session_auth,
                        _browser_candidate("f"),
                        _key("browser-chain"),
                        request_digest({"candidateBrowserSessionSecret": _browser_candidate("f")}),
                    )
                revoke_key = _key("browser-revoke")
                revoke_digest = request_digest(
                    {"schemaVersion": "memoryendpoints.commons_browser_session.v1"}
                )
                _session, replay = repository.revoke_browser_session(
                    session_auth, revoke_key, revoke_digest
                )
                self.assertFalse(replay)
                replay_auth = repository.authenticate_browser_session(session_secret, allow_revoked=True)
                _session, replay = repository.revoke_browser_session(
                    replay_auth, revoke_key, revoke_digest
                )
                self.assertTrue(replay)
                self.assertIsNone(repository.authenticate_browser_session(session_secret))

    def test_cross_resource_idempotency_is_exact(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, _master = self._context(store_type, tempdir)
                token_a = self._enroll(repository, "exact-agent-a", "exact-a")
                token_b = self._enroll(repository, "exact-agent-b", "exact-b")
                auth_a = store.authenticate(token_a, workspace_id)
                auth_b = store.authenticate(token_b, workspace_id)
                repository.set_membership(repository.room_id, auth_a, "joined", _key("exact-join-a"), request_digest({"state": "joined"}))
                repository.set_membership(repository.room_id, auth_b, "joined", _key("exact-join-b"), request_digest({"state": "joined"}))
                messages = []
                for index in range(4):
                    item, _replay = repository.publish(
                        repository.room_id,
                        auth_a,
                        "Message %d" % index,
                        None,
                        _key("exact-post-%d" % index),
                        request_digest({"content": "Message %d" % index}),
                    )
                    messages.append(item)

                correction_digest = request_digest(
                    {"content": "Same correction", "expectedRevision": 1}
                )
                repository.correct(
                    messages[0]["messageId"],
                    auth_a,
                    "Same correction",
                    1,
                    _key("cross-correction"),
                    correction_digest,
                )
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.correct(
                        messages[1]["messageId"],
                        auth_a,
                        "Same correction",
                        1,
                        _key("cross-correction"),
                        correction_digest,
                    )
                self.assertEqual(
                    1,
                    repository.message(messages[1]["messageId"])["currentRevision"],
                )

                withdrawal_digest = request_digest({"expectedRevision": 1})
                repository.withdraw(
                    messages[2]["messageId"],
                    auth_a,
                    1,
                    _key("cross-withdrawal"),
                    withdrawal_digest,
                )
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.withdraw(
                        messages[3]["messageId"],
                        auth_a,
                        1,
                        _key("cross-withdrawal"),
                        withdrawal_digest,
                    )
                self.assertEqual(
                    "current", repository.message(messages[3]["messageId"])["state"]
                )

                first_binding = repository.message(messages[0]["messageId"])[
                    "acknowledgementBinding"
                ]
                repository.acknowledge(
                    messages[0]["messageId"],
                    auth_b,
                    first_binding["expectedRevision"],
                    first_binding["expectedRevisionId"],
                    first_binding["expectedState"],
                    first_binding["expectedWithdrawalId"],
                    _key("cross-ack"),
                    request_digest(first_binding),
                )
                second_binding = repository.message(messages[1]["messageId"])[
                    "acknowledgementBinding"
                ]
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.acknowledge(
                        messages[1]["messageId"],
                        auth_b,
                        second_binding["expectedRevision"],
                        second_binding["expectedRevisionId"],
                        second_binding["expectedState"],
                        second_binding["expectedWithdrawalId"],
                        _key("cross-ack"),
                        request_digest(second_binding),
                    )

    def test_pending_candidate_alias_policy_flip_and_lifetime_caps(self):
        profile = {
            "listed": False,
            "implementation": "",
            "capabilities": [],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "",
        }
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(
                    master_auth,
                    True,
                    0,
                    _key("reservation-policy-on"),
                    request_digest({"humanApprovalRequired": True}),
                )
                token = _candidate("reserved-candidate")
                request_body = {"agentName": "reserved-agent", "candidateTokenSecret": token}
                pending, replay = repository.enroll(
                    "reserved-agent",
                    "Reserved Agent",
                    profile,
                    token,
                    _key("reservation-first"),
                    request_digest(request_body),
                )
                self.assertFalse(replay)
                alias_key = _key("reservation-alias")
                alias, replay = repository.enroll(
                    "reserved-agent",
                    "Reserved Agent",
                    profile,
                    token,
                    alias_key,
                    request_digest(request_body),
                )
                self.assertTrue(replay)
                self.assertEqual(
                    pending["enrollmentRequestId"], alias["enrollmentRequestId"]
                )
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.enroll(
                        "different-agent",
                        "Different Agent",
                        profile,
                        _candidate("different-candidate"),
                        alias_key,
                        request_digest({"agentName": "different-agent"}),
                    )

                decision_requests = []
                for index in range(2):
                    decision_pending, _ = repository.enroll(
                        "decision-agent-%d" % index,
                        "Decision Agent %d" % index,
                        profile,
                        _candidate("decision-candidate-%d" % index),
                        _key("decision-enroll-%d" % index),
                        request_digest({"agentName": "decision-agent-%d" % index}),
                    )
                    decision_requests.append(decision_pending)
                decision_key = _key("cross-enrollment-decision")
                decision_digest = request_digest({"expectedRevision": 1})
                repository.decide_enrollment(
                    master_auth,
                    decision_requests[0]["enrollmentRequestId"],
                    "denied",
                    1,
                    decision_key,
                    decision_digest,
                )
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.decide_enrollment(
                        master_auth,
                        decision_requests[1]["enrollmentRequestId"],
                        "denied",
                        1,
                        decision_key,
                        decision_digest,
                    )

                repository.set_policy(
                    master_auth,
                    False,
                    1,
                    _key("reservation-policy-off"),
                    request_digest({"humanApprovalRequired": False}),
                )
                with self.assertRaisesRegex(CommonsContractError, "enrollment_request_exists"):
                    repository.enroll(
                        "reserved-agent",
                        "Reserved Agent",
                        profile,
                        _candidate("reserved-name-new-candidate"),
                        _key("reservation-name-bypass"),
                        request_digest({"agentName": "reserved-agent", "attempt": 2}),
                    )
                self.assertIsNone(store.authenticate(token, workspace_id))

                repository.set_policy(
                    master_auth,
                    True,
                    2,
                    _key("reservation-policy-on-again"),
                    request_digest({"humanApprovalRequired": True, "revision": 2}),
                )
                repository.settings["maximumRetainedEnrollments"] = 3
                with self.assertRaisesRegex(
                    CommonsContractError, "enrollment_retention_capacity_reached"
                ):
                    repository.enroll(
                        "retention-blocked",
                        "Retention Blocked",
                        profile,
                        _candidate("retention-blocked"),
                        _key("retention-blocked"),
                        request_digest({"agentName": "retention-blocked"}),
                    )
                repository.set_policy(
                    master_auth,
                    False,
                    3,
                    _key("reservation-policy-final-off"),
                    request_digest({"humanApprovalRequired": False, "revision": 3}),
                )

                repository.settings["maximumRetainedAgents"] = 2
                self._enroll(repository, "capacity-agent-one", "cap-one")
                self._enroll(repository, "capacity-agent-two", "cap-two")
                with self.assertRaisesRegex(CommonsContractError, "agent_retention_capacity_reached"):
                    self._enroll(repository, "capacity-agent-three", "cap-three")

    def test_company_lifetime_ceilings_bound_projects(self):
        profile = {
            "listed": False,
            "implementation": "",
            "capabilities": [],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "",
        }
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                repository.settings["maximumRetainedAgents"] = 500
                repository.settings["maximumCompanyRetainedAgents"] = 2
                self._enroll(repository, "company-cap-one", "company-cap-one")
                self._enroll(repository, "company-cap-two", "company-cap-two")
                with self.assertRaisesRegex(
                    CommonsContractError, "company_agent_retention_capacity_reached"
                ):
                    self._enroll(repository, "company-cap-three", "company-cap-three")

                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(
                    master_auth,
                    True,
                    0,
                    _key("company-cap-policy"),
                    request_digest({"humanApprovalRequired": True}),
                )
                repository.settings["maximumRetainedEnrollments"] = 500
                repository.settings["maximumCompanyRetainedEnrollments"] = 2
                for index in range(2):
                    repository.enroll(
                        "company-pending-%d" % index,
                        "Company Pending %d" % index,
                        profile,
                        _candidate("company-pending-%d" % index),
                        _key("company-pending-%d" % index),
                        request_digest({"agentName": "company-pending-%d" % index}),
                    )
                with self.assertRaisesRegex(
                    CommonsContractError,
                    "company_enrollment_retention_capacity_reached",
                ):
                    repository.enroll(
                        "company-pending-three",
                        "Company Pending Three",
                        profile,
                        _candidate("company-pending-three"),
                        _key("company-pending-three"),
                        request_digest({"agentName": "company-pending-three"}),
                    )

    def test_layered_source_admission_preserves_shared_budget_and_bounds_partitions(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                suffix = "rates.json" if store_type is FileStore else "rates.sqlite3"
                store = store_type(Path(tempdir) / suffix)
                call = lambda source, now=1000, cap=4: store.consume_commons_layered_rate_limit(
                    "commonsSourceRequest",
                    "project-one|" + source,
                    2,
                    60,
                    "commonsProjectRequest",
                    "project-one",
                    3,
                    60,
                    cap,
                    now=now,
                )
                self.assertTrue(call("source-a")["allowed"])
                self.assertTrue(call("source-a")["allowed"])
                source_denied = call("source-a")
                self.assertFalse(source_denied["allowed"])
                self.assertEqual("source", source_denied["deniedLayer"])
                self.assertEqual(1, source_denied["project"]["remaining"])
                self.assertTrue(call("source-b")["allowed"])
                project_denied = call("source-c")
                self.assertFalse(project_denied["allowed"])
                self.assertEqual("project", project_denied["deniedLayer"])

                reset = 2000
                self.assertTrue(call("source-a", reset, 2)["allowed"])
                self.assertTrue(call("source-b", reset, 2)["allowed"])
                partition_denied = call("source-c", reset, 2)
                self.assertFalse(partition_denied["allowed"])
                self.assertEqual(
                    "source_partition_capacity", partition_denied["deniedLayer"]
                )
                if store_type is FileStore:
                    rows = list(
                        store._load().get("connectorRateLimits", {}).values()
                    )
                    live_sources = [
                        row
                        for row in rows
                        if row.get("bucket") == "commonsSourceRequest"
                        and int(row.get("expiresAtEpoch") or 0) > reset
                    ]
                else:
                    with store._open_connection() as connection:
                        live_sources = connection.execute(
                            "SELECT * FROM matm_connector_rate_limits WHERE "
                            "bucket = ? AND expires_at_epoch > ?",
                            ("commonsSourceRequest", reset),
                        ).fetchall()
                self.assertEqual(2, len(live_sources))
    def test_bounded_compaction_recovers_terminal_enrollment_and_unused_agent_slots(self):
        profile = {
            "listed": False,
            "implementation": "",
            "capabilities": [],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "",
        }
        old = "2000-01-01T00:00:00.000000Z"
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                repository.settings.update(
                    {
                        "maximumRetainedAgents": 1,
                        "maximumCompanyRetainedAgents": 100,
                        "maximumAgentTombstones": 10,
                        "maximumCompanyAgentTombstones": 100,
                        "maximumRetainedEnrollments": 1,
                        "maximumCompanyRetainedEnrollments": 100,
                        "maximumEnrollmentTombstones": 10,
                        "maximumCompanyEnrollmentTombstones": 100,
                        "terminalEnrollmentRetentionSeconds": 1,
                        "inactiveAgentRetentionSeconds": 1,
                    }
                )
                old_token = self._enroll(
                    repository, "compact-old-agent", "compact-old-agent"
                )
                old_auth = store.authenticate(old_token, workspace_id)
                repository.revoke_credential(
                    old_auth,
                    _key("compact-old-revoke"),
                    request_digest({"revoke": True}),
                )
                if store_type is FileStore:
                    data = store._load()
                    old_profile = next(
                        item
                        for item in data["commonsAgentProfiles"].values()
                        if item.get("agentId") == "compact-old-agent"
                    )
                    old_profile["updatedAt"] = old
                    store._save(data)
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.execute(
                                "UPDATE matm_commons_agent_profiles SET updated_at = ? "
                                "WHERE workspace_id = ? AND project_id = ? AND agent_id = ?",
                                (
                                    old,
                                    repository.workspace_id,
                                    repository.project_id,
                                    "compact-old-agent",
                                ),
                            )
                self._enroll(
                    repository, "compact-new-agent", "compact-new-agent"
                )
                self.assertIsNone(
                    repository.agent_profile("compact-old-agent", public_only=False)
                )
                self.assertIsNone(store.authenticate(old_token, workspace_id))
                old_replay, replayed = repository.enroll(
                    "compact-old-agent",
                    "Compact-Old-Agent",
                    {
                        "listed": True,
                        "implementation": "contract test",
                        "capabilities": ["commons"],
                        "profileUrl": "",
                        "capabilityUrl": "",
                        "availability": "available",
                    },
                    old_token,
                    _key("enroll-compact-old-agent"),
                    request_digest(
                        {
                            "agentName": "compact-old-agent",
                            "displayName": "Compact-Old-Agent",
                            "candidateTokenSecret": old_token,
                        }
                    ),
                )
                self.assertTrue(replayed)
                self.assertFalse(old_replay["credentialAccepted"])
                self.assertEqual("credential_inactive", old_replay["status"])
                repository.settings["maximumRetainedAgents"] = 2
                if store_type is FileStore:
                    snapshot = store._load()
                    before_counts = tuple(
                        len(snapshot.get(name, {}))
                        for name in (
                            "agentIdentities",
                            "agentTokens",
                            "commonsAgentProfiles",
                        )
                    ) + (len(snapshot.get("auditLog", [])),)
                else:
                    with store._open_connection() as connection:
                        before_counts = tuple(
                            int(
                                connection.execute(
                                    "SELECT COUNT(*) AS item_count FROM " + table
                                ).fetchone()["item_count"]
                            )
                            for table in (
                                "matm_agent_identities",
                                "matm_agent_tokens",
                                "matm_commons_agent_profiles",
                                "matm_audit_log",
                            )
                        )
                with self.assertRaisesRegex(
                    CommonsContractError,
                    "agent_name_unavailable",
                ):
                    repository.enroll(
                        "compact-old-agent",
                        "Compact Old Agent",
                        profile,
                        _candidate("compact-old-agent-new-secret"),
                        _key("compact-old-agent-new-key"),
                        request_digest({"agentName": "compact-old-agent"}),
                    )
                if store_type is FileStore:
                    snapshot = store._load()
                    after_counts = tuple(
                        len(snapshot.get(name, {}))
                        for name in (
                            "agentIdentities",
                            "agentTokens",
                            "commonsAgentProfiles",
                        )
                    ) + (len(snapshot.get("auditLog", [])),)
                else:
                    with store._open_connection() as connection:
                        after_counts = tuple(
                            int(
                                connection.execute(
                                    "SELECT COUNT(*) AS item_count FROM " + table
                                ).fetchone()["item_count"]
                            )
                            for table in (
                                "matm_agent_identities",
                                "matm_agent_tokens",
                                "matm_commons_agent_profiles",
                                "matm_audit_log",
                            )
                        )
                self.assertEqual(before_counts, after_counts)

                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(
                    master_auth,
                    True,
                    0,
                    _key("compact-policy"),
                    request_digest({"humanApprovalRequired": True}),
                )
                expired_candidate = _candidate("compact-expired-candidate")
                expired, _ = repository.enroll(
                    "compact-expired-request",
                    "Compact Expired Request",
                    profile,
                    expired_candidate,
                    _key("compact-expired-request"),
                    request_digest({"agentName": "compact-expired-request"}),
                )
                if store_type is FileStore:
                    data = store._load()
                    request = data["commonsEnrollmentRequests"][
                        expired["enrollmentRequestId"]
                    ]
                    request.update({"status": "denied", "decidedAt": old})
                    store._save(data)
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.execute(
                                "UPDATE matm_commons_enrollment_requests SET "
                                "status = 'denied', decided_at = ? WHERE "
                                "enrollment_request_id = ?",
                                (old, expired["enrollmentRequestId"]),
                            )
                fresh_candidate = _candidate("compact-fresh-candidate")
                fresh, replay = repository.enroll(
                    "compact-fresh-request",
                    "Compact Fresh Request",
                    profile,
                    fresh_candidate,
                    _key("compact-fresh-request"),
                    request_digest({"agentName": "compact-fresh-request"}),
                )
                self.assertFalse(replay)
                self.assertEqual("pending", fresh["status"])
                candidate_auth = repository.authenticate_enrollment_candidate(
                    expired_candidate
                )
                self.assertIsNotNone(candidate_auth)
                terminal = repository.current_enrollment(candidate_auth)
                self.assertEqual("denied", terminal["status"])
                self.assertTrue(terminal["profileCompacted"])
                self.assertIsNone(terminal["agentName"])
                exact_terminal, exact_replay = repository.enroll(
                    "compact-expired-request",
                    "Compact Expired Request",
                    profile,
                    expired_candidate,
                    _key("compact-expired-request"),
                    request_digest({"agentName": "compact-expired-request"}),
                )
                self.assertTrue(exact_replay)
                self.assertEqual("denied", exact_terminal["status"])
                alias_key = _key("compact-expired-alias")
                alias_terminal, alias_replay = repository.enroll(
                    "compact-expired-request",
                    "Compact Expired Request",
                    profile,
                    expired_candidate,
                    alias_key,
                    request_digest({"agentName": "compact-expired-request"}),
                )
                self.assertTrue(alias_replay)
                self.assertEqual("denied", alias_terminal["status"])
                with self.assertRaisesRegex(CommonsContractError, "idempotency_conflict"):
                    repository.enroll(
                        "different-request",
                        "Different Request",
                        profile,
                        _candidate("different-terminal-candidate"),
                        alias_key,
                        request_digest({"agentName": "different-request"}),
                    )
                if store_type is FileStore:
                    compact_audits = [
                        item
                        for item in store._load().get("auditLog", [])
                        if item.get("action")
                        in ("commons.retention.compact", "commons.enrollment.compact")
                    ]
                else:
                    with store._open_connection() as connection:
                        compact_audits = connection.execute(
                            "SELECT audit_id FROM matm_audit_log WHERE action IN (?, ?)",
                            ("commons.retention.compact", "commons.enrollment.compact"),
                        ).fetchall()
                self.assertGreaterEqual(len(compact_audits), 2)

    def test_inactive_approved_enrollment_compacts_without_candidate_resurrection(self):
        profile = {
            "listed": False,
            "implementation": "approval contract",
            "capabilities": ["commons"],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "available",
        }
        old = "2000-01-01T00:00:00.000000Z"
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(
                    master_auth,
                    True,
                    0,
                    _key("approved-compact-policy"),
                    request_digest({"humanApprovalRequired": True}),
                )
                repository.settings.update(
                    {
                        "maximumRetainedEnrollments": 1,
                        "maximumCompanyRetainedEnrollments": 100,
                        "maximumEnrollmentTombstones": 10,
                        "maximumCompanyEnrollmentTombstones": 100,
                        "terminalEnrollmentRetentionSeconds": 1,
                    }
                )
                approved_candidate = _candidate("approved-compact")
                pending, _ = repository.enroll(
                    "approved-compact",
                    "Approved Compact",
                    profile,
                    approved_candidate,
                    _key("approved-compact-enroll"),
                    request_digest({"agentName": "approved-compact"}),
                )
                approved, _ = repository.decide_enrollment(
                    master_auth,
                    pending["enrollmentRequestId"],
                    "approved",
                    pending["revision"],
                    _key("approved-compact-decision"),
                    request_digest(
                        {
                            "requestId": pending["enrollmentRequestId"],
                            "expectedRevision": pending["revision"],
                        }
                    ),
                )
                approved_auth = store.authenticate(approved_candidate, workspace_id)
                repository.revoke_credential(
                    approved_auth,
                    _key("approved-compact-revoke"),
                    request_digest({"revoke": True}),
                )
                token_id = approved_auth["agentTokenId"]
                if store_type is FileStore:
                    data = store._load()
                    data["agentTokens"][token_id]["revokedAt"] = old
                    data["commonsAgentProfiles"][
                        "%s:%s" % (repository.project_id, "approved-compact")
                    ]["updatedAt"] = old
                    data["commonsEnrollmentRequests"][
                        pending["enrollmentRequestId"]
                    ]["decidedAt"] = old
                    store._save(data)
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.execute(
                                "UPDATE matm_agent_tokens SET revoked_at = ? WHERE agent_token_id = ?",
                                (old, token_id),
                            )
                            connection.execute(
                                "UPDATE matm_commons_agent_profiles SET updated_at = ? WHERE "
                                "workspace_id = ? AND project_id = ? AND agent_id = ?",
                                (old, repository.workspace_id, repository.project_id, "approved-compact"),
                            )
                            connection.execute(
                                "UPDATE matm_commons_enrollment_requests SET decided_at = ? "
                                "WHERE enrollment_request_id = ?",
                                (old, pending["enrollmentRequestId"]),
                            )
                fresh, replay = repository.enroll(
                    "approved-compact-fresh",
                    "Approved Compact Fresh",
                    profile,
                    _candidate("approved-compact-fresh"),
                    _key("approved-compact-fresh"),
                    request_digest({"agentName": "approved-compact-fresh"}),
                )
                self.assertFalse(replay)
                self.assertEqual("pending", fresh["status"])
                candidate_auth = repository.authenticate_enrollment_candidate(
                    approved_candidate
                )
                self.assertIsNotNone(candidate_auth)
                historical = repository.current_enrollment(candidate_auth)
                self.assertEqual("approved", historical["status"])
                self.assertTrue(historical["profileCompacted"])
                self.assertFalse(historical["credentialAccepted"])
                self.assertIsNone(store.authenticate(approved_candidate, workspace_id))

    def test_compaction_filters_eligibility_before_its_batch_limit(self):
        old = "2000-01-01T00:00:00.000000Z"
        recent = utc_now()
        future = "2999-01-01T00:00:00.000000Z"
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, _workspace_id, project_id, company_id, _master = self._context(store_type, tempdir)
                repository.settings.update(
                    {
                        "terminalEnrollmentRetentionSeconds": 3600,
                        "inactiveAgentRetentionSeconds": 3600,
                    }
                )
                enrollment_rows = []
                for index in range(257):
                    suffix = hashlib.sha256(
                        ("batch-enrollment-%d" % index).encode("utf-8")
                    ).hexdigest()
                    enrollment_rows.append(
                        {
                            "enrollmentRequestId": "commonsenrollment-" + suffix[:24],
                            "workspaceId": repository.workspace_id,
                            "projectId": project_id,
                            "companyId": company_id,
                            "agentName": "batch-enrollment-%03d" % index,
                            "displayName": "Batch Enrollment %03d" % index,
                            "listed": False,
                            "implementation": "",
                            "capabilities": [],
                            "profileUrl": "",
                            "capabilityUrl": "",
                            "availability": "",
                            "candidateTokenId": "agenttoken-" + suffix[:20],
                            "candidateTokenHash": suffix,
                            "status": "denied",
                            "revision": 2,
                            "createdAt": (
                                "1999-01-01T00:00:%02d.000000Z" % (index % 60)
                                if index < 256
                                else "2001-01-01T00:00:00.000000Z"
                            ),
                            "expiresAt": old,
                            "decidedAt": old if index == 256 else recent,
                            "decidedByCredentialId": None,
                            "activatedAgentIdentityId": None,
                            "activatedProfileId": None,
                        }
                    )
                if store_type is FileStore:
                    data = store._load()
                    for item in enrollment_rows:
                        data["commonsEnrollmentRequests"][
                            item["enrollmentRequestId"]
                        ] = item
                    store._save(data)
                    repository._compact_terminal_enrollments_file(data, company_id)
                    after = store._load()
                    self.assertTrue(
                        after["commonsEnrollmentRequests"][
                            enrollment_rows[-1]["enrollmentRequestId"]
                        ]["profileCompacted"]
                    )
                    self.assertFalse(
                        after["commonsEnrollmentRequests"][
                            enrollment_rows[0]["enrollmentRequestId"]
                        ].get("profileCompacted", False)
                    )
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.executemany(
                                "INSERT INTO matm_commons_enrollment_requests ("
                                "enrollment_request_id, workspace_id, project_id, company_id, "
                                "agent_name, display_name, listed, implementation, "
                                "capabilities_json, profile_url, capability_url, availability, "
                                "candidate_token_id, candidate_token_hash, status, revision, "
                                "created_at, expires_at, decided_at, decided_by_credential_id, "
                                "activated_agent_identity_id, activated_profile_id) VALUES "
                                "(?,?,?,?,?,?,0,'','[]','','','',?,?,'denied',2,?,?,?,NULL,NULL,NULL)",
                                [
                                    (
                                        item["enrollmentRequestId"],
                                        item["workspaceId"],
                                        item["projectId"],
                                        item["companyId"],
                                        item["agentName"],
                                        item["displayName"],
                                        item["candidateTokenId"],
                                        item["candidateTokenHash"],
                                        item["createdAt"],
                                        item["expiresAt"],
                                        item["decidedAt"],
                                    )
                                    for item in enrollment_rows
                                ],
                            )
                            compacted = repository._compact_terminal_enrollments_sql(
                                connection, company_id
                            )
                    self.assertEqual(1, compacted)
                    with store._open_connection() as connection:
                        eligible = connection.execute(
                            "SELECT agent_name FROM matm_commons_enrollment_requests "
                            "WHERE enrollment_request_id = ?",
                            (enrollment_rows[-1]["enrollmentRequestId"],),
                        ).fetchone()
                        ineligible = connection.execute(
                            "SELECT agent_name FROM matm_commons_enrollment_requests "
                            "WHERE enrollment_request_id = ?",
                            (enrollment_rows[0]["enrollmentRequestId"],),
                        ).fetchone()
                    self.assertTrue(eligible["agent_name"].startswith("commons-tombstone-"))
                    self.assertEqual(enrollment_rows[0]["agentName"], ineligible["agent_name"])

                identity_rows = []
                grant_rows = []
                token_rows = []
                profile_rows = []
                for index in range(257):
                    suffix = hashlib.sha256(
                        ("batch-agent-%d" % index).encode("utf-8")
                    ).hexdigest()
                    agent_id = "batch-agent-%03d" % index
                    identity_id = "agentidentity-" + suffix[:24]
                    grant_id = "grant-" + suffix[:24]
                    token_id = "agenttoken-" + suffix[:20]
                    profile_id = "commonsprofile-" + suffix[:24]
                    eligible = index == 256
                    identity_rows.append((identity_id, agent_id))
                    grant_rows.append((grant_id, identity_id))
                    token_rows.append((token_id, grant_id, identity_id, suffix, old if eligible else None))
                    profile_rows.append((profile_id, identity_id, token_id, agent_id, "revoked" if eligible else "active", old if eligible else None))
                if store_type is FileStore:
                    data = store._load()
                    for identity_id, agent_id in identity_rows:
                        data["agentIdentities"][identity_id] = {
                            "agentIdentityId": identity_id,
                            "companyId": company_id,
                            "agentId": agent_id,
                            "agentNameNormalized": agent_id,
                            "status": "active",
                        }
                    for grant_id, identity_id in grant_rows:
                        data["agentAccessGrants"][grant_id] = {
                            "grantId": grant_id,
                            "companyId": company_id,
                            "agentIdentityId": identity_id,
                            "scopeType": "project",
                            "scopeId": project_id,
                            "workspaceId": repository.workspace_id,
                            "projectId": project_id,
                            "commonsOnly": True,
                            "status": "active",
                            "revokedAt": None,
                        }
                    for token_id, grant_id, identity_id, digest, revoked_at in token_rows:
                        data["agentTokens"][token_id] = {
                            "agentTokenId": token_id,
                            "grantId": grant_id,
                            "agentIdentityId": identity_id,
                            "tokenHash": digest,
                            "revokedAt": revoked_at,
                        }
                    for profile_id, identity_id, token_id, agent_id, status, updated_at in profile_rows:
                        data["commonsAgentProfiles"]["%s:%s" % (project_id, agent_id)] = {
                            "profileId": profile_id,
                            "workspaceId": repository.workspace_id,
                            "projectId": project_id,
                            "agentIdentityId": identity_id,
                            "agentTokenId": token_id,
                            "agentId": agent_id,
                            "displayName": agent_id,
                            "listed": False,
                            "implementation": "",
                            "capabilities": [],
                            "profileUrl": "",
                            "capabilityUrl": "",
                            "availability": "",
                            "credentialExpiresAt": future,
                            "status": status,
                            "createdAt": old,
                            "updatedAt": updated_at,
                        }
                    store._save(data)
                    repository._compact_inactive_agents_file(data, company_id)
                    after = store._load()
                    self.assertEqual(
                        "retired",
                        after["commonsAgentProfiles"][
                            "%s:%s" % (project_id, profile_rows[-1][3])
                        ]["status"],
                    )
                    self.assertEqual(
                        "active",
                        after["commonsAgentProfiles"][
                            "%s:%s" % (project_id, profile_rows[0][3])
                        ]["status"],
                    )
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.executemany(
                                "INSERT INTO matm_agent_identities (agent_identity_id, "
                                "company_id, agent_id, agent_name, agent_name_normalized, "
                                "display_name, status, created_at, updated_at) VALUES "
                                "(?,?,?,?,?,?,'active',?,NULL)",
                                [
                                    (identity_id, company_id, agent_id, agent_id, agent_id, agent_id, old)
                                    for identity_id, agent_id in identity_rows
                                ],
                            )
                            connection.executemany(
                                "INSERT INTO matm_agent_access_grants (grant_id, company_id, "
                                "agent_identity_id, scope_type, scope_id, workspace_id, project_id, "
                                "commons_only, status, created_at) VALUES "
                                "(?, ?, ?, 'project', ?, ?, ?, 1, 'active', ?)",
                                [
                                    (grant_id, company_id, identity_id, project_id, repository.workspace_id, project_id, old)
                                    for grant_id, identity_id in grant_rows
                                ],
                            )
                            connection.executemany(
                                "INSERT INTO matm_agent_tokens (agent_token_id, grant_id, "
                                "agent_identity_id, token_hash, created_at, revoked_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                [
                                    (token_id, grant_id, identity_id, digest, old, revoked_at)
                                    for token_id, grant_id, identity_id, digest, revoked_at in token_rows
                                ],
                            )
                            connection.executemany(
                                "INSERT INTO matm_commons_agent_profiles (profile_id, workspace_id, "
                                "project_id, agent_identity_id, agent_token_id, agent_id, display_name, "
                                "listed, implementation, capabilities_json, profile_url, capability_url, "
                                "availability, credential_expires_at, status, created_at, updated_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', '[]', '', '', '', ?, ?, ?, ?)",
                                [
                                    (profile_id, repository.workspace_id, project_id, identity_id, token_id, agent_id, agent_id, future, status, old, updated_at)
                                    for profile_id, identity_id, token_id, agent_id, status, updated_at in profile_rows
                                ],
                            )
                            compacted = repository._compact_inactive_agents_sql(
                                connection, company_id
                            )
                    self.assertEqual(1, compacted)
                    with store._open_connection() as connection:
                        eligible = connection.execute(
                            "SELECT status FROM matm_commons_agent_profiles WHERE profile_id = ?",
                            (profile_rows[-1][0],),
                        ).fetchone()
                        ineligible = connection.execute(
                            "SELECT status FROM matm_commons_agent_profiles WHERE profile_id = ?",
                            (profile_rows[0][0],),
                        ).fetchone()
                    self.assertEqual("retired", eligible["status"])
                    self.assertEqual("active", ineligible["status"])

    def test_enrollment_request_scope_isolation(self):
        profile = {
            "listed": False,
            "implementation": "",
            "capabilities": [],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "",
        }
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, company_id, master = self._context(store_type, tempdir)
                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(master_auth, True, 0, _key("isolation-policy"), request_digest({"humanApprovalRequired": True}))
                pending, _ = repository.enroll(
                    "isolated-agent",
                    "Isolated Agent",
                    profile,
                    _candidate("isolated"),
                    _key("isolation-enroll"),
                    request_digest({"agentName": "isolated-agent"}),
                )

                second_project, error = store.upsert_project(
                    workspace_id, "commons-second-project", "Commons Second", "test"
                )
                self.assertIsNone(error)
                second_settings = dict(repository.settings)
                second_settings["projectId"] = second_project["projectId"]
                same_company_repository = CommonsRepository(store, second_settings)
                for action in ("read", "approve", "deny"):
                    with self.subTest(scope="same_company_project", action=action):
                        with self.assertRaisesRegex(
                            CommonsContractError, "enrollment_request_not_found"
                        ):
                            if action == "read":
                                same_company_repository.enrollment_request(
                                    master_auth, pending["enrollmentRequestId"]
                                )
                            else:
                                same_company_repository.decide_enrollment(
                                    master_auth,
                                    pending["enrollmentRequestId"],
                                    "approved" if action == "approve" else "denied",
                                    pending["revision"],
                                    _key("isolation-%s" % action),
                                    request_digest({"expectedRevision": pending["revision"]}),
                                )

                other = store.create_free_account(
                    "Other Commons", "Other Commons", "Other Commons"
                )
                other_workspace, _other_master_id, other_master, _account, other_company, other_project = other[:6]
                self.assertNotEqual(company_id, other_company)
                other_settings = dict(repository.settings)
                other_settings.update(
                    {"workspaceId": other_workspace, "projectId": other_project}
                )
                other_repository = CommonsRepository(store, other_settings)
                other_auth = store.authenticate(other_master, other_workspace)
                with self.assertRaisesRegex(
                    CommonsContractError, "enrollment_request_not_found"
                ):
                    other_repository.enrollment_request(
                        other_auth, pending["enrollmentRequestId"]
                    )
                with self.assertRaisesRegex(
                    CommonsContractError, "enrollment_request_not_found"
                ):
                    other_repository.decide_enrollment(
                        other_auth,
                        pending["enrollmentRequestId"],
                        "approved",
                        pending["revision"],
                        _key("cross-company-approve"),
                        request_digest({"expectedRevision": pending["revision"]}),
                    )

    def test_sql_malformed_cross_company_enrollment_row_is_never_visible_or_mutable(self):
        profile = {
            "listed": False,
            "implementation": "",
            "capabilities": [],
            "profileUrl": "",
            "capabilityUrl": "",
            "availability": "",
        }
        with tempfile.TemporaryDirectory() as tempdir:
            (
                store,
                repository,
                workspace_id,
                _project_id,
                company_id,
                master,
            ) = self._context(SQLiteStore, tempdir)
            master_auth = store.authenticate(master, workspace_id)
            repository.set_policy(
                master_auth,
                True,
                0,
                _key("malformed-policy"),
                request_digest({"humanApprovalRequired": True}),
            )
            candidate = _candidate("malformed-company-candidate")
            pending, _ = repository.enroll(
                "malformed-company-agent",
                "Malformed Company Agent",
                profile,
                candidate,
                _key("malformed-enroll"),
                request_digest({"agentName": "malformed-company-agent"}),
            )
            other = store.create_free_account(
                "Malformed Other", "Malformed Other", "Malformed Other"
            )
            other_company_id = other[4]
            self.assertNotEqual(company_id, other_company_id)
            with closing(sqlite3.connect(str(store.path))) as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    "UPDATE matm_commons_enrollment_requests SET company_id = ? "
                    "WHERE enrollment_request_id = ?",
                    (other_company_id, pending["enrollmentRequestId"]),
                )
                audit_count = connection.execute(
                    "SELECT COUNT(*) FROM matm_audit_log"
                ).fetchone()[0]
                connection.commit()

            self.assertIsNone(
                repository.authenticate_enrollment_candidate(candidate)
            )
            with self.assertRaisesRegex(
                CommonsContractError, "enrollment_request_not_found"
            ):
                repository.enrollment_request(
                    master_auth, pending["enrollmentRequestId"]
                )
            self.assertEqual(0, repository.enrollment_requests(master_auth)["count"])
            for decision in ("approved", "denied"):
                with self.subTest(decision=decision):
                    with self.assertRaisesRegex(
                        CommonsContractError, "enrollment_request_not_found"
                    ):
                        repository.decide_enrollment(
                            master_auth,
                            pending["enrollmentRequestId"],
                            decision,
                            pending["revision"],
                            _key("malformed-" + decision),
                            request_digest(
                                {
                                    "expectedRevision": pending["revision"],
                                    "decision": decision,
                                }
                            ),
                        )

            with closing(sqlite3.connect(str(store.path))) as connection:
                row = connection.execute(
                    "SELECT company_id, status FROM matm_commons_enrollment_requests "
                    "WHERE enrollment_request_id = ?",
                    (pending["enrollmentRequestId"],),
                ).fetchone()
                self.assertEqual((other_company_id, "pending"), row)
                self.assertEqual(
                    audit_count,
                    connection.execute(
                        "SELECT COUNT(*) FROM matm_audit_log"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT COUNT(*) FROM matm_commons_agent_profiles "
                        "WHERE agent_id = 'malformed-company-agent'"
                    ).fetchone()[0],
                )

    def test_malformed_agent_token_grant_identity_company_and_scope_bindings_fail_closed(self):
        variants = (
            "token_identity_mismatch",
            "identity_company_mismatch",
            "company_workspace_mismatch",
            "project_scope_mismatch",
        )
        for store_type in self.STORE_TYPES:
            for variant in variants:
                with self.subTest(store=store_type.__name__, variant=variant), tempfile.TemporaryDirectory() as tempdir:
                    (
                        store,
                        repository,
                        workspace_id,
                        _project_id,
                        company_id,
                        _master,
                    ) = self._context(store_type, tempdir)
                    candidate = self._enroll(
                        repository,
                        "binding-primary",
                        "%s-%s-primary" % (store_type.__name__, variant),
                    )
                    stale_auth = repository.authenticate_agent_credential(candidate)
                    self.assertIsNotNone(stale_auth)
                    token_id, token_secret = storage_module._parse_governed_credential(
                        candidate, "agent"
                    )
                    other_identity_id = None
                    other_company_id = None
                    other_project_id = None
                    if variant == "token_identity_mismatch":
                        other_candidate = self._enroll(
                            repository,
                            "binding-secondary",
                            "%s-%s-secondary" % (store_type.__name__, variant),
                        )
                        other_identity_id = repository.authenticate_agent_credential(
                            other_candidate
                        )["agentIdentityId"]
                    elif variant in (
                        "identity_company_mismatch",
                        "company_workspace_mismatch",
                    ):
                        other = store.create_free_account(
                            "Binding Other",
                            "Binding Other",
                            "Binding Other",
                        )
                        other_company_id = other[4]
                        self.assertNotEqual(company_id, other_company_id)
                    else:
                        other_project, error = store.upsert_project(
                            workspace_id,
                            "binding-other-project",
                            "Binding Other Project",
                            "test",
                        )
                        self.assertIsNone(error)
                        other_project_id = other_project["projectId"]

                    if store_type is FileStore:
                        data = store._load()
                        token = data["agentTokens"][token_id]
                        grant = data["agentAccessGrants"][token["grantId"]]
                        identity = data["agentIdentities"][token["agentIdentityId"]]
                        if variant == "token_identity_mismatch":
                            token["agentIdentityId"] = other_identity_id
                        elif variant == "identity_company_mismatch":
                            identity["companyId"] = other_company_id
                        elif variant == "company_workspace_mismatch":
                            identity["companyId"] = other_company_id
                            grant["companyId"] = other_company_id
                            token["tokenHash"] = storage_module._governed_credential_digest(
                                "agent", other_company_id, token_id, token_secret
                            )
                        else:
                            grant["projectId"] = other_project_id
                            grant["scopeId"] = other_project_id
                        store._save(data)
                        audit_count = len(store._load().get("auditLog", []))
                    else:
                        with store._open_connection() as connection:
                            with connection:
                                if variant == "token_identity_mismatch":
                                    connection.execute(
                                        "UPDATE matm_agent_tokens SET agent_identity_id = ? "
                                        "WHERE agent_token_id = ?",
                                        (other_identity_id, token_id),
                                    )
                                elif variant == "identity_company_mismatch":
                                    connection.execute(
                                        "UPDATE matm_agent_identities SET company_id = ? "
                                        "WHERE agent_identity_id = ?",
                                        (other_company_id, stale_auth["agentIdentityId"]),
                                    )
                                elif variant == "company_workspace_mismatch":
                                    connection.execute(
                                        "UPDATE matm_agent_identities SET company_id = ? "
                                        "WHERE agent_identity_id = ?",
                                        (other_company_id, stale_auth["agentIdentityId"]),
                                    )
                                    connection.execute(
                                        "UPDATE matm_agent_access_grants SET company_id = ? "
                                        "WHERE grant_id = ?",
                                        (other_company_id, stale_auth["grantId"]),
                                    )
                                    connection.execute(
                                        "UPDATE matm_agent_tokens SET token_hash = ? "
                                        "WHERE agent_token_id = ?",
                                        (
                                            storage_module._governed_credential_digest(
                                                "agent",
                                                other_company_id,
                                                token_id,
                                                token_secret,
                                            ),
                                            token_id,
                                        ),
                                    )
                                else:
                                    connection.execute(
                                        "UPDATE matm_agent_access_grants SET project_id = ?, "
                                        "scope_id = ? WHERE grant_id = ?",
                                        (
                                            other_project_id,
                                            other_project_id,
                                            stale_auth["grantId"],
                                        ),
                                    )
                            audit_count = connection.execute(
                                "SELECT COUNT(*) FROM matm_audit_log"
                            ).fetchone()[0]

                    self.assertIsNone(
                        repository.authenticate_agent_credential(candidate)
                    )
                    self.assertIsNone(
                        repository.agent_profile("binding-primary")
                    )
                    self.assertNotIn(
                        "binding-primary",
                        [item["agentId"] for item in repository.agents()["items"]],
                    )
                    if variant == "company_workspace_mismatch":
                        repository.settings["maximumActiveAgents"] = 1
                        replacement = self._enroll(
                            repository,
                            "binding-replacement",
                            "%s-binding-replacement" % store_type.__name__,
                        )
                        self.assertIsNotNone(
                            repository.authenticate_agent_credential(replacement)
                        )
                        if store_type is FileStore:
                            audit_count = len(store._load().get("auditLog", []))
                        else:
                            with store._open_connection() as connection:
                                audit_count = connection.execute(
                                    "SELECT COUNT(*) FROM matm_audit_log"
                                ).fetchone()[0]
                    rejected_calls = (
                        lambda: repository.assert_active_agent(stale_auth),
                        lambda: repository.set_membership(
                            repository.room_id,
                            stale_auth,
                            "joined",
                            _key("malformed-binding-join"),
                            request_digest({"state": "joined"}),
                        ),
                        lambda: repository.publish(
                            repository.room_id,
                            stale_auth,
                            "Must not publish",
                            None,
                            _key("malformed-binding-publish"),
                            request_digest({"content": "Must not publish"}),
                        ),
                        lambda: repository.create_browser_session(
                            stale_auth,
                            _browser_candidate("malformed-binding-browser"),
                            _key("malformed-binding-browser"),
                            request_digest({"candidate": "malformed-binding-browser"}),
                        ),
                    )
                    for index, call in enumerate(rejected_calls):
                        with self.subTest(rejected_call=index):
                            with self.assertRaisesRegex(
                                CommonsContractError,
                                "commons_agent_credential_inactive",
                            ):
                                call()
                    if store_type is FileStore:
                        self.assertEqual(
                            audit_count, len(store._load().get("auditLog", []))
                        )
                    else:
                        with store._open_connection() as connection:
                            self.assertEqual(
                                audit_count,
                                connection.execute(
                                    "SELECT COUNT(*) FROM matm_audit_log"
                                ).fetchone()[0],
                            )

    def test_stale_agent_and_master_authorizations_fail_inside_mutations(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                token_a = self._enroll(repository, "stale-agent-a", "stale-a")
                token_b = self._enroll(repository, "stale-agent-b", "stale-b")
                stale_auth = store.authenticate(token_a, workspace_id)
                auth_b = store.authenticate(token_b, workspace_id)
                repository.set_membership(repository.room_id, stale_auth, "joined", _key("stale-join-a"), request_digest({"state": "joined"}))
                repository.set_membership(repository.room_id, auth_b, "joined", _key("stale-join-b"), request_digest({"state": "joined"}))
                owned_one, _ = repository.publish(repository.room_id, stale_auth, "Owned one", None, _key("stale-owned-one"), request_digest({"content": "Owned one"}))
                owned_two, _ = repository.publish(repository.room_id, stale_auth, "Owned two", None, _key("stale-owned-two"), request_digest({"content": "Owned two"}))
                other, _ = repository.publish(repository.room_id, auth_b, "Other", None, _key("stale-other"), request_digest({"content": "Other"}))
                successor = _candidate("stale-successor")
                repository.rotate_credential(
                    stale_auth,
                    successor,
                    _key("stale-rotate"),
                    request_digest({"candidateTokenSecret": successor}),
                )
                stale_calls = (
                    lambda: repository.set_membership(repository.room_id, stale_auth, "left", _key("stale-leave"), request_digest({"state": "left"})),
                    lambda: repository.publish(repository.room_id, stale_auth, "Late write", None, _key("stale-publish"), request_digest({"content": "Late write"})),
                    lambda: repository.correct(owned_one["messageId"], stale_auth, "Late correction", 1, _key("stale-correct"), request_digest({"content": "Late correction"})),
                    lambda: repository.withdraw(owned_two["messageId"], stale_auth, 1, _key("stale-withdraw"), request_digest({"expectedRevision": 1})),
                    lambda: repository.acknowledge(
                        other["messageId"],
                        stale_auth,
                        other["acknowledgementBinding"]["expectedRevision"],
                        other["acknowledgementBinding"]["expectedRevisionId"],
                        other["acknowledgementBinding"]["expectedState"],
                        other["acknowledgementBinding"]["expectedWithdrawalId"],
                        _key("stale-ack"),
                        request_digest(other["acknowledgementBinding"]),
                    ),
                    lambda: repository.create_browser_session(
                        stale_auth,
                        _browser_candidate("stale-browser"),
                        _key("stale-browser"),
                        request_digest({"candidate": "stale-browser"}),
                    ),
                )
                for index, call in enumerate(stale_calls):
                    with self.subTest(stale_agent_call=index):
                        with self.assertRaisesRegex(
                            CommonsContractError, "commons_agent_credential_inactive"
                        ):
                            call()

                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(master_auth, True, 0, _key("master-policy-on"), request_digest({"humanApprovalRequired": True}))
                pending, _ = repository.enroll(
                    "master-race-pending",
                    "Master Race Pending",
                    {"listed": False, "implementation": "", "capabilities": [], "profileUrl": "", "capabilityUrl": "", "availability": ""},
                    _candidate("master-race-pending"),
                    _key("master-race-enroll"),
                    request_digest({"agentName": "master-race-pending"}),
                )
                if store_type is FileStore:
                    data = store._load()
                    data["companyMasterKeys"][master_auth["masterKeyId"]]["revokedAt"] = utc_now()
                    store._save(data)
                else:
                    with store._open_connection() as connection:
                        with connection:
                            connection.execute(
                                "UPDATE matm_company_master_keys SET revoked_at = ? WHERE master_key_id = ?",
                                (utc_now(), master_auth["masterKeyId"]),
                            )
                with self.assertRaisesRegex(CommonsContractError, "company_master_required"):
                    repository.set_policy(master_auth, False, 1, _key("stale-master-policy"), request_digest({"humanApprovalRequired": False}))
                with self.assertRaisesRegex(CommonsContractError, "company_master_required"):
                    repository.decide_enrollment(
                        master_auth,
                        pending["enrollmentRequestId"],
                        "approved",
                        pending["revision"],
                        _key("stale-master-approve"),
                        request_digest({"expectedRevision": pending["revision"]}),
                    )

    def test_message_list_avoids_history_and_detail_is_wire_bounded(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, _master = self._context(store_type, tempdir)
                token = self._enroll(repository, "bounded-history-agent", "bounded-history")
                auth = store.authenticate(token, workspace_id)
                repository.set_membership(repository.room_id, auth, "joined", _key("bounded-join"), request_digest({"state": "joined"}))
                message, _ = repository.publish(repository.room_id, auth, "Initial", None, _key("bounded-post"), request_digest({"content": "Initial"}))
                for revision in range(2, 33):
                    content = ("\U0001f642" * 16000) + str(revision)
                    message, _ = repository.correct(
                        message["messageId"],
                        auth,
                        content,
                        revision - 1,
                        _key("bounded-correct-%d" % revision),
                        request_digest({"contentHash": hashlib.sha256(content.encode("utf-8")).hexdigest(), "expectedRevision": revision - 1}),
                    )
                method = "_history_sql" if store_type is SQLiteStore else "_history_file"
                with mock.patch.object(
                    repository,
                    method,
                    side_effect=AssertionError("list must not load history"),
                ):
                    page = repository.list_messages(repository.room_id, limit=100)
                self.assertEqual(1, page["count"])
                self.assertFalse(page["items"][0]["revisionHistoryIncluded"])
                detail = repository.message(message["messageId"])
                wire_bytes = len(
                    json.dumps(
                        {"ok": True, "message": detail}, indent=2, sort_keys=True
                    ).encode("utf-8")
                )
                self.assertLess(wire_bytes, 1048576)
                self.assertEqual(32, detail["revisionCount"])
                self.assertTrue(
                    all(not item["contentIncluded"] for item in detail["revisionHistory"])
                )
                revision = repository.message_revision(message["messageId"], 1)
                self.assertEqual("Initial", revision["content"])
                withdrawn, _ = repository.withdraw(
                    message["messageId"],
                    auth,
                    32,
                    _key("bounded-withdraw"),
                    request_digest({"expectedRevision": 32}),
                )
                self.assertEqual("withdrawn", withdrawn["state"])
                self.assertIsNone(
                    repository.message_revision(message["messageId"], 1)["content"]
                )

    def test_enrollment_replay_survives_policy_flip_and_fresh_enrollment_fails(self):
        for store_type in self.STORE_TYPES:
            with self.subTest(store=store_type.__name__), tempfile.TemporaryDirectory() as tempdir:
                store, repository, workspace_id, _project_id, _company_id, master = self._context(store_type, tempdir)
                token = self._enroll(repository, "agent-replay", "c")
                body = {
                    "agentName": "agent-replay",
                    "displayName": "Agent-Replay",
                    "candidateTokenSecret": token,
                }
                master_auth = store.authenticate(master, workspace_id)
                repository.set_policy(master_auth, True, 0, _key("policy-on"), request_digest({"humanApprovalRequired": True}))
                result, replay = repository.enroll(
                    "agent-replay",
                    "Agent-Replay",
                    {
                        "listed": True,
                        "implementation": "contract test",
                        "capabilities": ["commons"],
                        "profileUrl": "",
                        "capabilityUrl": "",
                        "availability": "available",
                    },
                    token,
                    _key("enroll-agent-replay"),
                    request_digest(body),
                )
                self.assertTrue(replay)
                self.assertEqual("agent-replay", result["agent"]["agentId"])
                self.assertIsNotNone(store.authenticate(token, workspace_id))
                pending_token = _candidate("d")
                pending, replay = repository.enroll(
                    "agent-fresh",
                    "Agent Fresh",
                    {"listed": False, "implementation": "", "capabilities": [], "profileUrl": "", "capabilityUrl": "", "availability": ""},
                    pending_token,
                    _key("enroll-fresh"),
                    request_digest({"agentName": "agent-fresh"}),
                )
                self.assertFalse(replay)
                self.assertEqual("pending", pending["status"])
                self.assertFalse(pending["credentialAccepted"])
                self.assertIsNone(store.authenticate(pending_token, workspace_id))
                candidate_auth = repository.authenticate_enrollment_candidate(
                    pending_token
                )
                self.assertEqual(
                    "pending", repository.current_enrollment(candidate_auth)["status"]
                )
                queue = repository.enrollment_requests(master_auth, limit=1)
                self.assertEqual(1, queue["count"])
                approved, replay = repository.decide_enrollment(
                    master_auth,
                    pending["enrollmentRequestId"],
                    "approved",
                    pending["revision"],
                    _key("approve-fresh"),
                    request_digest({"expectedRevision": pending["revision"]}),
                )
                self.assertFalse(replay)
                self.assertEqual("approved", approved["status"])
                self.assertTrue(approved["credentialAccepted"])
                self.assertIsNotNone(store.authenticate(pending_token, workspace_id))
                approved_replay, replay = repository.decide_enrollment(
                    master_auth,
                    pending["enrollmentRequestId"],
                    "approved",
                    pending["revision"],
                    _key("approve-fresh"),
                    request_digest({"expectedRevision": pending["revision"]}),
                )
                self.assertTrue(replay)
                self.assertEqual("approved", approved_replay["status"])

                denied_token = _candidate("f")
                denied_pending, _ = repository.enroll(
                    "agent-denied",
                    "Agent Denied",
                    {"listed": False, "implementation": "", "capabilities": [], "profileUrl": "", "capabilityUrl": "", "availability": ""},
                    denied_token,
                    _key("enroll-denied"),
                    request_digest({"agentName": "agent-denied"}),
                )
                denied, _ = repository.decide_enrollment(
                    master_auth,
                    denied_pending["enrollmentRequestId"],
                    "denied",
                    denied_pending["revision"],
                    _key("deny-agent"),
                    request_digest({"expectedRevision": denied_pending["revision"]}),
                )
                self.assertEqual("denied", denied["status"])
                self.assertIsNone(store.authenticate(denied_token, workspace_id))
                self.assertEqual(
                    "denied",
                    repository.current_enrollment(
                        repository.authenticate_enrollment_candidate(denied_token)
                    )["status"],
                )


if __name__ == "__main__":
    unittest.main()
