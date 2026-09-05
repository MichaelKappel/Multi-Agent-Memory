import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit


_CREDENTIAL_PEPPER_ENV = "MEMORYENDPOINTS_CREDENTIAL_PEPPER"
_MISSING = object()
_TEST_CREDENTIAL_PEPPER = "test-only-governed-agent-provisioner-v1-" + ("p" * 64)
_ISOLATED_RUNTIME_ENVIRONMENT = (
    "DATABASE_URL",
    "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
    "MEMORYENDPOINTS_AGENT_TOKEN",
    "MEMORYENDPOINTS_COMPANY_MASTER_TOKEN",
    "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
    "MEMORYENDPOINTS_CORS_ALLOWED_ORIGINS",
    "MEMORYENDPOINTS_DATA_DIR",
    "MEMORYENDPOINTS_INVITE_SECRET",
    "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH",
    "MEMORYENDPOINTS_MCP_OAUTH_PATH",
    "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
    "MEMORYENDPOINTS_MYSQL_DATABASE",
    "MEMORYENDPOINTS_MYSQL_HOST",
    "MEMORYENDPOINTS_MYSQL_PASSWORD",
    "MEMORYENDPOINTS_MYSQL_PORT",
    "MEMORYENDPOINTS_MYSQL_URL",
    "MEMORYENDPOINTS_MYSQL_USER",
    "MEMORYENDPOINTS_SQLITE_PATH",
    "MEMORYENDPOINTS_STORE_BACKEND",
    "MEMORYENDPOINTS_STORE_PATH",
    "MYSQL_DATABASE",
    "MYSQL_HOST",
    "MYSQL_PASSWORD",
    "MYSQL_PORT",
    "MYSQL_USER",
)


class IsolatedTestRuntimeEnvironment:
    """Install OS-temporary runtime paths and restore every inherited value exactly."""

    def __init__(self, prefix="memoryendpoints-test-"):
        self._prefix = prefix
        self._temporary = None
        self._saved = None

    @property
    def root(self):
        if self._temporary is None:
            raise AssertionError("The isolated test runtime is not installed.")
        return self._temporary.name

    def install(self):
        if self._temporary is not None:
            return self
        self._temporary = tempfile.TemporaryDirectory(prefix=self._prefix)
        self._saved = {
            name: os.environ.get(name, _MISSING)
            for name in _ISOLATED_RUNTIME_ENVIRONMENT
        }
        for name in _ISOLATED_RUNTIME_ENVIRONMENT:
            os.environ.pop(name, None)
        data_dir = os.path.join(self.root, "data")
        config_dir = os.path.join(self.root, "config")
        os.environ.update(
            {
                "MEMORYENDPOINTS_STORE_BACKEND": "sqlite",
                "MEMORYENDPOINTS_DATA_DIR": data_dir,
                "MEMORYENDPOINTS_SQLITE_PATH": os.path.join(data_dir, "store.sqlite3"),
                "MEMORYENDPOINTS_STORE_PATH": os.path.join(data_dir, "store.json"),
                "MEMORYENDPOINTS_MCP_OAUTH_PATH": os.path.join(data_dir, "oauth.sqlite3"),
                "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH": os.path.join(
                    config_dir, "missing-credential-config.json"
                ),
                "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH": os.path.join(
                    config_dir, "missing-mcp-host-config.json"
                ),
                "MEMORYENDPOINTS_MYSQL_CONFIG_PATH": os.path.join(
                    config_dir, "missing-mysql-config.json"
                ),
                "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH": os.path.join(
                    config_dir, "missing-admin-diagnostics.json"
                ),
            }
        )
        return self

    def restore(self):
        if self._temporary is None:
            return
        try:
            for name, value in self._saved.items():
                if value is _MISSING:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        finally:
            temporary = self._temporary
            self._temporary = None
            self._saved = None
            temporary.cleanup()


