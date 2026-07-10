import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import parse_qs

from . import __version__
from .build import build_provenance
from .config import COMPANION_DOCS_URL, GITHUB_REPO_URL, PUBLIC_STORAGE_BYTES, ROOT, SITE_NAME, SITE_URL, utc_now
from .http import json_response, problem, response
from .runtime import backend_error_code, store_backend_health
from .security import redact_text
from .site_data import PUBLIC_ROUTES, capability_matrix, manifest, readiness_result, route_inventory
from .storage import FileStore, MySQLStore, SQLiteStore, mysql_config_diagnostics, mysql_connection_stage_diagnostics


STATIC_ROOT = ROOT / "static"


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _query(environ):
    return {k: v[0] if v else "" for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}


def _token(environ):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return environ.get("HTTP_X_MEMORYENDPOINTS_KEY", "").strip()


def _idempotency_key(environ):
    return environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()


def _admin_diagnostics_path():
    return Path(
        os.environ.get(
            "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
            str(ROOT / ".local-secrets" / "admin-diagnostics.json"),
        )
    )


def _admin_diagnostics_authorized(environ):
    path = _admin_diagnostics_path()
    if not path.exists():
        return False, "not_configured"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False, "invalid_config"
    expected_hash = str(payload.get("tokenHash") or "").strip().lower()
    if not expected_hash:
        return False, "missing_token_hash"
    token_hash = hashlib.sha256(_token(environ).encode("utf-8")).hexdigest()
    return hmac.compare_digest(token_hash, expected_hash), "configured"


def _diagnostic_fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _store():
    backend = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file"
    if backend in ("mysql", "mariadb"):
        return MySQLStore()
    if backend == "sqlite":
        return SQLiteStore()
    return FileStore()


def _require_auth(environ, workspace_id):
    auth = _store().authenticate(_token(environ), workspace_id)
    return auth


def html_page(title, main):
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "url": SITE_URL,
            "description": "Pure MATM Multi-Agent Transactive Memory endpoint reference implementation.",
            "version": __version__,
        },
        sort_keys=True,
    ).replace("<", "\\u003c")
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | MemoryEndpoints.com</title>
  <meta name="description" content="Pure MATM Multi-Agent Transactive Memory endpoint reference implementation.">
  <link rel="stylesheet" href="/static/css/site.css">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="MemoryEndpoints home">
      <img src="/static/img/memory-endpoints-mark.svg" alt="" width="36" height="36">
      <span>MemoryEndpoints.com</span>
    </a>
    <nav aria-label="Primary">
      <a href="/docs">Docs</a>
      <a href="/agent-setup">Agent Setup</a>
      <a href="/console">Console</a>
      <a href="/memory-lifecycle">Memory</a>
      <a href="/transparency">Transparency</a>
      <a href="{companion_docs_url}">MultiAgentMemory.com</a>
    </nav>
  </header>
  <main>{main}</main>
  <footer>
    <p>Source-available MATM endpoint reference. No certification, endorsement, or hidden authority claim is implied.</p>
  </footer>
  <script src="/static/js/site.js"></script>
</body>
</html>""".format(title=escape_html(title), main=main, json_ld=json_ld, companion_docs_url=COMPANION_DOCS_URL)


def escape_html(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def route_home(start_response):
    body = """
<section class="hero">
  <div>
    <p class="eyebrow">Pure MATM endpoint reference</p>
    <h1>MemoryEndpoints.com</h1>
    <p class="lead">A practical MATM operator console for bounded workspace memory, current messages, redacted receipts, and AI-ready discovery without third-party runtime dependencies.</p>
    <div class="actions">
      <a class="button primary" href="/agent-setup">Create agent workspace</a>
      <a class="button" href="/console">Open human console</a>
      <a class="button" href="/api/matm/live-capability-matrix">Capability matrix</a>
      <a class="button" href="{companion_docs_url}">Read companion docs</a>
    </div>
  </div>
  <figure class="system-map" aria-label="MATM memory flow diagram">
    <div>Agent</div><div>Inbox</div><div>Memory</div><div>Receipts</div>
    <figcaption>Current messages remain separate from durable memory promotion.</figcaption>
  </figure>
