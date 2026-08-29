import unittest
import hashlib

from memoryendpoints.outbound_mcp import (
    SERVER_SCHEMA,
    OutboundMcpValidationError,
    agent_policy_update_allowed,
    authorization_decision,
    config_digest,
    normalize_endpoint,
    normalize_project_policy,
    validate_server_config,
)


def server(**overrides):
    value = {
        "schemaVersion": SERVER_SCHEMA,
        "label": "Local tools",
        "endpoint": "https://tools.example.test/mcp",
        "transport": "streamable_http",
        "authMode": "none",
        "requestedMode": "inherit",
        "toolAllowlist": ["memory.search", "build.run"],
    }
    value.update(overrides)
    return value


BINDING = {
    "server_id": "omcp-0123456789abcdef0123456789abcdef",
    "server_revision": 3,
    "project_id": "project-registry",
    "tool_name": "build.run",
    "arguments_digest": hashlib.sha256(b'{"target":"test"}').hexdigest(),
}


def decide(configured=None, policy=None, approval=None, **binding_overrides):
    configured = configured or server()
    binding = dict(BINDING)
    binding.update(
        {
            "expected_server_revision": binding["server_revision"],
            "expected_config_digest": config_digest(configured),
            "expected_policy_revision": normalize_project_policy(policy)["revision"],
        }
    )
    binding.update(binding_overrides)
    return authorization_decision(configured, policy, approval, **binding)


def exact_approval(decision, **overrides):
    approval = {
        "status": "approved",
        "serverId": decision["serverId"],
        "serverRevision": decision["serverRevision"],
        "configDigest": decision["configDigest"],
        "policyRevision": decision["projectPolicyRevision"],
    }
    approval.update(overrides)
    return approval