class IsolatedTestRuntimeMixin:
    """Keep all default stores outside the repository for a complete test class."""

    @classmethod
    def setUpClass(cls):
        fixture = IsolatedTestRuntimeEnvironment().install()
        cls._isolated_test_runtime_fixture = fixture
        try:
            super().setUpClass()
        except Exception:
            fixture.restore()
            raise

    @classmethod
    def tearDownClass(cls):
        fixture = cls.__dict__.get("_isolated_test_runtime_fixture")
        try:
            super().tearDownClass()
        finally:
            if fixture is not None:
                fixture.restore()


def governed_agent_redemption_material(invite_secret):
    """Return one deterministic client-retained candidate and exact retry key."""
    invite_secret = str(invite_secret or "")
    token_id = hashlib.sha256(
        ("governed-test-agent-token-id\0" + invite_secret).encode("utf-8")
    ).hexdigest()[:20]
    token_secret = base64.urlsafe_b64encode(
        hashlib.sha256(
            ("governed-test-agent-token-secret\0" + invite_secret).encode("utf-8")
        ).digest()
    ).decode("ascii").rstrip("=")
    candidate = "me_agent_v1.agenttoken-%s.%s" % (token_id, token_secret)
    idempotency_key = "governed-test-invite-redeem-" + hashlib.sha256(
        ("governed-test-invite-redeem-key\0" + invite_secret).encode("utf-8")
    ).hexdigest()
    return (
        {
            "schemaVersion": "memoryendpoints.agent_invite_redemption.v1",
            "inviteSecret": invite_secret,
            "candidateAgentTokenSecret": candidate,
        },
        idempotency_key,
        candidate,
    )


class DeterministicCredentialPepperEnvironment:
    """Install the test-only credential pepper and restore the prior environment."""

    def __init__(self):
        self._previous_pepper = _MISSING
        self._installed = False

    @property
    def installed(self):
        return self._installed

    def install(self):
        if not self._installed:
            self._previous_pepper = os.environ.get(_CREDENTIAL_PEPPER_ENV, _MISSING)
            os.environ[_CREDENTIAL_PEPPER_ENV] = _TEST_CREDENTIAL_PEPPER
            self._installed = True
        return self

    def restore(self):
        if not self._installed:
            return
        if self._previous_pepper is _MISSING:
            os.environ.pop(_CREDENTIAL_PEPPER_ENV, None)
        else:
            os.environ[_CREDENTIAL_PEPPER_ENV] = self._previous_pepper
        self._previous_pepper = _MISSING
        self._installed = False


class DeterministicCredentialPepperMixin:
    """Provide one deterministic credential-pepper environment per test class."""

    @classmethod
    def setUpClass(cls):
        fixture = DeterministicCredentialPepperEnvironment().install()
        cls._deterministic_credential_pepper_fixture = fixture
        try:
            super().setUpClass()
        except Exception:
            fixture.restore()
            raise

    @classmethod
    def tearDownClass(cls):
        fixture = cls.__dict__.get("_deterministic_credential_pepper_fixture")
        try:
            super().tearDownClass()
        finally:
            if fixture is not None:
                fixture.restore()


@dataclass(frozen=True)
class GovernedTestAgent:
    agent_id: str
    agent_bearer: str = field(repr=False)

    @property
    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": "Bearer " + self.agent_bearer}