</section>
<section class="grid">
  <article><h2>For humans</h2><p>Readable pages explain what is live, planned, gated, and unsupported.</p></article>
  <article><h2>For agents</h2><p>Deterministic JSON and text routes define setup, memory, inbox, and acknowledgement flows.</p></article>
  <article><h2>For operators</h2><p>Secrets stay outside the repo; deployment and database use require explicit proof.</p></article>
  <article><h2>For implementers</h2><p><a href="{companion_docs_url}">MultiAgentMemory.com</a> explains the repository, GitHub handoff, and MATM memory boundary.</p></article>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL)
    return response(start_response, "200 OK", html_page("Home", body), "text/html; charset=utf-8")


def route_docs(start_response):
    body = """
<section class="page">
  <h1>Documentation</h1>
  <p>MemoryEndpoints follows an AI-ready web model: human-first pages, deterministic discovery files, safe APIs, bounded capability claims, privacy-preserving receipts, and validation evidence.</p>
  <h2>Companion documentation</h2>
  <p><a href="{companion_docs_url}">MultiAgentMemory.com</a> is the public GitHub companion documentation site. It explains how the repository, `.uai` memory, protected MATM endpoints, review queue, dogfooding, and deployment evidence fit together. The source repository is <a href="{github_repo_url}">MichaelKappel/Multi-Agent-Memory</a>.</p>
  <h2>Discovery routes</h2>
  <ul>
    <li><code>/llms.txt</code> and <code>/llms-full.txt</code> summarize public agent guidance.</li>
    <li><code>/ai-manifest.json</code> exposes route inventory and support boundaries.</li>
    <li><code>/api/matm/readiness-result</code> exposes current local readiness and deployment blockers.</li>
    <li><code>/.well-known/mcp.json</code> and <code>/mcp/resources</code> expose resource discovery.</li>
  </ul>
</section>
""".format(companion_docs_url=COMPANION_DOCS_URL, github_repo_url=GITHUB_REPO_URL)
    return response(start_response, "200 OK", html_page("Docs", body), "text/html; charset=utf-8")


def route_agent_setup(start_response):
    body = """
<section class="page">
  <h1>Agent Setup</h1>
  <p>Agents create a free workspace with <code>POST /api/matm/agent-setup/free-account</code>. The returned key is shown once and must be saved by the human or host. MemoryEndpoints stores only a hash.</p>
  <p>The free workspace quota is <strong>200 MB</strong>. Checkout, coupon use, and human-only setup are not required.</p>
  <p>The <a href="/console">human verification console</a> lets a human-side agent enter a saved key, inspect the company/workspace/project boundary, read memory, send current messages to all agents or a particular agent, acknowledge notifications, and see redacted receipts.</p>
  <pre><code>curl -X POST /api/matm/agent-setup/free-account \\
  -H "Content-Type: application/json" \\
  -d "{\"companyLabel\":\"Example Company\",\"label\":\"Example Workspace\",\"projectLabel\":\"Example Project\"}"</code></pre>
</section>
"""
    return response(start_response, "200 OK", html_page("Agent Setup", body), "text/html; charset=utf-8")


