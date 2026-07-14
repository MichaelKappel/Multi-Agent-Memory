# Human one-time agent access contract

Status: frozen integration contract for the current human-access implementation. This document contains no credential values or private payloads.

## Product invariant

Humans authenticate with a username/password account that can hold explicit memberships in multiple companies. A raw company master token is accepted only by the bounded company-master-proof request and is cleared by the browser immediately. It is never used as the ongoing human session credential.

Humans can list agent identities and credential metadata after selecting a company. Existing raw agent tokens are never retrievable. “View a token” means prepare and reveal a new successor exactly once. The predecessor remains active until the human proves possession of the saved successor; confirmation then activates the successor and revokes the predecessor atomically.

Company-master and agent bearer tokens cannot call any human account, roster, history, export, recovery, lifecycle, setting, or replacement route. The separate machine access-plane `POST /api/matm/access/company-master-credentials` accepts either an existing company master for sibling delegation or an enabled company-scoped top-level agent for one human-operator master. Lower-scoped agents cannot issue, replace, revoke, list, or delegate credentials.

## Top-level agent company-master setting

`GET` and `PATCH /api/matm/human/companies/{companyId}/top-level-agent-master-credential-setting` require a selected authenticated human account with `owner` or `credential_admin` authority. `PATCH` also requires same-origin Fetch Metadata and the current CSRF token; its body is exactly `{"enabled": boolean}`. The default is enabled. The response exposes no credential material and names the canonical database column `matm_companies.top_level_agent_master_credential_enabled`. Disabling affects new top-level-agent issuance only and does not revoke existing company masters.

## Session and enrollment routes

### `POST /api/matm/human/company-master-proofs`

Request:

```json
{"companyMasterTokenSecret":"raw value accepted only by this request"}
```

Response `201` uses one-time-secret headers and returns:

```json
{
  "ok": true,
  "proof": {
    "masterProofId": "metadata id",
    "companyId": "metadata id",
    "status": "issued",
    "expiresAt": "UTC timestamp",
    "oneTime": true
  },
  "companyMasterProofSecret": "short-lived one-time proof",
  "valuesRedacted": true,
  "rawPayloadExposed": false
}
```

The browser clears the raw master input before awaiting the response. The proof secret is held only in an in-memory closure and is consumed by exactly one account-create or company-link operation.

### `POST /api/matm/human/accounts`

Request fields are `username`, optional `displayName`, `password`, and `companyMasterProofSecret`. Password confirmation is enforced by the UI and may also be supplied as `passwordConfirmation` for server-side equality validation.

Account, first owner membership, proof consumption, and session issuance are one transaction. The response `201` uses one-time-secret headers, sets the host-only human session cookie, and returns:

```json
{
  "ok": true,
  "created": true,
  "account": {"humanAccountId":"...","username":"...","displayName":"..."},
  "membership": {"authorityId":"...","companyId":"...","companyLabel":"...","role":"owner","permissions":["agent_inventory_read","credential_admin"]},
  "memberships": [{"authorityId":"...","companyId":"...","companyLabel":"...","role":"owner","permissions":["agent_inventory_read","credential_admin"]}],
  "humanSession": {"humanAccountSessionId":"...","selectedCompanyId":null,"expiresAt":"..."},
  "csrfToken": "one-time in-memory CSRF authority",
  "valuesRedacted": true,
  "rawPayloadExposed": false
}
```

`memberships` contains the same first membership. No orphan account is allowed if session issuance fails.

### `POST /api/matm/human/session`

Username/password login rotates to a fresh host-only cookie and CSRF token. Its response includes `account`, `memberships`, nested `humanSession`, and top-level `selectedCompanyId` for adapter compatibility. No company is implicitly selected after login.

### `GET /api/matm/human/session`

This is a same-origin cookie-bound revalidation operation. When invoked with browser same-origin Fetch Metadata it rotates the CSRF verifier and returns the new `csrfToken` with one-time/no-store headers. It includes `account`, `memberships`, nested `humanSession`, and top-level `selectedCompanyId`. It never returns tenant collections or agent roster data.

### `POST /api/matm/human/session/reauth`

Requires cookie, current CSRF, strict Origin, and same-origin Fetch Metadata. A correct password rotates the session cookie and CSRF token while preserving selected membership and records `passwordReauthenticatedAt`. Sensitive authority lasts no more than five minutes. The response is the complete session envelope (`account`, `memberships`, nested `humanSession`, top-level `selectedCompanyId`, and the rotated top-level `csrfToken`), and the frontend must establish it before the next protected mutation.

