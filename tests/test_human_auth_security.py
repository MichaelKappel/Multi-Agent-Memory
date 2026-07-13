import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from memoryendpoints import human_auth


class HumanAuthSecurityTests(unittest.TestCase):
    def test_username_is_canonical_ascii_and_human_readable(self):
        self.assertEqual(human_auth.canonicalize_username("  Alice.Smith-7  "), "alice.smith-7")
        self.assertEqual(human_auth.canonicalize_username("ops_team"), "ops_team")
        self.assertEqual(human_auth.username_policy()["allowedPattern"], r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")

        invalid = (None, "ab", "-alice", "alice..smith", "alice!", "аlice", "a" * 65)
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(human_auth.HumanAuthPolicyError):
                    human_auth.canonicalize_username(value)

    def test_password_policy_is_length_based_without_composition_tricks(self):
        strong_without_composition = "all lowercase words make a long passphrase"
        self.assertEqual(human_auth.password_policy_errors(strong_without_composition), ())
        self.assertTrue(human_auth.validate_password(strong_without_composition))
        self.assertIn("password_too_short", human_auth.password_policy_errors("too short"))
        self.assertIn("password_common", human_auth.password_policy_errors("correcthorsebatterystaple"))
        self.assertIn("password_invalid_character", human_auth.password_policy_errors("valid length but\x00bad"))
        self.assertIn("password_matches_username", human_auth.password_policy_errors("long-human-name", "long-human-name"))
        self.assertIn("password_too_long", human_auth.password_policy_errors("é" * 600))

    def test_scrypt_verifiers_use_fresh_salts_and_verify_in_constant_time(self):
        password = "unique long account passphrase"
        first = human_auth.encode_password_verifier(password)
        second = human_auth.encode_password_verifier(password)
        self.assertNotEqual(first, second)
        self.assertNotIn(password, first)
        parsed = human_auth.parse_password_verifier(first)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.n, human_auth.PASSWORD_SCRYPT_N)
        self.assertEqual(parsed.dklen, human_auth.PASSWORD_DERIVED_KEY_BYTES)

        with mock.patch.object(human_auth.hmac, "compare_digest", wraps=human_auth.hmac.compare_digest) as compared:
            self.assertTrue(human_auth.verify_password(password, first))
            self.assertFalse(human_auth.verify_password("different long passphrase", first))
        self.assertGreaterEqual(compared.call_count, 2)

    def test_malformed_or_resource_amplifying_verifiers_fail_closed(self):
        valid = human_auth.encode_password_verifier("a valid and unique passphrase")
        bad_values = (
            None,
            "",
            valid.replace("me_scrypt_v1", "me_scrypt_v2", 1),
            valid.replace("n=16384", "n=1048576", 1),
            valid.replace("n=16384$r=8", "r=8$n=16384", 1),
            valid + "$extra",
            valid.rsplit("$", 1)[0] + "$not+base64",
            valid.replace("r=8", "r=08", 1),
            "x" * 513,
        )
        for value in bad_values:
            with self.subTest(value=str(value)[:30]):
                self.assertIsNone(human_auth.parse_password_verifier(value))
                self.assertFalse(human_auth.verify_password("a valid and unique passphrase", value))

    def test_unknown_and_malformed_accounts_still_spend_dummy_kdf_work(self):
        with mock.patch.object(human_auth, "_derive_scrypt", wraps=human_auth._derive_scrypt) as derive:
            self.assertFalse(human_auth.verify_password_or_dummy("long unknown password", None))
            self.assertFalse(human_auth.verify_password_or_dummy("long unknown password", "malformed"))
        self.assertEqual(derive.call_count, 2)

    def test_credential_pepper_can_be_injected_or_loaded_from_protected_json(self):
        injected = b"p" * human_auth.MIN_CREDENTIAL_PEPPER_BYTES
        self.assertEqual(human_auth.resolve_credential_pepper(injected), injected)
        with self.assertRaises(human_auth.HumanAuthConfigurationError):
            human_auth.resolve_credential_pepper(b"short")
        with self.assertRaises(human_auth.HumanAuthConfigurationError):
            human_auth.resolve_credential_pepper(b"x" * 4097)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential.json"
            path.write_text(json.dumps({"credentialPepper": "z" * 40}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"MEMORYENDPOINTS_CREDENTIAL_PEPPER": ""}, clear=False):
                self.assertEqual(human_auth.resolve_credential_pepper(config_path=path), b"z" * 40)

    def test_bound_session_and_csrf_secrets_are_unique_and_context_bound(self):
        pepper = b"q" * 32
        first = human_auth.issue_bound_secret("human-session", "session-1", pepper=pepper)
        second = human_auth.issue_bound_secret("human-session", "session-1", pepper=pepper)
        self.assertNotEqual(first.secret, second.secret)
        self.assertNotIn(first.secret, first.verifier)
        self.assertNotIn(first.secret, repr(first))
        self.assertNotIn(first.verifier, repr(first))
        self.assertTrue(
            human_auth.verify_bound_secret(
                first.secret,
                first.verifier,
                "human-session",
                "session-1",
                pepper=pepper,
            )
        )
        self.assertFalse(
            human_auth.verify_bound_secret(
                first.secret,
                first.verifier,
                "csrf",
                "session-1",
                pepper=pepper,
            )
        )
        self.assertFalse(
            human_auth.verify_bound_secret(
                first.secret,
                "malformed",
                "human-session",
                "session-1",
                pepper=pepper,
            )
        )

    def test_recent_password_reauthentication_is_bounded_and_timezone_aware(self):
        now = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(
            human_auth.reauthentication_is_recent(
                "2026-01-01T11:56:00Z", now=now, max_age_seconds=300
            )
        )
        self.assertFalse(
            human_auth.reauthentication_is_recent(
                "2026-01-01T11:54:00Z", now=now, max_age_seconds=300
            )
        )
        self.assertFalse(human_auth.reauthentication_is_recent("2026-01-01T11:59:00", now=now))
        self.assertFalse(
            human_auth.reauthentication_is_recent(
                "2026-01-01T12:02:00Z", now=now, clock_skew_seconds=60
            )
        )
        self.assertFalse(
            human_auth.reauthentication_is_recent(
                "2026-01-01T12:00:00Z", now=now, max_age_seconds=3600
            )
        )

    def test_origin_and_fetch_metadata_policy_is_strict_for_human_routes(self):
        expected = "https://MemoryEndpoints.com:443/"
        self.assertEqual(human_auth.canonical_origin(expected), "https://memoryendpoints.com")
        self.assertTrue(
            human_auth.human_browser_request_allowed(
                "POST",
                "https://memoryendpoints.com",
                expected,
                "same-origin",
                "cors",
                "empty",
            )
        )
        denied = (
            ("POST", "https://evil.example", "same-origin", "cors", "empty"),
            ("POST", "https://memoryendpoints.com", "cross-site", "cors", "empty"),
            ("POST", "https://memoryendpoints.com", "same-origin", "navigate", "document"),
            ("POST", "", "same-origin", "cors", "empty"),
        )
        for method, origin, site, mode, destination in denied:
            with self.subTest(origin=origin, site=site, mode=mode):
                self.assertFalse(
                    human_auth.human_browser_request_allowed(
                        method, origin, expected, site, mode, destination
                    )
                )
        self.assertTrue(
            human_auth.human_browser_request_allowed(
                "GET", "", expected, "same-origin", "cors", "empty"
            )
        )


if __name__ == "__main__":
    unittest.main()