def route_console(start_response):
    body = """
<section class="console-shell" data-matm-console>
  <h1>Human Verification Console</h1>
  <p>Enter a workspace key returned by the setup route. The key is used only in this browser session and is never printed back by this console.</p>
  <form class="console-grid" data-console-auth>
    <label>Workspace key
      <input type="password" name="workspaceKey" autocomplete="off" placeholder="me_live_..." required>
    </label>
    <label>Human agent id
      <input name="agentId" value="human-verifier-agent" required>
    </label>
    <button class="button primary" type="submit">Load workspace</button>
  </form>
  <div class="console-status" data-console-status>Waiting for a key.</div>
  <section class="console-panel">
    <h2>Workspace Overview</h2>
    <div class="operator-summary" data-console-workspace-summary>
      <p class="empty-state">Load a workspace to see account, company, workspace, project, storage, and redaction status.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-workspace>{}</pre>
    </details>
  </section>
  <section class="console-panel">
    <h2>Memory</h2>
    <form class="console-grid" data-console-memory>
      <label>Actor agent
        <input name="actorAgentId" value="human-verifier-agent" required>
      </label>
      <label>Scope
        <select name="scope">
          <option value="company">company</option>
          <option value="workspace" selected>workspace</option>
          <option value="project">project</option>
        </select>
      </label>
      <label>Title
        <input name="title" value="Human-side verification note" required>
      </label>
      <label>Tags
        <input name="tags" value="human-verification,matm">
      </label>
      <label class="wide">Public-safe summary
        <textarea name="summary" rows="4" required>Human verifier can read company, workspace, project, and memory state from the browser console.</textarea>
      </label>
      <button class="button primary" type="submit">Save memory</button>
    </form>
    <form class="console-grid" data-console-search>
      <label class="wide">Search memory
        <input name="query" value="verification">
      </label>
      <button class="button" type="submit">Search</button>
    </form>
    <div class="console-results" data-console-memory-list>
      <p class="empty-state">Search results will appear as scoped memory rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-memory-output>{}</pre>
    </details>
  </section>
  <section class="console-panel">
    <h2>Review Queue</h2>
    <form class="console-grid" data-console-review>
      <label>Review status
        <select name="status">
          <option value="pending" selected>pending</option>
          <option value="quarantined">quarantined</option>
          <option value="promoted">promoted</option>
          <option value="rejected">rejected</option>
          <option value="">all</option>
        </select>
      </label>
      <button class="button" type="submit">Refresh reviews</button>
    </form>
    <div class="console-results" data-console-review-list>
      <p class="empty-state">Review queue items will appear as promotion rows.</p>
    </div>
    <form class="console-grid" data-console-review-decision>
      <label>Reviewer agent
        <input name="reviewerAgentId" value="human-verifier-agent" required>
      </label>
      <label>Review id
        <input name="reviewId" placeholder="select or paste a review id" required>
      </label>
      <label>Decision
        <select name="decision">
          <option value="promote" selected>promote</option>
          <option value="reject">reject</option>
          <option value="quarantine">quarantine</option>
        </select>
      </label>
      <label class="wide">Review note
        <textarea name="reviewNote" rows="3">Public-safe operator review from the human console.</textarea>
      </label>
      <button class="button primary" type="submit">Submit decision</button>
    </form>
    <details class="debug-json">
      <summary>Review JSON</summary>
      <pre data-console-review-output>{}</pre>
    </details>
    <details class="debug-json">
      <summary>Decision JSON</summary>
      <pre data-console-review-decision-output>{}</pre>
    </details>
  </section>
  <section class="console-panel">
    <h2>Messages</h2>
    <form class="console-grid" data-console-message>
      <label>Sender agent
        <input name="senderAgentId" value="human-verifier-agent" required>
      </label>
      <label>Target agent
        <input name="targetAgentId" placeholder="blank means every agent">
      </label>
      <label class="wide">Safe summary
        <textarea name="safeSummary" rows="3" required>Hello Codex swarm: please confirm this workspace memory and message lane are readable from the human console.</textarea>
      </label>
      <label class="checkline">
        <input type="checkbox" name="responseRequired" checked>
        Response required
      </label>
      <button class="button primary" type="submit">Send message</button>
    </form>
    <form class="console-grid" data-console-inbox>
      <label>Inbox agent
        <input name="agentId" value="human-verifier-agent" required>
      </label>
      <button class="button" type="submit">Refresh inbox</button>
      <button class="button" type="button" data-console-ack>Mark first unread read</button>
    </form>
    <div class="console-results" data-console-inbox-list>
      <p class="empty-state">Inbox messages will appear as broadcast or targeted rows.</p>
    </div>
    <details class="debug-json">
      <summary>Debug JSON</summary>
      <pre data-console-inbox-output>{}</pre>
    </details>
  </section>
  <section class="console-panel">
    <h2>Receipts And Audit</h2>
    <div class="actions">
      <button class="button" type="button" data-console-receipts>Refresh receipts</button>
      <button class="button" type="button" data-console-audit>Refresh audit</button>
    </div>
    <div class="console-results" data-console-receipts-list>
      <p class="empty-state">Read receipts will appear after acknowledgements.</p>
    </div>
    <details class="debug-json">
      <summary>Receipts JSON</summary>
      <pre data-console-receipts-output>{}</pre>
    </details>
    <div class="console-results" data-console-audit-list>
      <p class="empty-state">Audit events will appear after refresh.</p>
    </div>
    <details class="debug-json">
      <summary>Audit JSON</summary>
      <pre data-console-audit-output>{}</pre>
    </details>
  </section>
</section>
"""
    return response(start_response, "200 OK", html_page("Console", body), "text/html; charset=utf-8")


