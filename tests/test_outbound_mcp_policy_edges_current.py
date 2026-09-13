"""Current deterministic edge coverage for outbound MCP policy primitives."""

from __future__ import annotations

import unittest

from memoryendpoints.outbound_mcp import (
    SERVER_SCHEMA,
    OutboundMcpValidationError,
    agent_policy_update_allowed,
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
        "toolAllowlist": ["memory.search"],
    }
    value.update(overrides)
    return value


class OutboundMcpPolicyEdgeTests(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(OutboundMcpValidationError) as raised:
            callback()
        self.assertEqual("outbound_mcp_" + code, str(raised.exception))

    def test_endpoint_normalization_covers_ip_idna_and_parser_boundaries(self):
        self.assertEqual(
            "https://192.0.2.10:8443/",
            normalize_endpoint("https://192.0.2.10:8443"),
        )
        self.assertEqual(
            "https://[2001:db8::10]/mcp",
            normalize_endpoint("https://[2001:0DB8:0:0:0:0:0:10]/mcp"),
        )
        self.assertEqual(
            "https://xn--mnich-kva.example/mcp",
            normalize_endpoint("https://münich.example/mcp"),
        )
        for endpoint, code in (
            ("", "endpoint_invalid"),
            ("https://tools.example.test\\mcp", "endpoint_invalid"),
            ("https://tools.example.test/\x7f", "endpoint_invalid"),
            ("https://[broken.example/mcp", "endpoint_invalid"),
            ("https://\ud800.example/mcp", "endpoint_invalid"),
            ("https://tools.example.test.", "endpoint_invalid"),
            ("https://" + ("a" * 2049) + ".example/mcp", "endpoint_invalid"),
        ):
            with self.subTest(endpoint=repr(endpoint)):
                self.assert_code(code, lambda endpoint=endpoint: normalize_endpoint(endpoint))

    def test_server_configuration_rejects_every_untrusted_shape(self):
        cases = (
            (None, "server_invalid"),
            (dict(server(), extra=True), "server_unknown_field"),
            (server(schemaVersion="wrong"), "server_schema_invalid"),
            (server(label=""), "label_invalid"),
            (server(label="x" * 121), "label_invalid"),
            (server(transport="sse"), "transport_invalid"),
            (server(authMode="bearer"), "auth_mode_invalid"),
            (server(authMode="credential_slot"), "credential_slot_invalid"),
            (server(authMode="credential_slot", credentialSlotId="bad slot"), "credential_slot_invalid"),
            (server(credentialSlotId="vault:unused"), "credential_slot_forbidden"),
            (server(requestedMode="autonomous"), "requested_mode_invalid"),
            (server(toolAllowlist=None), "tool_allowlist_invalid"),
            (server(toolAllowlist=[1]), "tool_allowlist_invalid"),
            (server(toolAllowlist=["bad name"]), "tool_allowlist_invalid"),
            (server(toolAllowlist=[]), "tool_allowlist_invalid"),
            (server(toolAllowlist=["tool.%d" % index for index in range(257)]), "tool_allowlist_invalid"),
        )
        for payload, code in cases:
            with self.subTest(code=code, payload=payload):
                self.assert_code(code, lambda payload=payload: validate_server_config(payload))

        normalized = validate_server_config(
            server(label="  Local   tools  ", credentialSlotId=None, toolAllowlist=[" b ", "a", "a"])
        )
        self.assertEqual("Local tools", normalized["label"])
        self.assertEqual(["a", "b"], normalized["toolAllowlist"])
        self.assertIsNone(normalized["credentialSlotId"])

    def test_project_policy_and_agent_relaxation_rules_fail_closed(self):
        for payload, code in (
            ([], "policy_invalid"),
            ({"mode": "unknown"}, "policy_mode_invalid"),
            ({"mode": "autonomous", "revision": True}, "policy_revision_invalid"),
            ({"mode": "autonomous", "revision": -1}, "policy_revision_invalid"),
        ):
            with self.subTest(payload=payload):
                self.assert_code(code, lambda payload=payload: normalize_project_policy(payload))

        self.assertEqual(
            {
                "schemaVersion": "multiagentmemory.outbound_mcp_project_policy.v1",
                "mode": "blocked",
                "forcedByHuman": True,
                "revision": 3,
            },
            normalize_project_policy({"mode": "blocked", "forcedByHuman": 1, "revision": 3}),
        )
        self.assert_code(
            "policy_mode_invalid",
            lambda: agent_policy_update_allowed(None, "unknown"),
        )
        for current, requested, expected in (
            (None, "autonomous", True),
            ({"mode": "autonomous"}, "human_required", True),
            ({"mode": "human_required"}, "autonomous", False),
            ({"mode": "human_required"}, "blocked", True),
            ({"mode": "blocked"}, "human_required", False),
            ({"mode": "autonomous", "forcedByHuman": True}, "blocked", False),
        ):
            with self.subTest(current=current, requested=requested):
                self.assertEqual(expected, agent_policy_update_allowed(current, requested))


if __name__ == "__main__":
    unittest.main()
