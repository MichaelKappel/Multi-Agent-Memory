"""Focused current-contract coverage for Commons validation and projections."""

import base64
import datetime
import os
import unittest
from unittest.mock import patch

from memoryendpoints import commons
from memoryendpoints import commons_storage
from memoryendpoints import storage


def _expect_code(testcase, code, callback):
    with testcase.assertRaises(commons.CommonsContractError) as raised:
        callback()
    testcase.assertEqual(code, raised.exception.code)


class CommonsPrimitivesCurrentTests(unittest.TestCase):
    def test_storage_credential_candidates_and_retention_helpers_are_closed(self):
        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_CREDENTIAL_PEPPER": "p" * 32},
            clear=False,
        ):
            agent_token, _digest = storage._governed_credential(
                "agent", "company-1", "agenttoken-" + ("a" * 20)
            )
            session_token, _digest = storage._governed_credential(
                "commonsbrowser", "company-1", "commonsbrowser-" + ("b" * 20)
            )
            agent_id, agent_digest = commons_storage._candidate_agent_credential(
                agent_token, "company-1"
            )
            session_id, session_digest = commons_storage._candidate_browser_session(
                session_token, "company-1"
            )
            self.assertEqual("agenttoken-" + ("a" * 20), agent_id)
            self.assertRegex(agent_digest, r"^v1:[a-f0-9]{64}$")
            self.assertEqual("commonsbrowser-" + ("b" * 20), session_id)
            self.assertRegex(session_digest, r"^v1:[a-f0-9]{64}$")
        for function, value, code in (
            (commons_storage._candidate_agent_credential, "bad", "agent_credential_candidate_invalid"),
            (commons_storage._candidate_browser_session, "bad", "browser_session_candidate_invalid"),
        ):
            with self.subTest(function=function.__name__):
                with self.assertRaises(commons.CommonsContractError) as raised:
                    function(value, "company-1")
                self.assertEqual(code, raised.exception.code)
        self.assertTrue(commons_storage._retention_elapsed("2020-01-01T00:00:00Z", 60))
        self.assertFalse(commons_storage._retention_elapsed("not-a-date", 60))
        self.assertFalse(commons_storage._retention_elapsed("2026-01-01T00:00:00", 60))
        self.assertTrue(commons_storage._retention_cutoff(60).endswith("Z"))
        self.assertEqual("agent-1", commons_storage._credential_reference({"agentTokenId": "agent-1", "masterKeyId": "master-1"}))
        self.assertEqual("", commons_storage._credential_reference({}))
        self.assertTrue(commons_storage._enrollment_profile_compacted({"agentName": "commons-tombstone-abc"}))
        self.assertFalse(commons_storage._enrollment_profile_compacted({"agentName": "agent-1"}))
        self.assertEqual(
            '{"a":1}', commons_storage._json({"a": 1})
        )

    def test_storage_default_commons_policy_and_room_projection_are_tenant_bound(self):
        repository = commons_storage.CommonsRepository(
            None,
            {
                "workspaceId": "workspace-1",
                "projectId": "project-1",
                "humanApprovalRequiredByDefault": True,
            },
        )
        policy = repository._default_policy()
        self.assertEqual("workspace-1", policy["workspaceId"])
        self.assertEqual("project-1", policy["projectId"])
        self.assertTrue(policy["humanApprovalRequired"])
        self.assertFalse(policy["defaultAutonomousEnrollment"])
        room = repository._canonical_room("2026-01-01T00:00:00Z")
        self.assertEqual(repository.room_id, room["roomId"])
        self.assertEqual("workspace-1", room["workspaceId"])
        self.assertEqual("project-1", room["projectId"])

    def test_digest_and_normalization_contracts_are_deterministic(self):
        self.assertEqual(commons.request_digest({"a": 1, "b": 2}), commons.request_digest({"b": 2, "a": 1}))
        self.assertNotEqual(commons.digest_text("a"), commons.digest_text("b"))
        self.assertEqual(commons.digest_text(""), commons.digest_text(None))
        key = "k" * commons.COMMONS_IDEMPOTENCY_MIN_LENGTH
        self.assertEqual(key, commons.validate_idempotency_key(key))
        for value in (None, "", "x" * 31, "x" * 201, " " + key, key + " ", key + "\n"):
            with self.subTest(value=value):
                _expect_code(self, "idempotency_key_invalid", lambda value=value: commons.validate_idempotency_key(value))
        self.assertEqual("agent-7", commons.normalize_agent_name("agent-7"))
        for value in (None, "Agent-7", " agent-7", "ab", "a--b", "a_b"):
            with self.subTest(value=value):
                _expect_code(self, "agent_name_invalid", lambda value=value: commons.normalize_agent_name(value))

    def test_display_and_profile_validation_covers_optional_fields_and_secret_firewall(self):
        self.assertEqual("Fallback Name", commons.normalize_display_name(None, "Fallback Name"))
        self.assertEqual("spaced name", commons.normalize_display_name("  spaced   name ", "unused"))
        for value in (1, "", "x" * 81, "bad\x00name", "password: synthetic-secret"):
            with self.subTest(value=value):
                _expect_code(self, "display_name_invalid" if value != "password: synthetic-secret" else "public_content_rejected", lambda value=value: commons.normalize_display_name(value, "fallback"))

        self.assertEqual("", commons.normalize_public_profile({})["profileUrl"])
        profile = commons.normalize_public_profile(
            {
                "listed": True,
                "implementation": "  local   runtime ",
                "capabilities": ["Memory", "memory", "Tools"],
                "profileUrl": "https://example.test/profile",
                "capabilityUrl": "https://example.test/capabilities",
                "availability": "LIMITED",
            }
        )
        self.assertEqual(["Memory", "Tools"], profile["capabilities"])
        self.assertEqual("limited", profile["availability"])
        for value, code in (
            (None, "public_profile_invalid"),
            ({"unknown": True}, "public_profile_invalid"),
            ({"listed": 1}, "public_profile_invalid"),
            ({"implementation": 1}, "public_profile_invalid"),
            ({"capabilities": [1]}, "public_profile_invalid"),
            ({"capabilities": ["\x00"]}, "public_profile_invalid"),
            ({"availability": "later"}, "public_profile_invalid"),
            ({"profileUrl": "http://example.test"}, "public_profile_invalid"),
            ({"profileUrl": "https://user:pass@example.test"}, "public_profile_invalid"),
            ({"profileUrl": "https://example.test/#private"}, "public_profile_invalid"),
        ):
            with self.subTest(value=value):
                _expect_code(self, code, lambda value=value: commons.normalize_public_profile(value))
        _expect_code(self, "public_content_rejected", lambda: commons.validate_public_safe_payload({"nested": ["-----BEGIN PRIVATE KEY-----"]}))

    def test_message_and_page_validation_exposes_current_error_contracts(self):
        self.assertEqual("line1\nline2", commons.validate_message_content("line1\r\nline2", 100))
        _expect_code(self, "message_content_invalid", lambda: commons.validate_message_content(1, 100))
        _expect_code(self, "message_content_invalid", lambda: commons.validate_message_content(" text", 100))
        _expect_code(self, "message_content_invalid", lambda: commons.validate_message_content("bad\x00text", 100))
        with self.assertRaises(commons.CommonsContractError) as raised:
            commons.validate_message_content("x" * 5, 4)
        self.assertEqual("message_too_large", raised.exception.code)
        self.assertEqual("413 Payload Too Large", raised.exception.status)
        self.assertEqual(commons.COMMONS_PAGE_LIMIT_DEFAULT, commons.bounded_page_limit(None))
        self.assertEqual(7, commons.bounded_page_limit("7"))
        for value in ("x", 0, 101):
            with self.subTest(value=value):
                _expect_code(self, "page_limit_invalid", lambda value=value: commons.bounded_page_limit(value))

    def test_expiry_and_all_signed_cursor_families_fail_closed(self):
        self.assertTrue(commons.timestamp_expired(None))
        self.assertTrue(commons.timestamp_expired("not-a-date"))
        self.assertTrue(commons.timestamp_expired("2020-01-01T00:00:00Z"))
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)).isoformat()
        self.assertFalse(commons.timestamp_expired(future))
        self.assertTrue(commons.credential_expiry(30).endswith("Z"))

        key = b"commons-test-signing-key"
        context = "workspace-1"
        cursor = commons.encode_cursor("2026-01-01T00:00:00Z", "message-1", key, context)
        self.assertEqual({"createdAt": "2026-01-01T00:00:00Z", "messageId": "message-1"}, commons.decode_cursor(cursor, key, context))
        agent_cursor = commons.encode_agent_cursor("agent-7", key, context)
        self.assertEqual("agent-7", commons.decode_agent_cursor(agent_cursor, key, context))
        enrollment_cursor = commons.encode_enrollment_cursor("2026-01-01T00:00:00Z", "commonsenrollment-" + "a" * 24, key, context)
        self.assertEqual(("2026-01-01T00:00:00Z", "commonsenrollment-" + "a" * 24), commons.decode_enrollment_cursor(enrollment_cursor, key, context))
        for decoder, token in ((commons.decode_cursor, cursor), (commons.decode_agent_cursor, agent_cursor), (commons.decode_enrollment_cursor, enrollment_cursor)):
            with self.subTest(decoder=decoder.__name__):
                self.assertIsNone(decoder(None, key, context))
                _expect_code(self, "cursor_invalid", lambda decoder=decoder: decoder("invalid", key, context))
                _expect_code(self, "cursor_invalid", lambda decoder=decoder, token=token: decoder(token, key, "other-context"))
        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        _expect_code(self, "cursor_invalid", lambda: commons.decode_cursor(tampered, key, context))

    def test_public_projections_preserve_redaction_and_lifecycle_states(self):
        profile = {"agentId": "agent-7", "displayName": "Agent", "createdAt": "created", "updatedAt": "updated"}
        self.assertEqual("active", commons.public_agent(profile)["participationState"])
        self.assertEqual("inactive", commons.public_agent(profile, active=False)["participationState"])
        room = {"roomId": "room-1", "name": "Commons", "description": "Public", "visibility": "public", "membershipRequired": 1, "status": "active", "createdAt": "created"}
        self.assertEqual(3, commons.public_room(room, 3, "recent", {"status": "member"})["participantCount"])
        self.assertNotIn("viewerMembership", commons.public_room(room))
        message = {"messageId": "message-1", "roomId": "room-1", "authorAgentId": "agent-7", "currentRevision": 1, "currentRevisionId": "revision-1", "createdAt": "created", "state": "active"}
        revision = {"revisionId": "revision-1", "revisionNumber": 1, "authorAgentId": "agent-7", "createdAt": "created", "content": "hello"}
        current = commons.public_message(message, revision, revision_history=[revision])
        self.assertEqual("current", current["state"])
        self.assertEqual("hello", current["content"])
        self.assertEqual("corrected", commons.public_message(dict(message, currentRevision=2), revision)["state"])
        withdrawn = commons.public_message(dict(message, state="withdrawn"), revision, {"withdrawalId": "withdrawal-1"}, revision_history=[revision])
        self.assertIsNone(withdrawn["content"])
        self.assertTrue(withdrawn["tombstone"]["withdrawn"])
        without_history = commons.public_message(message, revision, include_history=False)
        self.assertNotIn("revisionHistory", without_history)
        projected_revision = commons.public_message_revision(message, revision)
        self.assertEqual("hello", projected_revision["content"])
        withdrawn_revision = commons.public_message_revision(dict(message, state="withdrawn"), revision, {"withdrawalId": "withdrawal-1"})
        self.assertIsNone(withdrawn_revision["content"])
        self.assertEqual("withdrawn", withdrawn_revision["messageState"])
        for projection in (current, withdrawn, projected_revision, withdrawn_revision):
            self.assertTrue(projection["valuesRedacted"])
            self.assertFalse(projection["rawCredentialExposed"])
            self.assertFalse(projection["rawPayloadExposed"])


if __name__ == "__main__":
    unittest.main()