def route_memory_lifecycle(start_response):
    body = """
<section class="page">
  <h1>Memory Lifecycle</h1>
  <ol>
    <li>The full <code>.uai/</code> suite is active startup memory; <code>.uai/startup-packet.uai</code> defines the read order.</li>
    <li>File handoff enters <code>agent-file-handoff/Content</code> or <code>agent-file-handoff/Improvement</code>.</li>
    <li>Reviewed durable strategy is dogfooded into hosted MemoryEndpoints workspace memory once MySQL is verified.</li>
    <li>Current messages are read through <code>/api/matm/current-message</code> and acknowledged through <code>/api/matm/notifications/ack</code>.</li>
    <li>Production database persistence requires the live MySQL/MariaDB backend to connect and pass protected workflow verification.</li>
  </ol>
</section>
"""
    return response(start_response, "200 OK", html_page("Memory Lifecycle", body), "text/html; charset=utf-8")


def route_transparency(start_response):
    body = """
<section class="page">
  <h1>Transparency</h1>
  <p>This project does not claim certification, endorsement, hidden credential validation, automatic memory promotion, or hosted runtime authority.</p>
  <p>Unsupported actions return safe no-op responses and human review guidance.</p>
</section>
"""
    return response(start_response, "200 OK", html_page("Transparency", body), "text/html; charset=utf-8")


def route_static(path, start_response):
    rel = path[len("/static/") :]
    target = (STATIC_ROOT / rel).resolve()
    if str(target).startswith(str(STATIC_ROOT.resolve())) and target.exists() and target.is_file():
        suffix = target.suffix.lower()
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        return response(start_response, "200 OK", target.read_bytes(), content_type)
    return problem(start_response, "404 Not Found", "Not found", "Static file not found.", "not_found")


def text_discovery(name):
    matrix = capability_matrix()
    lines = [
        SITE_NAME,
        "Purpose: pure MATM Multi-Agent Transactive Memory endpoint reference.",
        "Live public routes: " + ", ".join(matrix["publicRoutes"]),
        "Protected MATM routes: " + ", ".join(matrix["protectedRoutes"]),
        "Companion documentation: %s." % COMPANION_DOCS_URL,
        "Source repository: %s." % GITHUB_REPO_URL,
        "Memory boundary: hosted workspace memory for protected search; local files remain startup and migration evidence.",
        "Current-message lane: /api/matm/current-message with acknowledgement at /api/matm/notifications/ack.",
        "Readiness evidence: /api/matm/readiness-result.",
        "Authority boundary: no certification, endorsement, hidden credential validation, or automatic memory promotion.",
    ]
    if name == "robots.txt":
        return "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n\n# %s\n" % (SITE_URL, lines[1])
    return "\n".join(lines) + "\n"


