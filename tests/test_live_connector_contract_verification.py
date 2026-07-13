import json
import tempfile
import unittest
from pathlib import Path

from memoryendpoints import site_data
from scripts import verify_live_connector_contract as verifier


def http_result(payload, status=200, content_type="application/json", byte_count=1024):
    return {
        "status": status,
        "headers": {"Content-Type": content_type},
        "contentType": content_type,
        "byteCount": byte_count,
        "oversized": False,
        "payload": payload,
        "jsonParsed": True,
        "redirectObserved": False,
        "transportError": "",
    }


def discovery_document():
    return {
        "schemaVersion": verifier.SCHEMA,
        "supportedSchemaVersions": [verifier.SCHEMA],
        "issuer": verifier.ISSUER,
        "serviceRoot": {"exact": verifier.ISSUER},
        "endpoints": dict(verifier.EXPECTED_ENDPOINTS),
        "requestedScopes": list(verifier.REQUESTED_SCOPES),
        "scopeDigest": verifier.SCOPE_DIGEST,
        "transport": {
            "noRedirectsForApiEndpoints": True,
            "sameOriginEndpoints": True,
        },
    }


def receipt(action, status):
    return {
        "receiptId": "connector-0123456789abcdef01234567",
        "action": action,
        "status": status,
        "idempotentReplay": False,
        "rawCredentialExposed": False,
        "privatePayloadExposed": False,
        "scopeDigest": verifier.SCOPE_DIGEST,
    }


