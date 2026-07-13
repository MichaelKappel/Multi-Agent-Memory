# Connector Pairing v1 Threat Model

## Security objective

Pair one LocalEndpoint desktop agent to one human-approved workspace without
placing an authorization code, state, proof, credential, durable secret,
private payload, or sensitive identifier in a URL, browser history, referrer,
log, prompt, public response, or error. The resulting credential must have no
authority beyond the exact canonical agent, workspace, and closed four-scope
grant.

## Assets and trust boundaries

- Desktop-only setup state: PKCE verifier, state, request proof, claim and
  exchange idempotency keys, and a pending credential before secure storage.
- Browser approval: authenticated human session, recent password reauth, CSRF,
  same-origin and Fetch-Metadata enforcement, and opaque selector references.
- Server storage: constant-time verifiers/digests, scope digest, bounded
  derivation inputs, lifecycle metadata, redacted audit receipts, and no raw
  protocol secrets.
- Operating-system credential vault: the active connector credential after a
  successful one-time delivery.

## Threats and controls

| Threat | Required control |
| --- | --- |
| URL/history/referrer leakage | Only `publicRequestRef` appears in the approval path. It is 256-bit random, tenant-neutral, and non-authorizing. No query or fragment is accepted. |
| Browser callback interception | There is no code/state callback. `wakeUpUrl` is parameter-free, byte-for-byte registered, explicitly human-activated, and non-authorizing. |
| CSRF | Human mutations require the authenticated host-only session, trusted same-origin Origin and Fetch Metadata, and an in-memory CSRF token before body or storage dispatch. |
| Authorization-server mix-up | The desktop pins the exact HTTPS issuer and same-origin endpoint inventory; proof, state, client id, redirect URI, PKCE, and scope digest are bound to one request. |
| Custom-protocol hijacking or loopback listener race | Wake-up carries no authority. The body-only code still requires desktop-held proof/state and PKCE. Redirect validation permits only the registered custom URI byte-for-byte or exact `127.0.0.1` callback path and bounded dynamic port; `localhost` aliases are rejected. |
| Open redirect | Discovery/API operations never redirect. Approval accepts no redirect target from the browser and exposes only the pre-registered parameter-free wake-up URI through an explicit user action. |
| SSRF | The server never fetches the redirect/wake-up URI or any request-provided URL. Same-origin service endpoints are fixed; redirect validation is syntactic and allowlisted. |
| Request enumeration | A public ref resolves only client/agent display labels, scope-impact labels, status, and expiry; never company/workspace/project/agent/request IDs. |
| Approval UI tenant leakage | `companyRef` and `workspaceRef` are short-lived and bound to account, session, and request. Invalid binding is fixed 401; valid expiry is fixed 410. No stable IDs enter DOM/config/forms. |
| Claim theft or replay | Claim requires proof, state, client, redirect URI, scope binding, and exact Idempotency-Key/body. Pending 202 does not reserve the key. First success serializes to one code; changed body or key conflicts. |
| Code interception | The code is JSON-body-only, single-use, 60 seconds, and bound to PKCE S256, client, redirect URI, request, and scope digest. |
| Lost response duplication | Request, claim, exchange, activation, and lifecycle operations have exact-retry semantics. Deterministic recovery uses server-held secret material without persisting raw responses. |
| Secure-store failure | A pending credential has no workspace memory authority. Cancel it when possible or rely on automatic 600-second expiry. |
| Scope escalation/confused deputy | Exact `localendpoint-agent`, exact ordered scopes, versioned digest, connector-specific credential type, server-derived actor/workspace, and deny-before-parse route gating. |
| Rotation widening | Successors inherit the exact original scope array/digest and stable identity. Predecessor stays active until atomic activation. |
| Browser script exfiltration | Strict CSP, same-origin COOP/CORP, restrictive Permissions-Policy, `Referrer-Policy: no-referrer`, no opener, no automatic wake-up, BFCache/state scrubbing, and no third-party protected calls. |
| Logs/audit/error disclosure | Raw proof, state, code, PKCE verifier, connector secret, request body, secret-bearing retry response, reversible encoding, and raw private identifiers are forbidden. Protected connector audit rows keep only the action plus domain-separated HMAC correlation references; their workspace foreign-key field is null, public request references are pseudonymized, and account/session/authority/company/workspace/project/agent/pairing/rotation/credential/master-key IDs are never copied into actor, target, or details. If the credential pepper is unavailable, the audit row falls back to an uncorrelated event category rather than a raw value. Errors are fixed, non-reflective, and redacted. |
| Response overexposure | Pairing, rotation, request, grant, and credential-item projections use closed field allowlists. Internal request/company/project IDs, reasons, predecessor links, raw timestamps, and nested redaction copies never escape through these summaries. One-time responses attest authorized delivery, show-once behavior, and raw-secret non-persistence at the top level. |
| Oversized/parser abuse | Connector request bodies are rejected above 32 KiB before JSON/schema/storage dispatch. Discovery is bounded to 16 KiB; other connector JSON responses are bounded to 64 KiB and use explicit JSON. |
| Brute force/abuse | Persistent shared rate limits partition discovery, request, authorize, claim, exchange, activation, status, and lifecycle traffic; 429 supplies Retry-After. |

## Denied capabilities

Connector credentials cannot use human account/session routes, company or
access administration, invites, agent roster/inbox, meetings/messages,
audit/history, export/company lifecycle, knowledge/external-link mutation,
review, sync, or any unlisted route. The fixed denial is
`403 connector_scope_forbidden` before body parsing or data access.

## Verification obligations

Before the desktop reports Connected, authenticated readback must prove exact
workspace and agent identifiers, `credentialType=connector_agent`, exact scope
array and digest on principal/grant/pairing/credential metadata, active and not
revoked state, and no raw credential/private payload exposure. FileStore and
SQLite must pass the same flow, concurrency, replay, expiry, rotation,
revocation, disconnect, denial, and schema tests. Live evidence is valid only
after an authorized exact-SHA deployment and must be labeled separately from
local WSGI or fixture evidence.