def route_public_json(path, start_response):
    if path == "/api/version":
        backend_health = store_backend_health()
        return json_response(
            start_response,
            {
                "ok": backend_health["storeBackendVerified"],
                "site": SITE_NAME,
                "version": __version__,
                "generatedAt": utc_now(),
                "build": build_provenance(),
                "runtime": "python-stdlib-wsgi",
                "configuredStoreBackend": backend_health["configuredStoreBackend"],
                "storeBackend": backend_health["storeBackend"],
                "storeBackendVerified": backend_health["storeBackendVerified"],
                "storeBackendStatus": backend_health["storeBackendStatus"],
                "storeBackendHealth": backend_health,
                "thirdPartyRuntimeDependencies": backend_health["thirdPartyRuntimeDependencies"],
            },
        )
    if path == "/api/matm/live-capability-matrix":
        return json_response(start_response, {"ok": True, "data": capability_matrix()})
    if path == "/api/matm/route-inventory":
        return json_response(start_response, {"ok": True, "data": route_inventory()})
    if path == "/api/matm/readiness-result":
        return json_response(start_response, {"ok": True, "data": readiness_result()})
    if path == "/api/matm/redacted-example-receipts":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "schemaVersion": "memoryendpoints.redacted_receipts.v1",
                "examples": [
                    {
                        "receiptId": "receipt-example-redacted",
                        "workspaceId": "workspace-example",
                        "rawPayloadExposed": False,
                        "valuesRedacted": True,
                        "status": "read",
                    }
                ],
            },
        )
    if path == "/ai-manifest.json":
        return json_response(start_response, manifest())
    if path == "/.well-known/ai-agent.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "memoryendpoints.ai_agent.v1",
                "name": SITE_NAME,
                "capabilities": ["matm_memory", "current_message_inbox", "redacted_receipts", "workspace_quota", "readiness_evidence"],
                "manifest": "%s/ai-manifest.json" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "sourceRepository": GITHUB_REPO_URL,
            },
        )
    if path == "/.well-known/mcp.json":
        return json_response(
            start_response,
            {
                "schemaVersion": "mcp.well_known.v1",
                "name": SITE_NAME,
                "resources": "%s/mcp/resources" % SITE_URL,
                "companionDocumentation": COMPANION_DOCS_URL,
                "boundary": "Public resources only; protected MATM APIs require workspace key.",
            },
        )
    if path == "/mcp/resources":
        resources = [
            {
                "uri": "memoryendpoints://matm/capability-matrix",
                "name": "MemoryEndpoints Capability Matrix",
                "mimeType": "application/json",
                "route": "/api/matm/live-capability-matrix",
            },
            {
                "uri": "memoryendpoints://matm/redacted-example-receipts",
                "name": "Redacted Example Receipts",
                "mimeType": "application/json",
                "route": "/api/matm/redacted-example-receipts",
            },
            {
                "uri": "memoryendpoints://matm/readiness-result",
                "name": "MemoryEndpoints Readiness Result",
                "mimeType": "application/json",
                "route": "/api/matm/readiness-result",
            },
            {
                "uri": "memoryendpoints://matm/route-inventory",
                "name": "MemoryEndpoints Route Inventory",
                "mimeType": "application/json",
                "route": "/api/matm/route-inventory",
            },
            {
                "uri": "memoryendpoints://docs/companion-site",
                "name": "MultiAgentMemory.com Companion Documentation",
                "mimeType": "text/html",
                "url": COMPANION_DOCS_URL,
            },
        ]
        return json_response(start_response, {"ok": True, "resources": resources})
    return None


def route_admin_mysql_diagnostics(environ, start_response):
    if environ["REQUEST_METHOD"] != "GET":
        return problem(start_response, "405 Method Not Allowed", "Method not allowed", "Use GET for MySQL diagnostics.", "method_not_allowed")
    authorized, auth_status = _admin_diagnostics_authorized(environ)
    if auth_status == "not_configured":
        return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")
    if not authorized:
        return problem(start_response, "401 Unauthorized", "Diagnostics token required", "Send the diagnostics token in Authorization: Bearer.", "auth_required")
    diagnostics = mysql_config_diagnostics()
    connect_attempt = {
        "ok": False,
        "valuesRedacted": True,
    }
    try:
        MySQLStore().healthcheck()
        connect_attempt["ok"] = True
        connect_attempt["errorCode"] = None
    except Exception as exc:
        args = getattr(exc, "args", ()) or ()
        mysql_error_number = args[0] if args and isinstance(args[0], int) else None
        connect_attempt.update(
            {
                "errorCode": backend_error_code("mysql", exc),
                "errorType": exc.__class__.__name__,
                "mysqlErrorNumber": mysql_error_number,
                "sqlState": getattr(exc, "sqlstate", None),
                "messageFingerprint": _diagnostic_fingerprint(str(exc)),
            }
        )
    payload = {
        "ok": connect_attempt["ok"],
        "site": SITE_NAME,
        "generatedAt": utc_now(),
        "build": build_provenance(),
        "schemaVersion": "memoryendpoints.admin_mysql_diagnostics.v1",
        "authStatus": auth_status,
        "configuredStoreBackend": os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file",
        "configDiagnostics": diagnostics,
        "stageDiagnostics": mysql_connection_stage_diagnostics(),
        "connectAttempt": connect_attempt,
        "valuesRedacted": True,
    }
    return json_response(start_response, payload)