def production_json_size(payload):
    return len(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


class LiveConnectorPairingVerifierTests(unittest.TestCase):
    def test_current_public_contract_openapi_and_discovery_are_coherent(self):
        discovery = discovery_document()
        contract = {"ok": True, "data": site_data.connector_contract()}
        openapi = site_data.openapi_spec()
        discovery_size = production_json_size(discovery)
        contract_size = production_json_size(contract)
        openapi_size = production_json_size(openapi)

        self.assertGreater(openapi_size, verifier.MAX_CONNECTOR_JSON_BYTES)
        self.assertLessEqual(discovery_size, verifier.MAX_DISCOVERY_BYTES)
        self.assertLessEqual(contract_size, verifier.MAX_CONTRACT_BYTES)
        self.assertLessEqual(openapi_size, verifier.MAX_OPENAPI_BYTES)
        check = verifier.public_contract_check(
            http_result(discovery, byte_count=discovery_size),
            http_result(contract, byte_count=contract_size),
            http_result(openapi, byte_count=openapi_size),
        )

        self.assertTrue(check["ok"], check)
        self.assertTrue(check["credentialListSchemaVerified"])
        self.assertTrue(check["errorSchemaVerified"])
        self.assertTrue(check["mutationSchemasVerified"])
        self.assertTrue(check["receiptSchemasVerified"])
        self.assertTrue(all(check["mutationSchemaChecks"].values()))

    def test_public_contract_rejects_openapi_over_its_endpoint_specific_bound(self):
        openapi_result = http_result(
            site_data.openapi_spec(),
            byte_count=verifier.MAX_OPENAPI_BYTES + 1,
        )
        openapi_result["oversized"] = True

        check = verifier.public_contract_check(
            http_result(discovery_document()),
            http_result({"ok": True, "data": site_data.connector_contract()}),
            openapi_result,
        )

        self.assertFalse(check["ok"])
        self.assertFalse(check["responseBoundsVerified"])

    def test_public_endpoint_response_bounds_are_explicit_and_finite(self):
        self.assertEqual(
            {
                verifier.DISCOVERY_PATH: 16 * 1024,
                verifier.CONTRACT_PATH: 128 * 1024,
                verifier.OPENAPI_PATH: 1024 * 1024,
            },
            verifier.PUBLIC_RESPONSE_BYTE_LIMITS,
        )
        self.assertEqual(64 * 1024, verifier.MAX_CONNECTOR_JSON_BYTES)
        self.assertTrue(all(isinstance(limit, int) and 0 < limit <= 1024 * 1024 for limit in verifier.PUBLIC_RESPONSE_BYTE_LIMITS.values()))

    def test_public_contract_rejects_redirect_and_missing_credential_list(self):
        discovery = discovery_document()
        discovery["endpoints"].pop("credentialList")
        discovery_result = http_result(discovery, status=302)
        discovery_result["redirectObserved"] = True

        check = verifier.public_contract_check(
            discovery_result,
            http_result({"ok": True, "data": site_data.connector_contract()}),
            http_result(site_data.openapi_spec()),
        )

        self.assertFalse(check["ok"])
        self.assertFalse(check["transportVerified"])
        self.assertFalse(check["discoveryVerified"])

    def test_openapi_mutation_bodies_are_exact_and_versioned(self):
        spec = site_data.openapi_spec()
        for path, expected_name in verifier.MUTATION_PATH_SCHEMAS.items():
            actual_name, schema = verifier._schema_from_operation(spec, path)
            self.assertEqual(expected_name, actual_name, path)
            self.assertFalse(schema["additionalProperties"], path)
            self.assertIn("schemaVersion", schema["required"], path)
            self.assertEqual(verifier.SCHEMA, schema["properties"]["schemaVersion"]["const"], path)

        reason = spec["components"]["schemas"]["ConnectorLifecycleReasonInput"]["properties"]["reason"]
        self.assertEqual(1, reason["minLength"])
        self.assertEqual(255, reason["maxLength"])

    def test_authenticated_lifecycle_evidence_is_exact_and_redacted(self):
        expected = {
            "pairingId": "pairing-private-id",
            "workspaceId": "workspace-private-id",
            "agentId": "localendpoint-agent",
            "credentialId": "connector-private-id",
            "connectorCredentialSecret": "connector-secret-never-report",
        }
        pairing = {
            "ok": True,
            "schemaVersion": verifier.SCHEMA,
            "pairing": {
                "pairingId": expected["pairingId"],
                "credentialId": expected["credentialId"],
                "status": "active",
                "approvedScopes": list(verifier.REQUESTED_SCOPES),
                "scopeDigest": verifier.SCOPE_DIGEST,
                "workspace": {"workspaceId": expected["workspaceId"], "readable": True},
                "agent": {"agentId": expected["agentId"], "readable": True},
                "grant": {"credentialType": "connector_agent", "approvedScopes": list(verifier.REQUESTED_SCOPES), "scopeDigest": verifier.SCOPE_DIGEST},
            },
            "approvedScopes": list(verifier.REQUESTED_SCOPES),
            "scopeDigest": verifier.SCOPE_DIGEST,
            "verification": {
                "canonicalWorkspaceReadable": True,
                "canonicalWorkspaceIdMatches": True,
                "exactAgentReadable": True,
                "exactAgentIdMatches": True,
                "credentialScopedToConnectorAndAgent": True,
                "grantActive": True,
                "grantRevoked": False,
                "rawCredentialExposed": False,
                "privatePayloadExposed": False,
            },
            "receipt": receipt("verify", "verified"),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        credentials = {
            "ok": True,
            "schemaVersion": verifier.SCHEMA,
            "pairingId": expected["pairingId"],
            "approvedScopes": list(verifier.REQUESTED_SCOPES),
            "scopeDigest": verifier.SCOPE_DIGEST,
            "currentCredentialId": expected["credentialId"],
            "items": [{
                "credentialId": expected["credentialId"],
                "status": "active",
                "isCurrent": True,
                "approvedScopes": list(verifier.REQUESTED_SCOPES),
                "scopeDigest": verifier.SCOPE_DIGEST,
                "createdAt": "2026-01-01T00:00:00Z",
                "activatedAt": "2026-01-01T00:01:00Z",
                "revokedAt": None,
                "lastUsedAt": "2026-01-01T00:02:00Z",
            }],
            "count": 1,
            "totalCount": 1,
            "hasMore": False,
            "limit": 100,
            "receipt": receipt("list_credentials", "verified"),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        me = {
            "ok": True,
            "principal": {
                "credentialType": "connector_agent",
                "credentialId": expected["credentialId"],
                "agentId": expected["agentId"],
                "approvedScopes": list(verifier.REQUESTED_SCOPES),
                "scopeDigest": verifier.SCOPE_DIGEST,
                "resourceContext": {"workspaceId": expected["workspaceId"]},
                "grant": {"scopeType": "agent", "scopeId": expected["agentId"], "approvedScopes": list(verifier.REQUESTED_SCOPES), "scopeDigest": verifier.SCOPE_DIGEST},
            },
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        workspace = {
            "ok": True,
            "workspace": {"workspaceId": expected["workspaceId"]},
            "approvedScopes": list(verifier.REQUESTED_SCOPES),
            "scopeDigest": verifier.SCOPE_DIGEST,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

        check = verifier.authenticated_lifecycle_check(
            http_result(pairing),
            http_result(credentials),
            http_result(me),
            http_result(workspace),
            expected,
        )

        self.assertTrue(check["ok"], check)
        self.assertNotIn(expected["pairingId"], str(check))
        self.assertNotIn(expected["credentialId"], str(check))
        self.assertEqual(["active"], check["observedCredentialStatuses"])

    def test_authenticated_lifecycle_rejects_extra_or_secret_item_fields(self):
        expected = {
            "pairingId": "pairing-private-id",
            "workspaceId": "workspace-private-id",
            "agentId": "localendpoint-agent",
            "credentialId": "connector-private-id",
        }
        item = {field: None for field in verifier.CREDENTIAL_ITEM_FIELDS}
        item.update({"credentialId": expected["credentialId"], "status": "active", "isCurrent": True, "createdAt": "2026-01-01T00:00:00Z", "secretVerifier": "forbidden"})
        credentials = {
            "ok": True,
            "schemaVersion": verifier.SCHEMA,
            "pairingId": expected["pairingId"],
            "currentCredentialId": expected["credentialId"],
            "items": [item],
            "count": 1,
            "totalCount": 1,
            "hasMore": False,
            "limit": 100,
            "receipt": receipt("list_credentials", "verified"),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        empty = http_result({})

        check = verifier.authenticated_lifecycle_check(empty, http_result(credentials), empty, empty, expected)

        self.assertFalse(check["ok"])
        self.assertFalse(check["credentialItemShapesVerified"])

    def test_report_never_contains_raw_token_or_identifiers(self):
        secrets = {
            "connectorCredentialSecret": "connector-secret-never-report",
            "pairingId": "pairing-private-id",
            "workspaceId": "workspace-private-id",
            "agentId": "localendpoint-agent",
            "credentialId": "connector-private-id",
        }
        authenticated = {
            "attempted": True,
            "ok": True,
            "pairingIdHash": verifier.sha256_text(secrets["pairingId"]),
            "workspaceIdHash": verifier.sha256_text(secrets["workspaceId"]),
            "agentIdHash": verifier.sha256_text(secrets["agentId"]),
            "credentialIdHash": verifier.sha256_text(secrets["credentialId"]),
        }

        report = verifier.build_report(verifier.ISSUER, {"ok": True}, authenticated, True, secrets)
        serialized = str(report)

        self.assertTrue(report["ok"])
        self.assertFalse(report["rawCredentialValuesStored"])
        self.assertFalse(report["rawTenantIdentifiersStored"])
        for raw in secrets.values():
            self.assertNotIn(raw, serialized)

    def test_report_path_rejects_tracked_documentation(self):
        for path in (
            verifier.ROOT / "docs" / "reports" / "connector.json",
            verifier.ROOT / "scripts" / "connector-report.json",
        ):
            with self.assertRaises(ValueError, msg=str(path)):
                verifier._safe_report_path(path)
        self.assertEqual(
            (verifier.ROOT / "var" / "reports" / "live-connector-pairing-verification.json").resolve(),
            verifier._safe_report_path(verifier.DEFAULT_REPORT),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = verifier.write_report(Path(directory) / "connector.json", {"ok": True})
            self.assertTrue(path.exists())

    def test_service_root_is_exact(self):
        self.assertEqual(verifier.ISSUER, verifier._validate_service_root(verifier.ISSUER))
        for invalid in (
            "http://memoryendpoints.com",
            "https://memoryendpoints.com:443",
            "https://user@memoryendpoints.com",
            "https://memoryendpoints.com/path",
            "https://memoryendpoints.com?query=1",
            "https://memoryendpoints.com#fragment",
        ):
            with self.assertRaises(ValueError, msg=invalid):
                verifier._validate_service_root(invalid)


if __name__ == "__main__":
    unittest.main()