### `POST /api/matm/human/session/company`

Request is `{"authorityId":"..."}`. The server rotates cookie and CSRF and returns the complete revalidated session envelope. The frontend consumes that response directly; it does not send `companyId` and does not issue a second blind revalidation request.

### `POST /api/matm/human/company-memberships/link`

Requires recent password reauthentication and a fresh `companyMasterProofSecret`, never a raw master token. It returns the linked `membership` plus refreshed `memberships`. The selected company does not change implicitly.

## Roster and replacement routes

### `GET /api/matm/human/companies/{companyId}/agent-tokens`

Returns `{"items":[...]}` metadata only. Each item includes `credentialId`, stable `agentIdentityId`, human-readable agent name/display name, immutable `grant` ids/scope, status, creation/last-use timestamps, and `oneTimeSecretRetrievable:false`. Hashes, verifiers, raw credentials, and private memory are forbidden.

### `POST /api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements`

Requires selected-company match, `credential_admin`, recent password reauthentication, CSRF, and `Idempotency-Key`. Request may contain public-safe `reason` and bounded `expiresInSeconds` only; no predecessor/old-token field exists.

The first successful `201` returns nested `replacement` metadata and top-level `successorTokenSecret` under one-time-secret headers. An exact retry returns the same nested `replacement` metadata and top-level `successorCredentialAlreadyDelivered:true`; it never re-reveals the secret. A conflicting reuse of the idempotency key is a safe no-op conflict.

### `GET /api/matm/human/companies/{companyId}/agent-tokens/{credentialId}/replacements/{replacementId}`

Returns metadata-only status as `{"replacement":{...}}` for reconciliation: `prepared`, `confirmed`, `canceled`, or `expired`. It is the recovery authority after an unknown prepare, confirm, or cancel outcome.

### `POST .../{replacementId}/confirm`

The initial request requires `successorTokenProof` and an `Idempotency-Key`. Confirmation validates the selected company, replacement binding, recent human reauthentication, and successor possession, then atomically activates the successor and revokes the predecessor. Success and exact replay return `{"replacement":{...}}` with redacted terminal metadata; the exact retry may return the stored result after the UI has scrubbed the proof. Different requests cannot reuse the key.

### `POST .../{replacementId}/cancel`

Cancellation revokes only the pending successor and preserves the predecessor. Success and exact replay return `{"replacement":{...}}` with redacted terminal metadata. Expiry has the same predecessor-preserving outcome.

## Unknown-outcome UI recovery

- Lost prepare response: reconcile status. If the pending successor was created but its secret was not received, cancel it and start a fresh reauthenticated prepare. Never re-reveal it.
- Lost confirm response: reconcile status first. `confirmed` means scrub and refresh roster. `prepared` means request the human’s saved successor proof again unless an exact idempotent replay receipt is available. Never retain the proof merely for retries.
- Lost cancel response: reconcile status. `canceled` or `expired` closes safely; `prepared` permits another cancel.
- Every terminal path clears password, proof, successor reveal, possession input, replacement ids, cached roster, and CSRF state as appropriate.

## Stable error families

- `human_session_required` — `401`
- `human_owner_required`, `trusted_origin_required`, `csrf_required`, `csrf_invalid`, `human_reauthentication_failed`, `recent_reauthentication_required`, `human_credential_authority_required` — `403`
- `human_company_not_found` — `404`
- `selected_company_required`, `human_username_unavailable`, `idempotency_conflict`, `replacement_outcome_unknown` — `409`
- `company_master_proof_expired`, `company_master_proof_used`, `replacement_expired` — `410`
- `username_password_required` — `400`
- validation and malformed replacement bindings — `422`

All failures are typed, redacted, `safeNoOp:true`, and `Cache-Control: no-store`. Authentication failures do not include identifiers that reveal whether a username, company, agent, credential, or replacement exists.

## Demo parity

`/tour/human` uses the same markup, controller, validation, renderers, and route adapter. Only transport and session authority are injected. Demo state is clearly labeled, browser-session-local, resettable, secret-free, nonpersistent, and zero-network. Success, empty, validation, permission, expiry, cancel, logout, session expiry, lost prepare, lost confirm, and lost cancel are explicit scenarios.