def route_setup(environ, start_response):
    if environ["REQUEST_METHOD"] == "GET":
        return json_response(
            start_response,
            {
                "ok": True,
                "site": SITE_NAME,
                "route": "/api/matm/agent-setup/free-account",
                "method": "POST",
                "storageLimitBytes": PUBLIC_STORAGE_BYTES,
                "hierarchy": {
                    "account": "identity or owner boundary",
                    "company": "organization boundary; accounts and companies are many-to-many through memberships",
                    "workspace": "workspace belongs to company",
                    "project": "project belongs to workspace",
                },
                "keyHandling": "The api key is returned once; save it outside public files and ordinary chat.",
                "idempotencySupported": False,
                "checkoutRequired": False,
            },
        )
    body = _read_body(environ)
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    workspace_id, key_id, token, account_id, company_id, project_id = _store().create_free_account(
        body.get("label") or body.get("workspaceLabel") or body.get("workspace_label"),
        body.get("companyLabel") or body.get("company_label"),
        body.get("projectLabel") or body.get("project_label"),
    )
    return json_response(
        start_response,
        {
            "ok": True,
            "accountId": account_id,
            "companyId": company_id,
            "workspaceId": workspace_id,
            "projectId": project_id,
            "keyId": key_id,
            "apiKeySecret": token,
            "hierarchy": {
                "accountId": account_id,
                "companyId": company_id,
                "workspaceId": workspace_id,
                "projectId": project_id,
                "accountToCompanyMembership": True,
                "companyToWorkspace": True,
                "workspaceToProject": True,
            },
            "showKeyOnce": True,
            "storeKeySafely": True,
            "rawKeyStoredByServer": False,
            "storageLimitBytes": PUBLIC_STORAGE_BYTES,
            "checkoutRequired": False,
            "idempotencySupported": False,
        },
        "201 Created",
    )


def _idempotency_replay_or_conflict(store, start_response, workspace_id, key, operation, body):
    replay = store.check_idempotency(workspace_id, key, operation, body)
    if not replay:
        return None
    if replay.get("status") == "idempotency_conflict":
        return json_response(start_response, replay, "409 Conflict")
    replay_status = replay.pop("_httpStatus", "200 OK")
    return json_response(start_response, replay, replay_status)


def _audit_read(store, workspace_id, auth, action, route, details=None):
    audit_details = {"route": route, "method": "GET"}
    audit_details.update(details or {})
    store.record_audit(workspace_id, action, auth.get("keyId") or "workspace-key", route, audit_details)