class OutboundMcpPolicyTests(unittest.TestCase):
    def test_missing_project_policy_is_autonomous(self):
        self.assertEqual("autonomous", normalize_project_policy()["mode"])
        decision = decide()
        self.assertEqual("allowed", decision["state"])
        self.assertEqual("autonomous_default", decision["reason"])
        self.assertFalse(decision["networkRequestPerformed"])

    def test_human_policy_and_agent_request_require_exact_config_approval(self):
        for policy, configured in (
            ({"mode": "human_required", "forcedByHuman": True, "revision": 4}, server()),
            (None, server(requestedMode="human_required")),
        ):
            with self.subTest(policy=policy):
                pending = decide(configured, policy)
                self.assertEqual("approval_required", pending["state"])
                approved = decide(configured, policy, exact_approval(pending))
                self.assertEqual("allowed", approved["state"])

    def test_config_edit_invalidates_prior_approval(self):
        original = server()
        pending = decide(
            original,
            {"mode": "human_required", "forcedByHuman": True, "revision": 2},
        )
        approval = exact_approval(pending)
        changed = server(endpoint="https://other.example.test/mcp")
        decision = decide(
            changed,
            {"mode": "human_required", "forcedByHuman": True, "revision": 2},
            approval,
        )
        self.assertEqual("approval_required", decision["state"])

    def test_blocked_policy_wins_over_approval(self):
        configured = server()
        decision = decide(
            configured,
            {"mode": "blocked", "forcedByHuman": True, "revision": 9},
            {
                "status": "approved",
                "serverId": BINDING["server_id"],
                "serverRevision": BINDING["server_revision"],
                "configDigest": config_digest(configured),
                "policyRevision": 9,
            },
        )
        self.assertEqual("blocked", decision["state"])

    def test_agent_cannot_relax_human_forced_policy(self):
        forced = {"mode": "human_required", "forcedByHuman": True, "revision": 3}
        self.assertFalse(agent_policy_update_allowed(forced, "autonomous"))
        self.assertTrue(agent_policy_update_allowed(forced, "human_required"))
        self.assertFalse(agent_policy_update_allowed(forced, "blocked"))

    def test_server_schema_keeps_credentials_out_of_configuration(self):
        valid = validate_server_config(
            server(authMode="credential_slot", credentialSlotId="vault:tools-prod")
        )
        self.assertEqual("vault:tools-prod", valid["credentialSlotId"])
        with self.assertRaisesRegex(OutboundMcpValidationError, "unknown_field"):
            validate_server_config(dict(server(), bearerToken="not-allowed"))
        with self.assertRaisesRegex(OutboundMcpValidationError, "slot_forbidden"):
            validate_server_config(dict(server(), credentialSlotId="vault:unused"))

    def test_tool_allowlist_is_required_normalized_exact_and_digest_bound(self):
        configured = validate_server_config(
            server(toolAllowlist=["memory.search", "build.run", "memory.search"])
        )
        self.assertEqual(["build.run", "memory.search"], configured["toolAllowlist"])
        self.assertEqual(
            config_digest(server(toolAllowlist=["build.run", "memory.search"])),
            config_digest(server(toolAllowlist=["memory.search", "build.run"])),
        )
        self.assertNotEqual(
            config_digest(server()),
            config_digest(server(toolAllowlist=["build.run"])),
        )
        missing = server()
        missing.pop("toolAllowlist")
        with self.assertRaisesRegex(OutboundMcpValidationError, "tool_allowlist_invalid"):
            validate_server_config(missing)
        with self.assertRaisesRegex(OutboundMcpValidationError, "tool_allowlist_invalid"):
            validate_server_config(server(toolAllowlist=[]))

    def test_authorization_is_bound_to_exact_invocation_context(self):
        decision = decide()
        self.assertEqual("allowed", decision["state"])
        self.assertEqual(BINDING["server_id"], decision["serverId"])
        self.assertEqual(BINDING["server_revision"], decision["serverRevision"])
        self.assertEqual(BINDING["project_id"], decision["projectId"])
        self.assertEqual(BINDING["tool_name"], decision["toolName"])
        self.assertEqual(BINDING["arguments_digest"], decision["argumentsDigest"])
        self.assertEqual(0, decision["projectPolicyRevision"])
        self.assertFalse(decision["networkRequestPerformed"])

        for override in (
            {"tool_name": "Build.Run"},
            {"tool_name": "admin.delete"},
            {"arguments_digest": BINDING["arguments_digest"].upper()},
            {"arguments_digest": "a" * 63},
            {"server_id": ""},
            {"server_revision": 0},
            {"project_id": ""},
        ):
            with self.subTest(override=override):
                blocked = decide(**override)
                self.assertEqual("blocked", blocked["state"])
        self.assertEqual(
            "tool_not_allowlisted", decide(tool_name="admin.delete")["reason"]
        )

    def test_expected_server_config_and_project_policy_must_match_current(self):
        policy = {"mode": "autonomous", "forcedByHuman": False, "revision": 5}
        mismatches = (
            ({"expected_server_revision": BINDING["server_revision"] + 1}, "server_revision_mismatch"),
            ({"expected_config_digest": "0" * 64}, "config_digest_mismatch"),
            ({"expected_policy_revision": 4}, "project_policy_revision_mismatch"),
        )
        for overrides, reason in mismatches:
            with self.subTest(reason=reason):
                decision = decide(policy=policy, **overrides)
                self.assertEqual("blocked", decision["state"])
                self.assertEqual(reason, decision["reason"])

    def test_approval_requires_every_exact_server_and_policy_binding(self):
        policy = {"mode": "human_required", "forcedByHuman": True, "revision": 7}
        pending = decide(policy=policy)
        self.assertEqual("approval_required", pending["state"])
        approval = exact_approval(pending)
        self.assertEqual("allowed", decide(policy=policy, approval=approval)["state"])
        mismatches = {
            "serverId": "omcp-ffffffffffffffffffffffffffffffff",
            "serverRevision": pending["serverRevision"] + 1,
            "configDigest": "0" * 64,
            "policyRevision": pending["projectPolicyRevision"] + 1,
            "status": "denied",
        }
        for field, value in mismatches.items():
            with self.subTest(field=field):
                rejected = decide(
                    policy=policy,
                    approval=exact_approval(pending, **{field: value}),
                )
                self.assertEqual("approval_required", rejected["state"])

    def test_endpoint_requires_https_without_url_credentials_query_or_fragment(self):
        self.assertEqual(
            "https://tools.example.test/mcp",
            normalize_endpoint("HTTPS://TOOLS.EXAMPLE.TEST/mcp"),
        )
        for endpoint, code in (
            ("http://tools.example.test/mcp", "https_required"),
            ("https://user:pass@tools.example.test/mcp", "endpoint_invalid"),
            ("https://tools.example.test/mcp?token=value", "query_forbidden"),
            ("https://tools.example.test/mcp#secret", "query_forbidden"),
            ("https://bad host.example.test/mcp", "endpoint_invalid"),
            ("https://%65xample.test/mcp", "endpoint_invalid"),
            ("https://-bad.example.test/mcp", "endpoint_invalid"),
            ("https://bad-.example.test/mcp", "endpoint_invalid"),
            ("https://010.1.1.1/mcp", "endpoint_invalid"),
            ("https://tools.example.test:0/mcp", "endpoint_invalid"),
            ("https://[fe80::1%25eth0]/mcp", "endpoint_invalid"),
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(OutboundMcpValidationError, code):
                    normalize_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