class GovernedAgentProvisioner:
    """Exercise the production governed invitation flow for test principals."""

    def __init__(self, call_app):
        self._call_app = call_app
        self._pepper_environment = DeterministicCredentialPepperEnvironment()

    def install(self):
        self._pepper_environment.install()
        return self

    def restore(self):
        self._pepper_environment.restore()

    def provision(
        self,
        *,
        master_bearer,
        company_id,
        workspace_id,
        project_id,
        requested_name,
        display_name,
        grant_scope_type="workspace",
        grant_scope_id=None,
    ):
        if not self._pepper_environment.installed:
            raise AssertionError("The deterministic test credential pepper is not installed.")
        scope_ids = {
            "company": company_id,
            "workspace": workspace_id,
            "project": project_id,
        }
        scope_id = grant_scope_id or scope_ids.get(grant_scope_type)
        if not scope_id:
            raise AssertionError("The requested governed test grant has no scope id.")
        master_headers = {"HTTP_AUTHORIZATION": "Bearer " + master_bearer}
        request_headers = dict(
            master_headers,
            HTTP_IDEMPOTENCY_KEY="governed-test-name-request-" + requested_name,
        )

        requested = self._json_call(
            "/api/matm/access/agent-name-requests",
            "POST",
            {
                "requestedName": requested_name,
                "displayName": display_name,
                "requestedGrant": {
                    "scopeType": grant_scope_type,
                    "scopeId": scope_id,
                },
                "assignmentContext": {
                    "projectId": project_id,
                    "taskId": "governed-test-fixture",
                    "taskLabel": "Governed test fixture",
                },
                "justification": "Provision a governed principal for an isolated contract test.",
            },
            request_headers,
            "201 Created",
            "agent name request",
        )
        request_id = ((requested.get("request") or {}).get("requestId") or "").strip()
        if not request_id:
            raise AssertionError("The governed agent name request returned no request id.")

        approved = self._json_call(
            "/api/matm/access/agent-name-requests/%s/decision" % request_id,
            "POST",
            {
                "decision": "approve",
                "decisionReason": "Approved for the isolated governed-principal contract test.",
            },
            dict(
                master_headers,
                HTTP_IDEMPOTENCY_KEY="governed-test-name-decision-" + request_id,
            ),
            "200 OK",
            "agent name approval",
        )
        if ((approved.get("request") or {}).get("status") or "") != "approved":
            raise AssertionError("The governed agent name request was not approved.")

        issued = self._json_call(
            "/api/matm/access/invites",
            "POST",
            {"approvedRequestId": request_id, "expiresInSeconds": 900},
            master_headers,
            "201 Created",
            "agent invitation issuance",
        )
        if "inviteSecret" in issued:
            raise AssertionError("The governed invitation exposed a secret outside the URL fragment.")
        invite_url = issued.get("inviteUrl") or ""
        parsed_invite_url = urlsplit(invite_url)
        if parsed_invite_url.query or not parsed_invite_url.fragment:
            raise AssertionError("The governed invitation was not fragment-only.")
        fragment = parse_qs(parsed_invite_url.fragment, strict_parsing=True)
        if set(fragment) != {"invite"} or len(fragment["invite"]) != 1:
            raise AssertionError("The governed invitation fragment was malformed.")
        invite_secret = fragment["invite"][0]

        redemption, redemption_key, agent_bearer = (
            governed_agent_redemption_material(invite_secret)
        )

        redeemed = self._json_call(
            "/api/matm/access/invites/redeem",
            "POST",
            redemption,
            {
                "CONTENT_TYPE": "application/json",
                "HTTP_IDEMPOTENCY_KEY": redemption_key,
            },
            "201 Created",
            "agent invitation redemption",
        )
        principal = redeemed.get("principal") or {}
        agent_id = str(principal.get("agentId") or "").strip()
        if "agentTokenSecret" in redeemed:
            raise AssertionError("The governed redemption returned a credential secret.")
        if not redeemed.get("candidateCredentialAccepted"):
            raise AssertionError("The governed redemption did not accept the client candidate.")
        if not agent_id or not agent_bearer:
            raise AssertionError("The governed invitation redemption returned no canonical agent principal.")
        return GovernedTestAgent(agent_id=agent_id, agent_bearer=agent_bearer)

    def _json_call(self, path, method, body, headers, expected_status, operation):
        status, _response_headers, text = self._call_app(
            path,
            method=method,
            body=body,
            headers=headers,
        )
        if status != expected_status:
            raise AssertionError(
                "%s expected %s but received %s" % (operation, expected_status, status)
            )
        try:
            payload = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise AssertionError("%s returned invalid JSON" % operation) from exc
        if not payload.get("ok"):
            raise AssertionError("%s did not succeed" % operation)
        return payload