def route_protected(environ, start_response, path):
    method = environ["REQUEST_METHOD"]
    query = _query(environ)
    body = _read_body(environ) if method in ("POST", "PUT", "PATCH") else {}
    if body is None:
        return problem(start_response, "400 Bad Request", "Invalid JSON", "Request body must be JSON.", "invalid_json")
    workspace_id = (body or {}).get("workspaceId") or (body or {}).get("workspace_id") or query.get("workspace_id") or query.get("workspaceId")
    auth = _require_auth(environ, workspace_id)
    if not auth:
        return problem(start_response, "401 Unauthorized", "Workspace key required", "Use the free-account setup route, then send the key in Authorization: Bearer.", "auth_required")
    workspace_id = auth["workspaceId"]
    store = _store()
    idem = _idempotency_key(environ)
    if path == "/api/matm/workspace" and method == "GET":
        status = store.workspace_status(workspace_id)
        _audit_read(store, workspace_id, auth, "workspace.read", path, {"found": bool(status)})
        return json_response(start_response, {"ok": True, "workspace": status})
    if path == "/api/matm/audit-log" and method == "GET":
        _audit_read(store, workspace_id, auth, "audit_log.read", path, {"actionFilter": query.get("action") or "", "limit": query.get("limit") or ""})
        items = store.audit_log(workspace_id, query.get("limit") or 50, query.get("action"))
        return json_response(
            start_response,
            {
                "ok": True,
                "schemaVersion": "memoryendpoints.audit_log.v1",
                "items": items,
                "count": len(items),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
        )
    if path == "/api/matm/agents/register" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "agent-register", body)
        if replay:
            return replay
        if not (body.get("agentId") or body.get("agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Agent id required", "Agent registration requires agentId.", "agent_id_required")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this record.", "quota_exceeded")
        agent = store.register_agent(workspace_id, body.get("agentId") or body.get("agent_id"), body.get("displayName") or body.get("display_name"))
        payload = {"ok": True, "agent": agent}
        store.record_idempotency(workspace_id, idem, "agent-register", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/memory-events/submit" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "memory-submit", body)
        if replay:
            return replay
        summary = body.get("summary") or ""
        title = body.get("title") or "Untitled memory"
        if not (body.get("actorAgentId") or body.get("actor_agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Actor agent id required", "Memory events require actorAgentId.", "actor_agent_id_required")
        if not summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Summary required", "Memory events require a public-safe summary.", "summary_required")
        if len(summary) > 4000:
            return problem(start_response, "422 Unprocessable Entity", "Summary too long", "Memory event summaries must be at most 4000 characters.", "summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this memory event.", "quota_exceeded")
        event = store.submit_memory(
            workspace_id,
            body.get("actorAgentId") or body.get("actor_agent_id"),
            body.get("scope"),
            title,
            summary,
            body.get("tags") or [],
            body.get("source"),
            body.get("memoryType") or body.get("memory_type"),
            body.get("subject"),
            body.get("confidence"),
            body.get("scopeId") or body.get("scope_id"),
        )
        payload = {"ok": True, "event": event}
        store.record_idempotency(workspace_id, idem, "memory-submit", body, payload, "201 Created")
        return json_response(start_response, payload, "201 Created")
    if path == "/api/matm/review-queue" and method == "GET":
        items = store.review_queue(workspace_id, query.get("status"))
        _audit_read(store, workspace_id, auth, "review_queue.read", path, {"statusFilter": query.get("status") or "", "count": len(items)})
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "valuesRedacted": True,
                "promotionRoute": "/api/matm/review-queue/decide",
            },
        )
    if path == "/api/matm/review-queue/decide" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "review-decide", body)
        if replay:
            return replay
        review_id = body.get("reviewId") or body.get("review_id")
        reviewer_agent_id = body.get("reviewerAgentId") or body.get("reviewer_agent_id")
        decision = body.get("decision")
        if not review_id:
            return problem(start_response, "422 Unprocessable Entity", "Review id required", "Review decisions require reviewId.", "review_id_required")
        if not reviewer_agent_id:
            return problem(start_response, "422 Unprocessable Entity", "Reviewer agent id required", "Review decisions require reviewerAgentId.", "reviewer_agent_id_required")
        review, error = store.decide_review(workspace_id, review_id, reviewer_agent_id, decision, redact_text(body.get("reviewNote") or body.get("review_note") or ""))
        if error == "invalid_decision":
            return problem(start_response, "422 Unprocessable Entity", "Invalid review decision", "Decision must be promote, approve, reject, or quarantine.", "invalid_review_decision")
        if error == "not_found":
            return problem(start_response, "404 Not Found", "Review item not found", "No matching review queue item exists for this workspace.", "review_item_not_found")
        payload = {"ok": True, "review": review, "valuesRedacted": True}
        store.record_idempotency(workspace_id, idem, "review-decide", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path in ("/api/matm/memory-events", "/api/matm/search") and method == "GET":
        items = store.search_memory(workspace_id, query.get("q") or query.get("query"))
        _audit_read(store, workspace_id, auth, "memory.search", path, {"memoryCount": len(items), "memorySource": "hosted_workspace_store"})
        return json_response(
            start_response,
            {
                "ok": True,
                "items": items,
                "count": len(items),
                "memorySource": "hosted_workspace_store",
                "filesystemDocsIncluded": False,
            },
        )
    if path == "/api/matm/agent-messages" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "message-submit", body)
        if replay:
            return replay
        safe_summary = body.get("safeSummary") or body.get("safe_summary") or ""
        if not (body.get("senderAgentId") or body.get("sender_agent_id")):
            return problem(start_response, "422 Unprocessable Entity", "Sender agent id required", "Current messages require senderAgentId.", "sender_agent_id_required")
        if not safe_summary.strip():
            return problem(start_response, "422 Unprocessable Entity", "Safe summary required", "Current messages require a public-safe summary.", "safe_summary_required")
        if len(safe_summary) > 1000:
            return problem(start_response, "422 Unprocessable Entity", "Safe summary too long", "Current-message safe summaries must be at most 1000 characters.", "safe_summary_too_long")
        if not store.has_quota_for(workspace_id, body):
            return problem(start_response, "413 Payload Too Large", "Workspace quota exceeded", "The workspace does not have enough remaining storage for this current message.", "quota_exceeded")
        message, note = store.submit_message(
            workspace_id,
            body.get("senderAgentId") or body.get("sender_agent_id"),
            body.get("targetAgentId") or body.get("target_agent_id"),
            safe_summary,
            body.get("responseRequired") or body.get("response_required"),
        )
        payload = {"ok": True, "message": message, "notification": note}
        store.record_idempotency(workspace_id, idem, "message-submit", body, payload, "202 Accepted")
        return json_response(start_response, payload, "202 Accepted")
    if path in ("/api/matm/agent-inbox", "/api/matm/current-message") and method == "GET":
        items = store.inbox(workspace_id, query.get("agent_id") or query.get("agentId"))
        _audit_read(store, workspace_id, auth, "current_message.read" if path == "/api/matm/current-message" else "agent_inbox.read", path, {"unreadCount": len(items)})
        return json_response(
            start_response,
            {
                "ok": True,
                "currentMessageLane": path == "/api/matm/current-message",
                "items": items,
                "unreadCount": len(items),
                "responseStates": ["required_response", "viewed_acknowledgement"],
            },
        )
    if path == "/api/matm/notifications/ack" and method == "POST":
        replay = _idempotency_replay_or_conflict(store, start_response, workspace_id, idem, "notification-ack", body)
        if replay:
            return replay
        receipt = store.ack(workspace_id, body.get("notificationId") or body.get("notification_id"), body.get("consumerAgentId") or body.get("consumer_agent_id"), body.get("status") or "read")
        if not receipt:
            return problem(start_response, "404 Not Found", "Notification not found", "No matching notification exists for this workspace.", "notification_not_found")
        payload = {"ok": True, "receipt": receipt}
        store.record_idempotency(workspace_id, idem, "notification-ack", body, payload, "200 OK")
        return json_response(start_response, payload)
    if path == "/api/matm/receipts" and method == "GET":
        items = store.receipts(workspace_id, query.get("consumer_agent_id") or query.get("consumerAgentId"))
        _audit_read(store, workspace_id, auth, "receipts.read", path, {"count": len(items)})
        return json_response(start_response, {"ok": True, "items": items, "count": len(items), "valuesRedacted": True})
    return problem(start_response, "404 Not Found", "Route not found", "No protected route matched this request.", "not_found")


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    if path == "/" and method == "GET":
        return route_home(start_response)
    if path in ("/docs", "/docs/") and method == "GET":
        return route_docs(start_response)
    if path == "/agent-setup" and method == "GET":
        return route_agent_setup(start_response)
    if path == "/console" and method == "GET":
        return route_console(start_response)
    if path == "/memory-lifecycle" and method == "GET":
        return route_memory_lifecycle(start_response)
    if path == "/transparency" and method == "GET":
        return route_transparency(start_response)
    if path.startswith("/static/") and method == "GET":
        return route_static(path, start_response)
    if path in ("/robots.txt", "/llms.txt", "/llms-full.txt", "/ai.txt") and method == "GET":
        content_type = "text/plain; charset=utf-8"
        return response(start_response, "200 OK", text_discovery(path.rsplit("/", 1)[-1]), content_type)
    if path == "/sitemap.xml" and method == "GET":
        urls = "\n".join(["<url><loc>%s%s</loc></url>" % (SITE_URL, route) for route in PUBLIC_ROUTES if not route.startswith("/api")])
        return response(start_response, "200 OK", "<?xml version=\"1.0\"?><!-- MemoryEndpoints.com sitemap --><urlset>%s</urlset>" % urls, "application/xml; charset=utf-8")
    public = route_public_json(path, start_response) if method == "GET" else None
    if public:
        return public
    if path == "/api/admin/mysql-diagnostics":
        return route_admin_mysql_diagnostics(environ, start_response)
    if path == "/api/matm/agent-setup/free-account":
        return route_setup(environ, start_response)
    if path.startswith("/api/matm/"):
        return route_protected(environ, start_response, path)
    return problem(start_response, "404 Not Found", "Not found", "The requested route does not exist.", "not_found")
