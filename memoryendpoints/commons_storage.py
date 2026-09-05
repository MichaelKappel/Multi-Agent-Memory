"""Persistence for the project-scoped MATM Commons contract.

This repository deliberately works through the configured MATM ``FileStore``
or relational store instance.  It does not create another storage authority or
select a fallback backend.
"""

import base64
import datetime
import hashlib
import hmac
import json
import re

from .commons import (
    COMMONS_POLICY_SCHEMA,
    COMMONS_ROOM_DESCRIPTION,
    COMMONS_ROOM_NAME,
    CommonsContractError,
    credential_expiry,
    decode_agent_cursor,
    decode_cursor,
    decode_enrollment_cursor,
    digest_text,
    encode_agent_cursor,
    encode_cursor,
    encode_enrollment_cursor,
    message_acknowledgement_binding,
    public_agent,
    public_message,
    public_message_revision,
    public_room,
    timestamp_expired,
)
from . import storage as storage_module
from .storage import FileStore, SQLiteStore


def _stable_id(prefix, *parts):
    material = "\n".join(str(part or "") for part in parts)
    return "%s-%s" % (prefix, hashlib.sha256(material.encode("utf-8")).hexdigest()[:24])


def _one_time_agent_credential(company_id, credential_id):
    return storage_module._governed_credential("agent", company_id, credential_id)


def _candidate_agent_credential(token, company_id):
    if type(token) is not str:
        raise CommonsContractError(
            "agent_credential_candidate_invalid",
            detail="candidateTokenSecret must be a JSON string.",
        )
    credential_id, secret = storage_module._parse_governed_credential(token, "agent")
    if (
        not credential_id
        or not re.fullmatch(r"agenttoken-[0-9a-f]{20}", credential_id)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", str(secret or ""))
    ):
        raise CommonsContractError(
            "agent_credential_candidate_invalid",
            detail=(
                "candidateTokenSecret must be a newly generated me_agent_v1 "
                "credential with an agenttoken identifier and 32-byte URL-safe secret."
            ),
        )
    return credential_id, storage_module._governed_credential_digest(
        "agent", company_id, credential_id, secret
    )


def _candidate_browser_session(token, company_id):
    if type(token) is not str:
        raise CommonsContractError(
            "browser_session_candidate_invalid",
            detail="candidateBrowserSessionSecret must be a JSON string.",
        )
    session_id, secret = storage_module._parse_governed_credential(
        token, "commonsbrowser"
    )
    if (
        not session_id
        or not re.fullmatch(r"commonsbrowser-[0-9a-f]{20}", session_id)
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", str(secret or ""))
    ):
        raise CommonsContractError(
            "browser_session_candidate_invalid",
            detail=(
                "candidateBrowserSessionSecret must be a newly generated "
                "me_commonsbrowser_v1 credential with a commonsbrowser identifier "
                "and 32-byte URL-safe secret."
            ),
        )
    return session_id, storage_module._governed_credential_digest(
        "commonsbrowser", company_id, session_id, secret
    )


def _iso_now():
    return storage_module.utc_now()


def _retention_elapsed(value, seconds):
    if not value:
        return False
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=int(seconds)
    )
    return parsed <= cutoff


def _retention_cutoff(seconds):
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=int(seconds))
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _credential_reference(auth):
    return str(
        (auth or {}).get("agentTokenId")
        or (auth or {}).get("masterKeyId")
        or (auth or {}).get("credentialId")
        or ""
    )


def _terminal_enrollment_agent_name(request_id):
    return "commons-tombstone-" + hashlib.sha256(
        str(request_id or "").encode("utf-8")
    ).hexdigest()[:24]


def _enrollment_profile_compacted(record):
    return bool(
        (record or {}).get("profileCompacted")
        or str((record or {}).get("agentName") or "").startswith(
            "commons-tombstone-"
        )
    )


class CommonsRepository(object):
    """One Commons repository projected through an existing MATM store."""

    def __init__(self, store, settings):
        self.store = store
        self.settings = dict(settings or {})
        self.workspace_id = str(self.settings.get("workspaceId") or "")
        self.project_id = str(self.settings.get("projectId") or "")
        self.sql = isinstance(store, SQLiteStore)
        self.room_id = _stable_id(
            "commonsroom", self.workspace_id, self.project_id, "public-commons-v1"
        )

    def _default_policy(self):
        return {
            "schemaVersion": COMMONS_POLICY_SCHEMA,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "humanApprovalRequired": bool(
                self.settings.get("humanApprovalRequiredByDefault", False)
            ),
            "revision": 0,
            "updatedAt": None,
            "updatedByCredentialId": None,
            "defaultAutonomousEnrollment": not bool(
                self.settings.get("humanApprovalRequiredByDefault", False)
            ),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def _canonical_room(self, created_at=None):
        return {
            "roomId": self.room_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "name": COMMONS_ROOM_NAME,
            "description": COMMONS_ROOM_DESCRIPTION,
            "visibility": "public",
            "membershipRequired": True,
            "status": "active",
            "createdAt": created_at,
        }

    def _scope_file(self, data):
        workspace = data.get("workspaces", {}).get(self.workspace_id)
        project = data.get("projects", {}).get(self.project_id)
        company = data.get("companies", {}).get((workspace or {}).get("companyId"))
        if (
            not workspace
            or workspace.get("status") != "active"
            or not project
            or project.get("workspaceId") != self.workspace_id
            or project.get("status") != "active"
            or not company
            or company.get("status") != "active"
        ):
            raise CommonsContractError(
                "commons_scope_unavailable",
                "503 Service Unavailable",
                "The configured Commons workspace/project scope is not active.",
            )
        return workspace, project, company

    def _scope_sql(self, connection, lock=False):
        statement = """
            SELECT w.workspace_id, w.company_id, w.status AS workspace_status,
                   p.project_id, p.status AS project_status, c.status AS company_status
            FROM matm_workspaces w
            JOIN matm_projects p ON p.workspace_id = w.workspace_id
            JOIN matm_companies c ON c.company_id = w.company_id
            WHERE w.workspace_id = ? AND p.project_id = ?
            """
        if lock and getattr(connection, "dialect", "sqlite") == "mysql":
            statement += " FOR UPDATE"
        row = connection.execute(
            statement,
            (self.workspace_id, self.project_id),
        ).fetchone()
        if (
            not row
            or row["workspace_status"] != "active"
            or row["project_status"] != "active"
            or row["company_status"] != "active"
        ):
            raise CommonsContractError(
                "commons_scope_unavailable",
                "503 Service Unavailable",
                "The configured Commons workspace/project scope is not active.",
            )
        return row

    def scope_available(self):
        try:
            if self.sql:
                with self.store._open_connection() as connection:
                    self._scope_sql(connection)
            else:
                self._scope_file(self.store._load())
            return True
        except CommonsContractError:
            return False

    def _policy_file(self, data):
        policy = data.get("commonsPolicies", {}).get(self.project_id)
        if not policy:
            return self._default_policy()
        return {
            "schemaVersion": COMMONS_POLICY_SCHEMA,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "humanApprovalRequired": bool(policy.get("humanApprovalRequired")),
            "revision": int(policy.get("revision") or 0),
            "updatedAt": policy.get("updatedAt"),
            "updatedByCredentialId": policy.get("updatedByCredentialId"),
            "defaultAutonomousEnrollment": not bool(
                self.settings.get("humanApprovalRequiredByDefault", False)
            ),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def _policy_sql(self, connection):
        row = connection.execute(
            "SELECT * FROM matm_commons_policies WHERE workspace_id = ? AND project_id = ?",
            (self.workspace_id, self.project_id),
        ).fetchone()
        if not row:
            return self._default_policy()
        return {
            "schemaVersion": COMMONS_POLICY_SCHEMA,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "humanApprovalRequired": bool(row["human_approval_required"]),
            "revision": int(row["revision"] or 0),
            "updatedAt": row["updated_at"],
            "updatedByCredentialId": row["updated_by_credential_id"],
            "defaultAutonomousEnrollment": not bool(
                self.settings.get("humanApprovalRequiredByDefault", False)
            ),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def policy(self):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                return self._policy_sql(connection)
        data = self.store._load()
        self._scope_file(data)
        return self._policy_file(data)

    def _file_idempotency(self, data, principal_id, operation, key, request_digest):
        record_key = _stable_id(
            "commonsidem",
            self.workspace_id,
            self.project_id,
            principal_id,
            operation,
            digest_text(key),
        )
        record = data.get("commonsIdempotency", {}).get(record_key)
        if record and not hmac.compare_digest(
            str(record.get("requestDigest") or ""), str(request_digest or "")
        ):
            raise CommonsContractError(
                "idempotency_conflict",
                "409 Conflict",
                "The Idempotency-Key was already used for a different Commons request.",
            )
        return record_key, record

    def _record_file_idempotency(
        self, data, record_key, principal_id, operation, key, request_digest, result_kind, result_id, status_code
    ):
        data.setdefault("commonsIdempotency", {})[record_key] = {
            "idempotencyRecordId": record_key,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "principalId": principal_id,
            "operation": operation,
            "idempotencyKeyHash": digest_text(key),
            "requestDigest": request_digest,
            "resultKind": result_kind,
            "resultId": result_id,
            "statusCode": int(status_code),
            "createdAt": _iso_now(),
        }

    def _sql_idempotency(self, connection, principal_id, operation, key, request_digest):
        key_hash = digest_text(key)
        row = connection.execute(
            """
            SELECT * FROM matm_commons_idempotency
            WHERE workspace_id = ? AND project_id = ? AND principal_id = ?
              AND operation = ? AND idempotency_key_hash = ?
            """,
            (self.workspace_id, self.project_id, principal_id, operation, key_hash),
        ).fetchone()
        if row and not hmac.compare_digest(
            str(row["request_digest"] or ""), str(request_digest or "")
        ):
            raise CommonsContractError(
                "idempotency_conflict",
                "409 Conflict",
                "The Idempotency-Key was already used for a different Commons request.",
            )
        return row

    def _record_sql_idempotency(
        self, connection, principal_id, operation, key, request_digest, result_kind, result_id, status_code
    ):
        connection.execute(
            """
            INSERT INTO matm_commons_idempotency (
              idempotency_record_id, workspace_id, project_id, principal_id,
              operation, idempotency_key_hash, request_digest, result_kind,
              result_id, status_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                storage_module._id("commonsidem"),
                self.workspace_id,
                self.project_id,
                principal_id,
                operation,
                digest_text(key),
                request_digest,
                result_kind,
                result_id,
                int(status_code),
                _iso_now(),
            ),
        )

    def set_policy(self, auth, human_approval_required, expected_revision, key, request_digest):
        if (auth or {}).get("credentialType") != "company_master":
            raise CommonsContractError(
                "company_master_required",
                "403 Forbidden",
                "A company master credential is required to change Commons enrollment policy.",
            )
        principal_id = _credential_reference(auth)
        if self.sql:
            return self._set_policy_sql(
                auth,
                human_approval_required,
                expected_revision,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            _workspace, _project, company = self._scope_file(data)
            principal_id = self._assert_bound_company_master_file(
                data, auth, company.get("companyId")
            )
            record_key, replay = self._file_idempotency(
                data, principal_id, "policy-set", key, request_digest
            )
            current = self._policy_file(data)
            if replay:
                return current, True
            if int(expected_revision) != int(current["revision"]):
                raise CommonsContractError(
                    "revision_conflict", "409 Conflict", "Commons policy revision changed."
                )
            now = _iso_now()
            data.setdefault("commonsPolicies", {})[self.project_id] = {
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "humanApprovalRequired": bool(human_approval_required),
                "revision": int(current["revision"]) + 1,
                "updatedAt": now,
                "updatedByCredentialId": principal_id,
            }
            self._record_file_idempotency(
                data,
                record_key,
                principal_id,
                "policy-set",
                key,
                request_digest,
                "policy",
                self.project_id,
                200,
            )
            self.store.audit(
                data,
                "commons.policy.set",
                principal_id,
                self.project_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "revision": int(current["revision"]) + 1,
                    "humanApprovalRequired": bool(human_approval_required),
                },
            )
            self.store._save(data)
            return self._policy_file(data), False

    def _set_policy_sql(
        self,
        auth,
        human_approval_required,
        expected_revision,
        key,
        request_digest,
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    scope = self._scope_sql(connection, lock=True)
                    principal_id = self._assert_bound_company_master_sql(
                        connection, auth, scope["company_id"]
                    )
                    replay = self._sql_idempotency(
                        connection, principal_id, "policy-set", key, request_digest
                    )
                    current = self._policy_sql(connection)
                    if replay:
                        return current, True
                    if int(expected_revision) != int(current["revision"]):
                        raise CommonsContractError(
                            "revision_conflict", "409 Conflict", "Commons policy revision changed."
                        )
                    now = _iso_now()
                    next_revision = int(current["revision"]) + 1
                    if int(current["revision"]) == 0 and current.get("updatedAt") is None:
                        try:
                            connection.execute(
                                """
                                INSERT INTO matm_commons_policies (
                                  workspace_id, project_id, human_approval_required,
                                  revision, updated_by_credential_id, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    self.workspace_id,
                                    self.project_id,
                                    1 if human_approval_required else 0,
                                    next_revision,
                                    principal_id,
                                    now,
                                ),
                            )
                        except Exception as exc:
                            if storage_module._is_sql_duplicate_key_conflict(exc):
                                raise CommonsContractError(
                                    "revision_conflict",
                                    "409 Conflict",
                                    "Commons policy revision changed.",
                                )
                            raise
                    else:
                        changed = connection.execute(
                            """
                            UPDATE matm_commons_policies
                            SET human_approval_required = ?, revision = ?,
                                updated_by_credential_id = ?, updated_at = ?
                            WHERE workspace_id = ? AND project_id = ? AND revision = ?
                            """,
                            (
                                1 if human_approval_required else 0,
                                next_revision,
                                principal_id,
                                now,
                                self.workspace_id,
                                self.project_id,
                                int(current["revision"]),
                            ),
                        )
                        if changed.rowcount != 1:
                            raise CommonsContractError(
                                "revision_conflict", "409 Conflict", "Commons policy revision changed."
                            )
                    self._record_sql_idempotency(
                        connection,
                        principal_id,
                        "policy-set",
                        key,
                        request_digest,
                        "policy",
                        self.project_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.policy.set",
                        principal_id,
                        self.project_id,
                        {
                            "projectId": self.project_id,
                            "revision": next_revision,
                            "humanApprovalRequired": bool(human_approval_required),
                        },
                    )
                    return self._policy_sql(connection), False

    def _ensure_room_file(self, data):
        room = data.setdefault("commonsRooms", {}).get(self.room_id)
        if not room:
            room = self._canonical_room(_iso_now())
            data["commonsRooms"][self.room_id] = room
        return room

    def _ensure_room_sql(self, connection):
        now = _iso_now()
        connection.execute(
            """
            INSERT OR IGNORE INTO matm_commons_rooms (
              room_id, workspace_id, project_id, name, description, visibility,
              membership_required, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'public', 1, 'active', ?, NULL)
            """,
            (
                self.room_id,
                self.workspace_id,
                self.project_id,
                COMMONS_ROOM_NAME,
                COMMONS_ROOM_DESCRIPTION,
                now,
            ),
        )
        return connection.execute(
            "SELECT * FROM matm_commons_rooms WHERE room_id = ? AND workspace_id = ? AND project_id = ?",
            (self.room_id, self.workspace_id, self.project_id),
        ).fetchone()

    def _profile_file(self, data, agent_id):
        return data.get("commonsAgentProfiles", {}).get(
            "%s:%s" % (self.project_id, agent_id)
        )

    def _profile_active_file(self, data, profile):
        if not profile or profile.get("status") != "active" or timestamp_expired(
            profile.get("credentialExpiresAt")
        ):
            return False
        token = data.get("agentTokens", {}).get(profile.get("agentTokenId"))
        grant = data.get("agentAccessGrants", {}).get((token or {}).get("grantId"))
        identity = data.get("agentIdentities", {}).get(profile.get("agentIdentityId"))
        workspace = data.get("workspaces", {}).get(self.workspace_id)
        project = data.get("projects", {}).get(self.project_id)
        company = data.get("companies", {}).get((workspace or {}).get("companyId"))
        return bool(
            token
            and token.get("agentIdentityId") == profile.get("agentIdentityId")
            and not token.get("revokedAt")
            and grant
            and grant.get("agentIdentityId") == profile.get("agentIdentityId")
            and grant.get("companyId") == (identity or {}).get("companyId")
            and grant.get("companyId") == (workspace or {}).get("companyId")
            and grant.get("workspaceId") == self.workspace_id
            and grant.get("projectId") == self.project_id
            and grant.get("scopeType") == "project"
            and grant.get("scopeId") == self.project_id
            and grant.get("commonsOnly") is True
            and grant.get("status") == "active"
            and not grant.get("revokedAt")
            and identity
            and identity.get("agentId") == profile.get("agentId")
            and identity.get("status") == "active"
            and project
            and project.get("workspaceId") == self.workspace_id
            and company
            and company.get("status") == "active"
        )

    def _profile_from_sql(self, row):
        if not row:
            return None
        return {
            "profileId": row["profile_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "agentIdentityId": row["agent_identity_id"],
            "agentTokenId": row["agent_token_id"],
            "agentId": row["agent_id"],
            "displayName": row["display_name"],
            "listed": bool(row["listed"]),
            "implementation": row["implementation"] or "",
            "capabilities": json.loads(row["capabilities_json"] or "[]"),
            "profileUrl": row["profile_url"] or "",
            "capabilityUrl": row["capability_url"] or "",
            "availability": row["availability"] or "",
            "credentialExpiresAt": row["credential_expires_at"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _profile_sql(self, connection, agent_id, active_only=False):
        suffix = (
            " AND p.status = 'active' AND p.credential_expires_at > ? "
            "AND i.status = 'active' AND c.status = 'active' "
            "AND t.revoked_at IS NULL AND g.status = 'active' AND g.revoked_at IS NULL"
            if active_only
            else ""
        )
        params = [self.workspace_id, self.project_id, agent_id]
        if active_only:
            params.append(_iso_now())
        return connection.execute(
            """
            SELECT p.*, i.status AS identity_status, t.revoked_at AS token_revoked_at,
                   g.status AS grant_status, g.revoked_at AS grant_revoked_at
            FROM matm_commons_agent_profiles p
            JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id
            JOIN matm_agent_tokens t ON t.agent_token_id = p.agent_token_id
              AND t.agent_identity_id = p.agent_identity_id
            JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id
              AND g.agent_identity_id = p.agent_identity_id
            JOIN matm_workspaces w ON w.workspace_id = p.workspace_id
              AND w.company_id = g.company_id AND w.company_id = i.company_id
            JOIN matm_projects pr ON pr.project_id = p.project_id
              AND pr.workspace_id = p.workspace_id
              AND g.project_id = pr.project_id AND g.workspace_id = pr.workspace_id
            JOIN matm_companies c ON c.company_id = w.company_id
            WHERE p.workspace_id = ? AND p.project_id = ? AND p.agent_id = ?
              AND i.agent_id = p.agent_id AND g.scope_type = 'project'
              AND g.scope_id = p.project_id AND g.commons_only = 1
            """ + suffix,
            tuple(params),
        ).fetchone()

    @staticmethod
    def _effective_enrollment_status(record):
        status = str((record or {}).get("status") or "")
        if status == "pending" and timestamp_expired((record or {}).get("expiresAt")):
            return "expired"
        return status

    @staticmethod
    def _enrollment_request_from_sql(row):
        if not row:
            return None
        result = {
            "enrollmentRequestId": row["enrollment_request_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "companyId": row["company_id"],
            "agentName": row["agent_name"],
            "displayName": row["display_name"],
            "listed": bool(row["listed"]),
            "implementation": row["implementation"] or "",
            "capabilities": json.loads(row["capabilities_json"] or "[]"),
            "profileUrl": row["profile_url"] or "",
            "capabilityUrl": row["capability_url"] or "",
            "availability": row["availability"] or "",
            "candidateTokenId": row["candidate_token_id"],
            "candidateTokenHash": row["candidate_token_hash"],
            "status": row["status"],
            "revision": int(row["revision"] or 1),
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
            "decidedAt": row["decided_at"],
            "decidedByCredentialId": row["decided_by_credential_id"],
            "activatedAgentIdentityId": row["activated_agent_identity_id"],
            "activatedProfileId": row["activated_profile_id"],
        }
        result["profileCompacted"] = _enrollment_profile_compacted(result)
        return result

    def _public_enrollment_request(self, record, profile=None, active=False):
        profile_compacted = _enrollment_profile_compacted(record)
        candidate_current = bool(
            profile
            and profile.get("agentTokenId") == record.get("candidateTokenId")
        )
        participation_active = bool(active)
        active = bool(
            active
            and candidate_current
        )
        status = self._effective_enrollment_status(record)
        credential_state = "not_activated"
        if status == "approved":
            if active:
                credential_state = "active"
            elif profile and not candidate_current:
                credential_state = "superseded"
            elif profile and timestamp_expired(profile.get("credentialExpiresAt")):
                credential_state = "expired"
            elif profile and profile.get("status") == "revoked":
                credential_state = "revoked"
            else:
                credential_state = "inactive"
        elif status in ("denied", "expired"):
            credential_state = status
        result = {
            "enrollmentRequestId": record.get("enrollmentRequestId"),
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentName": None if profile_compacted else record.get("agentName"),
            "displayName": None if profile_compacted else record.get("displayName"),
            "publicProfile": None if profile_compacted else {
                "listed": bool(record.get("listed")),
                "implementation": record.get("implementation") or "",
                "capabilities": list(record.get("capabilities") or []),
                "profileUrl": record.get("profileUrl") or "",
                "capabilityUrl": record.get("capabilityUrl") or "",
                "availability": record.get("availability") or "",
            },
            "profileCompacted": profile_compacted,
            "status": status,
            "revision": int(record.get("revision") or 1),
            "createdAt": record.get("createdAt"),
            "expiresAt": record.get("expiresAt"),
            "decidedAt": record.get("decidedAt"),
            "credentialState": credential_state,
            "credentialAccepted": credential_state == "active",
            "agentParticipationState": (
                "active" if participation_active else "inactive"
            ),
            "credentialCustody": "client_generated_and_retained",
            "rawCredentialPersisted": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        if profile and candidate_current:
            result["credentialExpiresAt"] = profile.get("credentialExpiresAt")
            result["agent"] = public_agent(profile, active=bool(active))
        return result

    @staticmethod
    def _enrollment_request_matches(
        record,
        agent_name,
        display_name,
        profile,
        request_digest=None,
        retained_request_digest=None,
    ):
        if _enrollment_profile_compacted(record):
            return bool(
                request_digest
                and retained_request_digest
                and hmac.compare_digest(
                    str(request_digest), str(retained_request_digest)
                )
            )
        return bool(
            record
            and record.get("agentName") == agent_name
            and record.get("displayName") == display_name
            and bool(record.get("listed")) == bool(profile.get("listed"))
            and (record.get("implementation") or "")
            == (profile.get("implementation") or "")
            and list(record.get("capabilities") or [])
            == list(profile.get("capabilities") or [])
            and (record.get("profileUrl") or "") == (profile.get("profileUrl") or "")
            and (record.get("capabilityUrl") or "")
            == (profile.get("capabilityUrl") or "")
            and (record.get("availability") or "")
            == (profile.get("availability") or "")
        )

    @staticmethod
    def _retained_enrollment_digest_file(data, request_id):
        for item in data.get("commonsIdempotency", {}).values():
            if (
                item.get("principalId") == "anonymous-enrollment"
                and item.get("operation") == "enroll"
                and item.get("resultKind") == "enrollment_request"
                and item.get("resultId") == request_id
            ):
                return item.get("requestDigest")
        return None

    @staticmethod
    def _retained_enrollment_digest_sql(connection, request_id):
        row = connection.execute(
            "SELECT request_digest FROM matm_commons_idempotency WHERE "
            "principal_id = 'anonymous-enrollment' AND operation = 'enroll' "
            "AND result_kind = 'enrollment_request' AND result_id = ? "
            "ORDER BY created_at, idempotency_record_id LIMIT 1",
            (request_id,),
        ).fetchone()
        return row["request_digest"] if row else None

    def _materialize_expired_enrollments_file(self, data, company_id):
        changed = []
        for item in data.get("commonsEnrollmentRequests", {}).values():
            if (
                item.get("workspaceId") == self.workspace_id
                and item.get("projectId") == self.project_id
                and item.get("companyId") == company_id
                and item.get("status") == "pending"
                and timestamp_expired(item.get("expiresAt"))
            ):
                item["status"] = "expired"
                item["revision"] = int(item.get("revision") or 1) + 1
                changed.append(item.get("enrollmentRequestId"))
                if len(changed) >= 128:
                    break
        if changed:
            self.store.audit(
                data,
                "commons.enrollment.expire",
                "commons-system",
                self.project_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "expiredCount": len(changed),
                    "terminalTombstonesPreserved": True,
                },
            )
            self.store._save(data)
        return len(changed)

    def _materialize_expired_enrollments_sql(self, connection, company_id):
        rows = connection.execute(
            "SELECT enrollment_request_id, revision FROM "
            "matm_commons_enrollment_requests WHERE workspace_id = ? "
            "AND project_id = ? AND company_id = ? AND status = 'pending' "
            "AND expires_at <= ? ORDER BY created_at, enrollment_request_id LIMIT 128",
            (self.workspace_id, self.project_id, company_id, _iso_now()),
        ).fetchall()
        changed = []
        for row in rows:
            result = connection.execute(
                "UPDATE matm_commons_enrollment_requests SET status = 'expired', "
                "revision = ? WHERE workspace_id = ? AND project_id = ? "
                "AND company_id = ? AND enrollment_request_id = ? AND status = 'pending' "
                "AND revision = ?",
                (
                    int(row["revision"] or 1) + 1,
                    self.workspace_id,
                    self.project_id,
                    company_id,
                    row["enrollment_request_id"],
                    int(row["revision"] or 1),
                ),
            )
            if result.rowcount == 1:
                changed.append(row["enrollment_request_id"])
        if changed:
            self.store._record_audit_sql(
                connection,
                self.workspace_id,
                "commons.enrollment.expire",
                "commons-system",
                self.project_id,
                {
                    "projectId": self.project_id,
                    "expiredCount": len(changed),
                    "terminalTombstonesPreserved": True,
                },
            )
        return len(changed)

    def _compact_terminal_enrollments_file(self, data, company_id):
        retention = int(
            self.settings.get("terminalEnrollmentRetentionSeconds")
            or 7 * 24 * 60 * 60
        )
        compacted = []
        for item in data.get("commonsEnrollmentRequests", {}).values():
            if (
                item.get("workspaceId") != self.workspace_id
                or item.get("projectId") != self.project_id
                or item.get("companyId") != company_id
                or _enrollment_profile_compacted(item)
            ):
                continue
            status = self._effective_enrollment_status(item)
            inactive_at = None
            if status in ("denied", "expired"):
                inactive_at = item.get("decidedAt") or item.get("expiresAt")
            elif status == "approved":
                token = data.get("agentTokens", {}).get(item.get("candidateTokenId"))
                grant = data.get("agentAccessGrants", {}).get(
                    (token or {}).get("grantId")
                )
                identity = data.get("agentIdentities", {}).get(
                    (token or {}).get("agentIdentityId")
                )
                profile = next(
                    (
                        candidate
                        for candidate in data.get("commonsAgentProfiles", {}).values()
                        if candidate.get("profileId") == item.get("activatedProfileId")
                    ),
                    None,
                )
                candidate_active = bool(
                    token
                    and grant
                    and identity
                    and profile
                    and profile.get("agentTokenId") == item.get("candidateTokenId")
                    and token.get("agentIdentityId") == profile.get("agentIdentityId")
                    and grant.get("agentIdentityId") == profile.get("agentIdentityId")
                    and grant.get("companyId") == company_id
                    and identity.get("companyId") == company_id
                    and grant.get("workspaceId") == self.workspace_id
                    and grant.get("projectId") == self.project_id
                    and self._profile_active_file(data, profile)
                )
                if candidate_active:
                    continue
                inactive_at = (
                    (token or {}).get("revokedAt")
                    or (grant or {}).get("revokedAt")
                    or (profile or {}).get("updatedAt")
                    or (profile or {}).get("credentialExpiresAt")
                    or item.get("decidedAt")
                )
            else:
                continue
            if not _retention_elapsed(inactive_at, retention):
                continue
            item.update(
                {
                    "agentName": _terminal_enrollment_agent_name(
                        item.get("enrollmentRequestId")
                    ),
                    "displayName": "",
                    "listed": False,
                    "implementation": "",
                    "capabilities": [],
                    "profileUrl": "",
                    "capabilityUrl": "",
                    "availability": "",
                    "decidedByCredentialId": None,
                    "profileCompacted": True,
                }
            )
            compacted.append(item.get("enrollmentRequestId"))
            if len(compacted) >= 128:
                break
        if compacted:
            self.store.audit(
                data,
                "commons.enrollment.compact",
                "commons-system",
                self.project_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "contentFreeTerminalRequests": len(compacted),
                    "candidateAndDecisionTombstonesPreserved": True,
                },
            )
            self.store._save(data)
        return len(compacted)

    def _compact_terminal_enrollments_sql(self, connection, company_id):
        retention = int(
            self.settings.get("terminalEnrollmentRetentionSeconds")
            or 7 * 24 * 60 * 60
        )
        cutoff = _retention_cutoff(retention)
        now = _iso_now()
        rows = connection.execute(
            "SELECT r.* FROM matm_commons_enrollment_requests r "
            "LEFT JOIN matm_agent_tokens t ON t.agent_token_id = r.candidate_token_id "
            "LEFT JOIN matm_commons_agent_profiles p ON "
            "p.profile_id = r.activated_profile_id "
            "LEFT JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id "
            "LEFT JOIN matm_agent_identities i ON i.agent_identity_id = t.agent_identity_id "
            "WHERE r.workspace_id = ? AND r.project_id = ? AND r.company_id = ? "
            "AND r.agent_name NOT LIKE 'commons-tombstone-%' AND ("
            "(r.status = 'denied' AND COALESCE(r.decided_at, r.expires_at) <= ?) OR "
            "(r.status = 'expired' AND r.expires_at <= ?) OR "
            "(r.status = 'approved' AND COALESCE(t.revoked_at, g.revoked_at, "
            "p.updated_at, p.credential_expires_at, r.decided_at) <= ? AND ("
            "t.agent_token_id IS NULL OR p.profile_id IS NULL OR "
            "p.agent_token_id <> r.candidate_token_id OR p.status <> 'active' OR "
            "p.credential_expires_at <= ? OR t.revoked_at IS NOT NULL OR "
            "g.grant_id IS NULL OR g.status <> 'active' OR g.revoked_at IS NOT NULL OR "
            "i.agent_identity_id IS NULL OR i.status <> 'active' OR "
            "t.agent_identity_id <> p.agent_identity_id OR "
            "g.agent_identity_id <> p.agent_identity_id OR "
            "g.company_id <> r.company_id OR i.company_id <> r.company_id OR "
            "g.workspace_id <> r.workspace_id OR g.project_id <> r.project_id))) "
            "ORDER BY r.created_at, r.enrollment_request_id LIMIT 128",
            (
                self.workspace_id,
                self.project_id,
                company_id,
                cutoff,
                cutoff,
                cutoff,
                now,
            ),
        ).fetchall()
        compacted = []
        for row in rows:
            request = self._enrollment_request_from_sql(row)
            if _enrollment_profile_compacted(request):
                continue
            changed = connection.execute(
                "UPDATE matm_commons_enrollment_requests SET agent_name = ?, "
                "display_name = '', listed = 0, implementation = '', "
                "capabilities_json = '[]', profile_url = '', capability_url = '', "
                "availability = '', decided_by_credential_id = NULL WHERE "
                "workspace_id = ? AND project_id = ? AND company_id = ? "
                "AND enrollment_request_id = ? AND agent_name = ?",
                (
                    _terminal_enrollment_agent_name(
                        request.get("enrollmentRequestId")
                    ),
                    self.workspace_id,
                    self.project_id,
                    company_id,
                    request.get("enrollmentRequestId"),
                    request.get("agentName"),
                ),
            )
            if changed.rowcount == 1:
                compacted.append(request.get("enrollmentRequestId"))
            if len(compacted) >= 128:
                break
        if compacted:
            self.store._record_audit_sql(
                connection,
                self.workspace_id,
                "commons.enrollment.compact",
                "commons-system",
                self.project_id,
                {
                    "projectId": self.project_id,
                    "contentFreeTerminalRequests": len(compacted),
                    "candidateAndDecisionTombstonesPreserved": True,
                },
            )
        return len(compacted)

    @staticmethod
    def _agent_has_public_attribution_file(data, agent_id):
        return any(
            item.get(field) == agent_id
            for collection, field in (
                ("commonsMessages", "authorAgentId"),
                ("commonsMessageRevisions", "authorAgentId"),
                ("commonsWithdrawals", "withdrawnByAgentId"),
                ("commonsAcknowledgements", "agentId"),
            )
            for item in data.get(collection, {}).values()
        )

    def _compact_inactive_agents_file(self, data, company_id):
        retention = int(
            self.settings.get("inactiveAgentRetentionSeconds")
            or 7 * 24 * 60 * 60
        )
        removable = []
        for profile_key, profile in data.get("commonsAgentProfiles", {}).items():
            if (
                profile.get("workspaceId") != self.workspace_id
                or profile.get("projectId") != self.project_id
            ):
                continue
            identity = data.get("agentIdentities", {}).get(
                profile.get("agentIdentityId")
            )
            if not identity or identity.get("companyId") != company_id:
                continue
            if self._profile_active_file(data, profile):
                continue
            inactive_at = (
                profile.get("updatedAt")
                if profile.get("status") == "revoked"
                else profile.get("credentialExpiresAt")
            )
            agent_id = profile.get("agentId")
            if not _retention_elapsed(inactive_at, retention) or self._agent_has_public_attribution_file(
                data, agent_id
            ):
                continue
            grants = [
                grant
                for grant in data.get("agentAccessGrants", {}).values()
                if grant.get("agentIdentityId") == profile.get("agentIdentityId")
            ]
            if not grants or any(
                not grant.get("commonsOnly")
                or grant.get("workspaceId") != self.workspace_id
                or grant.get("projectId") != self.project_id
                for grant in grants
            ):
                continue
            removable.append((profile_key, profile, identity, grants))
            if len(removable) >= 32:
                break
        if not removable:
            return 0
        now = _iso_now()
        for _profile_key, profile, _identity, _grants in removable:
            agent_id = profile.get("agentId")
            for collection, predicate in (
                (
                    "commonsBrowserSessions",
                    lambda item: item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("agentId") == agent_id,
                ),
                (
                    "commonsMemberships",
                    lambda item: item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("agentId") == agent_id,
                ),
            ):
                records = data.get(collection, {})
                for record_id in list(records):
                    if predicate(records.get(record_id) or {}):
                        records.pop(record_id, None)
            profile.update(
                {
                    "displayName": agent_id,
                    "listed": False,
                    "implementation": "",
                    "capabilities": [],
                    "profileUrl": "",
                    "capabilityUrl": "",
                    "availability": "",
                    "status": "retired",
                    "updatedAt": now,
                }
            )
        self.store.audit(
            data,
            "commons.retention.compact",
            "commons-system",
            self.project_id,
            self.workspace_id,
            {
                "projectId": self.project_id,
                "inactiveNonparticipatingAgentsRetired": len(removable),
                "credentialAndNameTombstonesPreserved": True,
                "publicContentPurged": False,
            },
        )
        self.store._save(data)
        return len(removable)

    def _compact_inactive_agents_sql(self, connection, company_id):
        retention = int(
            self.settings.get("inactiveAgentRetentionSeconds")
            or 7 * 24 * 60 * 60
        )
        cutoff = _retention_cutoff(retention)
        now = _iso_now()
        rows = connection.execute(
            "SELECT DISTINCT p.*, i.company_id FROM matm_commons_agent_profiles p "
            "JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id "
            "JOIN matm_agent_tokens t ON t.agent_token_id = p.agent_token_id "
            "AND t.agent_identity_id = p.agent_identity_id "
            "JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id "
            "AND g.agent_identity_id = p.agent_identity_id "
            "WHERE p.workspace_id = ? AND p.project_id = ? AND i.company_id = ? "
            "AND p.status <> 'retired' AND (p.credential_expires_at <= ? "
            "OR (t.revoked_at IS NOT NULL AND t.revoked_at <= ?) "
            "OR (g.revoked_at IS NOT NULL AND g.revoked_at <= ?) "
            "OR (p.status = 'revoked' AND p.updated_at <= ?) "
            "OR (i.status <> 'active' AND COALESCE(p.updated_at, p.created_at) <= ?)) "
            "AND NOT EXISTS (SELECT 1 FROM matm_agent_access_grants g2 WHERE "
            "g2.agent_identity_id = p.agent_identity_id AND (g2.commons_only <> 1 "
            "OR g2.workspace_id <> ? OR g2.project_id <> ?)) "
            "AND NOT EXISTS (SELECT 1 FROM matm_commons_messages m WHERE "
            "m.workspace_id = p.workspace_id AND m.project_id = p.project_id "
            "AND m.author_agent_id = p.agent_id) "
            "AND NOT EXISTS (SELECT 1 FROM matm_commons_message_revisions r WHERE "
            "r.workspace_id = p.workspace_id AND r.project_id = p.project_id "
            "AND r.author_agent_id = p.agent_id) "
            "AND NOT EXISTS (SELECT 1 FROM matm_commons_withdrawals w WHERE "
            "w.workspace_id = p.workspace_id AND w.project_id = p.project_id "
            "AND w.withdrawn_by_agent_id = p.agent_id) "
            "AND NOT EXISTS (SELECT 1 FROM matm_commons_acknowledgements a WHERE "
            "a.workspace_id = p.workspace_id AND a.project_id = p.project_id "
            "AND a.agent_id = p.agent_id) "
            "ORDER BY p.created_at, p.profile_id LIMIT 32",
            (
                self.workspace_id,
                self.project_id,
                company_id,
                cutoff,
                cutoff,
                cutoff,
                cutoff,
                cutoff,
                self.workspace_id,
                self.project_id,
            ),
        ).fetchall()
        removable = [self._profile_from_sql(row) for row in rows]
        for profile in removable:
            agent_id = profile.get("agentId")
            connection.execute(
                "DELETE FROM matm_commons_browser_sessions WHERE workspace_id = ? "
                "AND project_id = ? AND agent_id = ?",
                (self.workspace_id, self.project_id, agent_id),
            )
            connection.execute(
                "DELETE FROM matm_commons_memberships WHERE workspace_id = ? "
                "AND project_id = ? AND agent_id = ?",
                (self.workspace_id, self.project_id, agent_id),
            )
            connection.execute(
                "UPDATE matm_commons_agent_profiles SET display_name = agent_id, "
                "listed = 0, implementation = '', capabilities_json = '[]', "
                "profile_url = '', capability_url = '', availability = '', "
                "status = 'retired', updated_at = ? WHERE profile_id = ? "
                "AND workspace_id = ? AND project_id = ?",
                (
                    now,
                    profile.get("profileId"),
                    self.workspace_id,
                    self.project_id,
                ),
            )
        if removable:
            self.store._record_audit_sql(
                connection,
                self.workspace_id,
                "commons.retention.compact",
                "commons-system",
                self.project_id,
                {
                    "projectId": self.project_id,
                    "inactiveNonparticipatingAgentsRetired": len(removable),
                    "credentialAndNameTombstonesPreserved": True,
                    "publicContentPurged": False,
                },
            )
        return len(removable)

    def _pending_capacity_file(self, data, company_id):
        self._materialize_expired_enrollments_file(data, company_id)
        self._compact_terminal_enrollments_file(data, company_id)
        scoped_requests = [
            item
            for item in data.get("commonsEnrollmentRequests", {}).values()
            if item.get("workspaceId") == self.workspace_id
            and item.get("projectId") == self.project_id
            and item.get("companyId") == company_id
        ]
        if len(scoped_requests) >= int(
            self.settings.get("maximumEnrollmentTombstones") or 50000
        ):
            raise CommonsContractError(
                "enrollment_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded irreversible enrollment history limit.",
            )
        retained = sum(
            1
            for item in scoped_requests
            if not _enrollment_profile_compacted(item)
        )
        if retained >= int(
            self.settings.get("maximumRetainedEnrollments") or 5000
        ):
            raise CommonsContractError(
                "enrollment_retention_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its audit-preserving lifetime enrollment limit.",
            )
        company_requests = [
            item
            for item in data.get("commonsEnrollmentRequests", {}).values()
            if item.get("companyId") == company_id
        ]
        if len(company_requests) >= int(
            self.settings.get("maximumCompanyEnrollmentTombstones") or 200000
        ):
            raise CommonsContractError(
                "company_enrollment_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its bounded irreversible Commons enrollment history limit.",
            )
        company_retained = sum(
            1 for item in company_requests if not _enrollment_profile_compacted(item)
        )
        if company_retained >= int(
            self.settings.get("maximumCompanyRetainedEnrollments") or 20000
        ):
            raise CommonsContractError(
                "company_enrollment_retention_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its audit-preserving Commons enrollment limit.",
            )
        pending = sum(
            1
            for item in data.get("commonsEnrollmentRequests", {}).values()
            if item.get("workspaceId") == self.workspace_id
            and item.get("projectId") == self.project_id
            and self._effective_enrollment_status(item) == "pending"
        )
        if pending >= int(self.settings.get("maximumPendingEnrollments") or 100):
            raise CommonsContractError(
                "enrollment_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded pending-enrollment capacity.",
            )

    def _active_capacity_file(self, data, company_id):
        self._compact_inactive_agents_file(data, company_id)
        scoped_profiles = [
            item
            for item in data.get("commonsAgentProfiles", {}).values()
            if item.get("workspaceId") == self.workspace_id
            and item.get("projectId") == self.project_id
        ]
        if len(scoped_profiles) >= int(
            self.settings.get("maximumAgentTombstones") or 50000
        ):
            raise CommonsContractError(
                "agent_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded irreversible identity history limit.",
            )
        retained = sum(
            1 for item in scoped_profiles if item.get("status") != "retired"
        )
        if retained >= int(self.settings.get("maximumRetainedAgents") or 5000):
            raise CommonsContractError(
                "agent_retention_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its attribution-preserving lifetime identity limit.",
            )
        company_profiles = [
            item
            for item in data.get("commonsAgentProfiles", {}).values()
            if (
                data.get("agentIdentities", {})
                .get(item.get("agentIdentityId"), {})
                .get("companyId")
                == company_id
            )
        ]
        if len(company_profiles) >= int(
            self.settings.get("maximumCompanyAgentTombstones") or 200000
        ):
            raise CommonsContractError(
                "company_agent_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its bounded irreversible Commons identity history limit.",
            )
        company_retained = sum(
            1 for item in company_profiles if item.get("status") != "retired"
        )
        if company_retained >= int(
            self.settings.get("maximumCompanyRetainedAgents") or 20000
        ):
            raise CommonsContractError(
                "company_agent_retention_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its attribution-preserving Commons identity limit.",
            )
        active = sum(
            1
            for item in data.get("commonsAgentProfiles", {}).values()
            if item.get("workspaceId") == self.workspace_id
            and item.get("projectId") == self.project_id
            and self._profile_active_file(data, item)
        )
        if active >= int(self.settings.get("maximumActiveAgents") or 1000):
            raise CommonsContractError(
                "agent_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded active-agent capacity.",
            )

    def _active_capacity_sql(self, connection, company_id):
        self._compact_inactive_agents_sql(connection, company_id)
        retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_agent_profiles "
            "WHERE workspace_id = ? AND project_id = ?",
            (self.workspace_id, self.project_id),
        ).fetchone()
        if int(retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumAgentTombstones") or 50000
        ):
            raise CommonsContractError(
                "agent_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded irreversible identity history limit.",
            )
        retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_agent_profiles "
            "WHERE workspace_id = ? AND project_id = ? AND status <> 'retired'",
            (self.workspace_id, self.project_id),
        ).fetchone()
        if int(retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumRetainedAgents") or 5000
        ):
            raise CommonsContractError(
                "agent_retention_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its attribution-preserving lifetime identity limit.",
            )
        company_retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_agent_profiles p "
            "JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id "
            "WHERE i.company_id = ?",
            (company_id,),
        ).fetchone()
        if int(company_retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumCompanyAgentTombstones") or 200000
        ):
            raise CommonsContractError(
                "company_agent_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its bounded irreversible Commons identity history limit.",
            )
        company_retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_agent_profiles p "
            "JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id "
            "WHERE i.company_id = ? AND p.status <> 'retired'",
            (company_id,),
        ).fetchone()
        if int(company_retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumCompanyRetainedAgents") or 20000
        ):
            raise CommonsContractError(
                "company_agent_retention_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its attribution-preserving Commons identity limit.",
            )
        row = connection.execute(
            """
            SELECT COUNT(*) AS item_count
            FROM matm_commons_agent_profiles p
            JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id
            JOIN matm_agent_tokens t ON t.agent_token_id = p.agent_token_id
              AND t.agent_identity_id = p.agent_identity_id
            JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id
              AND g.agent_identity_id = p.agent_identity_id
            JOIN matm_workspaces w ON w.workspace_id = p.workspace_id
              AND w.company_id = g.company_id AND w.company_id = i.company_id
            JOIN matm_projects pr ON pr.project_id = p.project_id
              AND pr.workspace_id = p.workspace_id
              AND g.project_id = pr.project_id AND g.workspace_id = pr.workspace_id
            JOIN matm_companies c ON c.company_id = w.company_id
            WHERE p.workspace_id = ? AND p.project_id = ? AND p.status = 'active'
              AND p.credential_expires_at > ? AND t.revoked_at IS NULL
              AND i.agent_id = p.agent_id AND i.status = 'active'
              AND g.scope_type = 'project' AND g.scope_id = p.project_id
              AND g.commons_only = 1 AND g.status = 'active'
              AND g.revoked_at IS NULL AND c.status = 'active'
            """,
            (self.workspace_id, self.project_id, _iso_now()),
        ).fetchone()
        if int(row["item_count"] or 0) >= int(
            self.settings.get("maximumActiveAgents") or 1000
        ):
            raise CommonsContractError(
                "agent_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded active-agent capacity.",
            )

    def _pending_capacity_sql(self, connection, company_id):
        self._materialize_expired_enrollments_sql(connection, company_id)
        self._compact_terminal_enrollments_sql(connection, company_id)
        retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_enrollment_requests "
            "WHERE workspace_id = ? AND project_id = ? AND company_id = ?",
            (self.workspace_id, self.project_id, company_id),
        ).fetchone()
        if int(retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumEnrollmentTombstones") or 50000
        ):
            raise CommonsContractError(
                "enrollment_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded irreversible enrollment history limit.",
            )
        retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_enrollment_requests "
            "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
            "AND agent_name NOT LIKE 'commons-tombstone-%'",
            (self.workspace_id, self.project_id, company_id),
        ).fetchone()
        if int(retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumRetainedEnrollments") or 5000
        ):
            raise CommonsContractError(
                "enrollment_retention_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its audit-preserving lifetime enrollment limit.",
            )
        company_retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_enrollment_requests "
            "WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        if int(company_retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumCompanyEnrollmentTombstones") or 200000
        ):
            raise CommonsContractError(
                "company_enrollment_tombstone_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its bounded irreversible Commons enrollment history limit.",
            )
        company_retained_row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_enrollment_requests "
            "WHERE company_id = ? AND agent_name NOT LIKE 'commons-tombstone-%'",
            (company_id,),
        ).fetchone()
        if int(company_retained_row["item_count"] or 0) >= int(
            self.settings.get("maximumCompanyRetainedEnrollments") or 20000
        ):
            raise CommonsContractError(
                "company_enrollment_retention_capacity_reached",
                "429 Too Many Requests",
                "The company has reached its audit-preserving Commons enrollment limit.",
            )
        row = connection.execute(
            "SELECT COUNT(*) AS item_count FROM matm_commons_enrollment_requests "
            "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
            "AND status = 'pending' "
            "AND expires_at > ?",
            (self.workspace_id, self.project_id, company_id, _iso_now()),
        ).fetchone()
        if int(row["item_count"] or 0) >= int(
            self.settings.get("maximumPendingEnrollments") or 100
        ):
            raise CommonsContractError(
                "enrollment_capacity_reached",
                "429 Too Many Requests",
                "The project has reached its bounded pending-enrollment capacity.",
            )

    def authenticate_enrollment_candidate(self, candidate_token_secret):
        if type(candidate_token_secret) is not str:
            return None
        token_id, secret = storage_module._parse_governed_credential(
            candidate_token_secret, "agent"
        )
        if not token_id or not secret:
            return None
        if self.sql:
            with self.store._open_connection() as connection:
                try:
                    scope = self._scope_sql(connection)
                except CommonsContractError:
                    return None
                row = connection.execute(
                    "SELECT * FROM matm_commons_enrollment_requests WHERE "
                    "workspace_id = ? AND project_id = ? AND company_id = ? "
                    "AND candidate_token_id = ?",
                    (
                        self.workspace_id,
                        self.project_id,
                        scope["company_id"],
                        token_id,
                    ),
                ).fetchone()
                record = self._enrollment_request_from_sql(row)
                company_id = scope["company_id"]
        else:
            data = self.store._load()
            try:
                _workspace, _project, company = self._scope_file(data)
            except CommonsContractError:
                return None
            record = next(
                (
                    item
                    for item in data.get("commonsEnrollmentRequests", {}).values()
                    if item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("companyId") == company.get("companyId")
                    and item.get("candidateTokenId") == token_id
                ),
                None,
            )
            company_id = company.get("companyId")
        if not record:
            return None
        expected = storage_module._governed_credential_digest(
            "agent", company_id, token_id, secret
        )
        if not hmac.compare_digest(
            str(expected), str(record.get("candidateTokenHash") or "")
        ):
            return None
        return {
            "authType": "commons_enrollment_candidate",
            "enrollmentRequestId": record.get("enrollmentRequestId"),
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "companyId": company_id,
            "candidateTokenId": token_id,
            "isPrincipal": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def authenticate_agent_credential(self, token, allow_revoked=False):
        if type(token) is not str:
            return None
        token_id, secret = storage_module._parse_governed_credential(token, "agent")
        if not token_id or not secret:
            return None
        if self.sql:
            with self.store._open_connection() as connection:
                row = connection.execute(
                    """
                    SELECT t.*, g.company_id, g.scope_type, g.scope_id,
                           g.workspace_id, g.project_id, g.commons_only,
                           g.status AS grant_status, g.revoked_at AS grant_revoked_at,
                           i.agent_id, i.status AS identity_status,
                           c.status AS company_status
                    FROM matm_agent_tokens t
                    JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id
                      AND g.agent_identity_id = t.agent_identity_id
                    JOIN matm_agent_identities i ON i.agent_identity_id = t.agent_identity_id
                      AND i.company_id = g.company_id
                    JOIN matm_workspaces w ON w.workspace_id = g.workspace_id
                      AND w.company_id = g.company_id
                    JOIN matm_projects p ON p.project_id = g.project_id
                      AND p.workspace_id = g.workspace_id
                    JOIN matm_companies c ON c.company_id = g.company_id
                    WHERE t.agent_token_id = ?
                    """,
                    (token_id,),
                ).fetchone()
                if not row:
                    return None
                token_hash = row["token_hash"]
                company_id = row["company_id"]
                record = {
                    "agentTokenId": row["agent_token_id"],
                    "grantId": row["grant_id"],
                    "agentIdentityId": row["agent_identity_id"],
                    "agentId": row["agent_id"],
                    "companyId": company_id,
                    "workspaceId": row["workspace_id"],
                    "projectId": row["project_id"],
                    "scopeType": row["scope_type"],
                    "scopeId": row["scope_id"],
                    "commonsOnly": bool(row["commons_only"]),
                    "tokenRevoked": bool(row["revoked_at"]),
                    "grantActive": row["grant_status"] == "active"
                    and not row["grant_revoked_at"],
                    "identityActive": row["identity_status"] == "active",
                    "companyActive": row["company_status"] == "active",
                }
        else:
            data = self.store._load()
            token_record = data.get("agentTokens", {}).get(token_id)
            grant = data.get("agentAccessGrants", {}).get(
                (token_record or {}).get("grantId")
            )
            identity = data.get("agentIdentities", {}).get(
                (token_record or {}).get("agentIdentityId")
            )
            company = data.get("companies", {}).get((grant or {}).get("companyId"))
            if not token_record or not grant or not identity or not company:
                return None
            workspace = data.get("workspaces", {}).get(grant.get("workspaceId"))
            project = data.get("projects", {}).get(grant.get("projectId"))
            if (
                token_record.get("agentIdentityId")
                != grant.get("agentIdentityId")
                or token_record.get("agentIdentityId")
                != identity.get("agentIdentityId")
                or identity.get("companyId") != grant.get("companyId")
                or not workspace
                or workspace.get("companyId") != grant.get("companyId")
                or not project
                or project.get("workspaceId") != grant.get("workspaceId")
            ):
                return None
            token_hash = token_record.get("tokenHash")
            company_id = grant.get("companyId")
            record = {
                "agentTokenId": token_id,
                "grantId": grant.get("grantId"),
                "agentIdentityId": identity.get("agentIdentityId"),
                "agentId": identity.get("agentId"),
                "companyId": company_id,
                "workspaceId": grant.get("workspaceId"),
                "projectId": grant.get("projectId"),
                "scopeType": grant.get("scopeType"),
                "scopeId": grant.get("scopeId"),
                "commonsOnly": bool(grant.get("commonsOnly")),
                "tokenRevoked": bool(token_record.get("revokedAt")),
                "grantActive": grant.get("status") == "active"
                and not grant.get("revokedAt"),
                "identityActive": identity.get("status") == "active",
                "companyActive": company.get("status") == "active",
            }
        expected = storage_module._governed_credential_digest(
            "agent", company_id, token_id, secret
        )
        if not hmac.compare_digest(str(expected), str(token_hash or "")):
            return None
        if (
            not record["commonsOnly"]
            or record["workspaceId"] != self.workspace_id
            or record["projectId"] != self.project_id
            or record["scopeType"] != "project"
            or record["scopeId"] != self.project_id
            or not record["identityActive"]
            or not record["companyActive"]
            or (
                not allow_revoked
                and (record["tokenRevoked"] or not record["grantActive"])
            )
        ):
            return None
        return {
            "authType": "agent",
            "credentialType": "agent",
            "publicCredentialType": "commons_agent",
            "companyId": company_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentId": record["agentId"],
            "agentIdentityId": record["agentIdentityId"],
            "agentTokenId": token_id,
            "credentialId": token_id,
            "grantId": record["grantId"],
            "scopeType": "project",
            "scopeId": self.project_id,
            "commonsOnly": True,
            "active": not record["tokenRevoked"] and record["grantActive"],
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def enroll(
        self,
        agent_name,
        display_name,
        profile,
        candidate_token_secret,
        key,
        request_digest,
    ):
        if self.sql:
            return self._enroll_sql(
                agent_name,
                display_name,
                profile,
                candidate_token_secret,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            workspace, _project, company = self._scope_file(data)
            record_key, replay = self._file_idempotency(
                data, "anonymous-enrollment", "enroll", key, request_digest
            )
            if replay:
                if replay.get("resultKind") == "enrollment_request":
                    request = data.get("commonsEnrollmentRequests", {}).get(
                        replay.get("resultId")
                    )
                    if not request:
                        raise CommonsContractError(
                            "idempotency_state_unavailable", "409 Conflict"
                        )
                    existing = self._profile_file(data, request.get("agentName"))
                    return self._public_enrollment_request(
                        request,
                        existing,
                        self._profile_active_file(data, existing),
                    ), True
                replay_token_id = replay.get("resultId")
                replay_token = data.get("agentTokens", {}).get(replay_token_id)
                existing = next(
                    (
                        item
                        for item in data.get("commonsAgentProfiles", {}).values()
                        if item.get("workspaceId") == self.workspace_id
                        and item.get("projectId") == self.project_id
                        and item.get("agentIdentityId")
                        == (replay_token or {}).get("agentIdentityId")
                    ),
                    None,
                )
                if not existing or not replay_token:
                    raise CommonsContractError(
                        "idempotency_state_unavailable", "409 Conflict"
                    )
                return self._enrollment_result(
                    existing,
                    bool(
                        existing.get("agentTokenId") == replay_token_id
                        and self._profile_active_file(data, existing)
                    ),
                    replay_token_id,
                ), True
            policy = self._policy_file(data)
            token_id, token_digest = _candidate_agent_credential(
                candidate_token_secret, company.get("companyId")
            )
            candidate_request = next(
                (
                    item
                    for item in data.get("commonsEnrollmentRequests", {}).values()
                    if (
                        item.get("candidateTokenId") == token_id
                        or hmac.compare_digest(
                            str(item.get("candidateTokenHash") or ""), token_digest
                        )
                    )
                ),
                None,
            )
            if candidate_request:
                if (
                    candidate_request.get("workspaceId") != self.workspace_id
                    or candidate_request.get("projectId") != self.project_id
                    or candidate_request.get("companyId") != company.get("companyId")
                ):
                    raise CommonsContractError(
                        "agent_credential_candidate_unavailable", "409 Conflict"
                    )
                if not self._enrollment_request_matches(
                    candidate_request,
                    agent_name,
                    display_name,
                    profile,
                    request_digest,
                    self._retained_enrollment_digest_file(
                        data, candidate_request.get("enrollmentRequestId")
                    ),
                ):
                    raise CommonsContractError(
                        "agent_credential_candidate_unavailable", "409 Conflict"
                    )
                existing = self._profile_file(
                    data, candidate_request.get("agentName")
                )
                self._record_file_idempotency(
                    data,
                    record_key,
                    "anonymous-enrollment",
                    "enroll",
                    key,
                    request_digest,
                    "enrollment_request",
                    candidate_request.get("enrollmentRequestId"),
                    200,
                )
                self.store._save(data)
                return self._public_enrollment_request(
                    candidate_request,
                    existing,
                    self._profile_active_file(data, existing),
                ), True
            if any(
                item.get("workspaceId") == self.workspace_id
                and item.get("projectId") == self.project_id
                and item.get("agentName") == agent_name
                and self._effective_enrollment_status(item) == "pending"
                for item in data.get("commonsEnrollmentRequests", {}).values()
            ):
                raise CommonsContractError("enrollment_request_exists", "409 Conflict")
            if policy["humanApprovalRequired"]:
                self._pending_capacity_file(data, company.get("companyId"))
                if any(
                    item.get("companyId") == company.get("companyId")
                    and item.get("agentNameNormalized") == agent_name
                    for item in data.get("agentIdentities", {}).values()
                ) or self._profile_file(data, agent_name):
                    raise CommonsContractError(
                        "agent_name_unavailable",
                        "409 Conflict",
                        "That agentName is unavailable because it was already activated.",
                    )
                if any(
                    item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("agentName") == agent_name
                    and self._effective_enrollment_status(item) == "pending"
                    for item in data.get("commonsEnrollmentRequests", {}).values()
                ):
                    raise CommonsContractError(
                        "enrollment_request_exists", "409 Conflict"
                    )
                if token_id in data.get("agentTokens", {}) or any(
                    item.get("candidateTokenId") == token_id
                    or hmac.compare_digest(
                        str(item.get("candidateTokenHash") or ""), token_digest
                    )
                    for item in data.get("commonsEnrollmentRequests", {}).values()
                ):
                    raise CommonsContractError(
                        "agent_credential_candidate_unavailable", "409 Conflict"
                    )
                now = _iso_now()
                request_id = _stable_id(
                    "commonsenrollment",
                    self.workspace_id,
                    self.project_id,
                    token_id,
                )
                request = {
                    "enrollmentRequestId": request_id,
                    "workspaceId": self.workspace_id,
                    "projectId": self.project_id,
                    "companyId": company.get("companyId"),
                    "agentName": agent_name,
                    "displayName": display_name,
                    "listed": bool(profile.get("listed")),
                    "implementation": profile.get("implementation") or "",
                    "capabilities": list(profile.get("capabilities") or []),
                    "profileUrl": profile.get("profileUrl") or "",
                    "capabilityUrl": profile.get("capabilityUrl") or "",
                    "availability": profile.get("availability") or "",
                    "candidateTokenId": token_id,
                    "candidateTokenHash": token_digest,
                    "status": "pending",
                    "revision": 1,
                    "createdAt": now,
                    "expiresAt": credential_expiry(
                        self.settings.get("enrollmentRequestTtlSeconds") or 86400
                    ),
                    "decidedAt": None,
                    "decidedByCredentialId": None,
                    "activatedAgentIdentityId": None,
                    "activatedProfileId": None,
                }
                data.setdefault("commonsEnrollmentRequests", {})[request_id] = request
                self._record_file_idempotency(
                    data,
                    record_key,
                    "anonymous-enrollment",
                    "enroll",
                    key,
                    request_digest,
                    "enrollment_request",
                    request_id,
                    202,
                )
                self.store.audit(
                    data,
                    "commons.enrollment.pending",
                    "anonymous-enrollment",
                    request_id,
                    self.workspace_id,
                    {"projectId": self.project_id, "revision": 1},
                )
                self.store._save(data)
                return self._public_enrollment_request(request), False
            if any(
                item.get("companyId") == company.get("companyId")
                and item.get("agentNameNormalized") == agent_name
                for item in data.get("agentIdentities", {}).values()
            ) or self._profile_file(data, agent_name):
                raise CommonsContractError(
                    "agent_name_unavailable", "409 Conflict", "That agentName was already activated."
                )
            self._active_capacity_file(data, company.get("companyId"))
            now = _iso_now()
            identity_id = storage_module._id("agentidentity")
            grant_id = storage_module._id("grant")
            if token_id in data.get("agentTokens", {}):
                raise CommonsContractError(
                    "agent_credential_candidate_unavailable", "409 Conflict"
                )
            expires_at = credential_expiry(self.settings.get("credentialTtlSeconds"))
            data.setdefault("agentIdentities", {})[identity_id] = {
                "agentIdentityId": identity_id,
                "companyId": company.get("companyId"),
                "agentId": agent_name,
                "agentName": agent_name,
                "agentNameNormalized": agent_name,
                "displayName": display_name,
                "status": "active",
                "createdAt": now,
                "updatedAt": None,
            }
            data.setdefault("agentAccessGrants", {})[grant_id] = {
                "grantId": grant_id,
                "companyId": company.get("companyId"),
                "agentIdentityId": identity_id,
                "scopeType": "project",
                "scopeId": self.project_id,
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "supersedesTokenId": None,
                "memoryTransferFromTokenId": None,
                "commonsOnly": True,
                "status": "active",
                "createdAt": now,
                "pendingExpiresAt": None,
                "predecessorTokenId": None,
                "activatedAt": now,
                "cancelledAt": None,
                "revokedAt": None,
                "revokedByMasterKeyId": None,
            }
            data.setdefault("agentTokens", {})[token_id] = {
                "agentTokenId": token_id,
                "grantId": grant_id,
                "agentIdentityId": identity_id,
                "tokenHash": token_digest,
                "createdAt": now,
                "lastUsedAt": None,
                "revokedAt": None,
            }
            data.setdefault("agents", {})[
                "%s:%s" % (self.workspace_id, agent_name)
            ] = {
                "workspaceId": self.workspace_id,
                "agentId": agent_name,
                "displayName": display_name,
                "registeredAt": now,
                "status": "active",
            }
            profile_record = {
                "profileId": storage_module._id("commonsprofile"),
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "agentIdentityId": identity_id,
                "agentTokenId": token_id,
                "agentId": agent_name,
                "displayName": display_name,
                "listed": bool(profile.get("listed")),
                "implementation": profile.get("implementation") or "",
                "capabilities": list(profile.get("capabilities") or []),
                "profileUrl": profile.get("profileUrl") or "",
                "capabilityUrl": profile.get("capabilityUrl") or "",
                "availability": profile.get("availability") or "",
                "credentialExpiresAt": expires_at,
                "status": "active",
                "createdAt": now,
                "updatedAt": None,
            }
            data.setdefault("commonsAgentProfiles", {})[
                "%s:%s" % (self.project_id, agent_name)
            ] = profile_record
            self._ensure_room_file(data)
            self._record_file_idempotency(
                data,
                record_key,
                "anonymous-enrollment",
                "enroll",
                key,
                request_digest,
                "agent",
                token_id,
                201,
            )
            self.store.audit(
                data,
                "commons.agent.enroll",
                agent_name,
                identity_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "listed": bool(profile_record["listed"]),
                    "credentialExpiresAt": expires_at,
                },
            )
            self.store._save(data)
            return self._enrollment_result(profile_record, True, token_id), False

    def _enrollment_result(self, profile, active=True, credential_id=None):
        result = {
            "status": "active" if active else "credential_inactive",
            "agent": public_agent(profile, active=bool(active)),
            "principal": {
                "authority": "commons_only",
                "credentialType": "agent_token",
                "credentialId": credential_id or profile.get("agentTokenId"),
                "agentId": profile.get("agentId"),
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "scopeType": "project",
                "scopeId": self.project_id,
                "credentialExpiresAt": profile.get("credentialExpiresAt"),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            },
            "credentialAccepted": bool(active),
            "credentialCustody": "client_generated_and_retained",
            "credentialReturnedOnce": False,
            "rawCredentialPersisted": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        return result

    def _enroll_sql(
        self,
        agent_name,
        display_name,
        profile,
        candidate_token_secret,
        key,
        request_digest,
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    scope = self._scope_sql(connection, lock=True)
                    replay = self._sql_idempotency(
                        connection, "anonymous-enrollment", "enroll", key, request_digest
                    )
                    if replay:
                        if replay["result_kind"] == "enrollment_request":
                            row = connection.execute(
                                "SELECT * FROM matm_commons_enrollment_requests "
                                "WHERE workspace_id = ? AND project_id = ? "
                                "AND company_id = ? "
                                "AND enrollment_request_id = ?",
                                (
                                    self.workspace_id,
                                    self.project_id,
                                    scope["company_id"],
                                    replay["result_id"],
                                ),
                            ).fetchone()
                            request = self._enrollment_request_from_sql(row)
                            if not request:
                                raise CommonsContractError(
                                    "idempotency_state_unavailable", "409 Conflict"
                                )
                            profile_record = self._profile_from_sql(
                                self._profile_sql(
                                    connection, request.get("agentName")
                                )
                            )
                            active = bool(
                                self._profile_sql(
                                    connection,
                                    request.get("agentName"),
                                    active_only=True,
                                )
                            )
                            return self._public_enrollment_request(
                                request, profile_record, active
                            ), True
                        replay_token_id = replay["result_id"]
                        row = connection.execute(
                            "SELECT p.* FROM matm_agent_tokens t JOIN "
                            "matm_commons_agent_profiles p ON "
                            "p.workspace_id = ? AND p.project_id = ? AND "
                            "p.agent_identity_id = t.agent_identity_id WHERE "
                            "t.agent_token_id = ?",
                            (self.workspace_id, self.project_id, replay_token_id),
                        ).fetchone()
                        profile_record = self._profile_from_sql(row)
                        if not profile_record:
                            raise CommonsContractError(
                                "idempotency_state_unavailable", "409 Conflict"
                            )
                        active = bool(
                            profile_record.get("agentTokenId") == replay_token_id
                            and self._profile_sql(
                                connection,
                                profile_record.get("agentId"),
                                active_only=True,
                            )
                        )
                        return self._enrollment_result(
                            profile_record, active, replay_token_id
                        ), True
                    policy = self._policy_sql(connection)
                    token_id, token_digest = _candidate_agent_credential(
                        candidate_token_secret, scope["company_id"]
                    )
                    candidate_row = connection.execute(
                        "SELECT * FROM matm_commons_enrollment_requests WHERE "
                        "(candidate_token_id = ? OR candidate_token_hash = ?)",
                        (token_id, token_digest),
                    ).fetchone()
                    candidate_request = self._enrollment_request_from_sql(
                        candidate_row
                    )
                    if candidate_request:
                        if (
                            candidate_request.get("workspaceId") != self.workspace_id
                            or candidate_request.get("projectId") != self.project_id
                            or candidate_request.get("companyId") != scope["company_id"]
                        ):
                            raise CommonsContractError(
                                "agent_credential_candidate_unavailable",
                                "409 Conflict",
                            )
                        if not self._enrollment_request_matches(
                            candidate_request,
                            agent_name,
                            display_name,
                            profile,
                            request_digest,
                            self._retained_enrollment_digest_sql(
                                connection,
                                candidate_request.get("enrollmentRequestId"),
                            ),
                        ):
                            raise CommonsContractError(
                                "agent_credential_candidate_unavailable",
                                "409 Conflict",
                            )
                        profile_record = self._profile_from_sql(
                            self._profile_sql(
                                connection, candidate_request.get("agentName")
                            )
                        )
                        active = bool(
                            profile_record
                            and self._profile_sql(
                                connection,
                                candidate_request.get("agentName"),
                                active_only=True,
                            )
                        )
                        self._record_sql_idempotency(
                            connection,
                            "anonymous-enrollment",
                            "enroll",
                            key,
                            request_digest,
                            "enrollment_request",
                            candidate_request.get("enrollmentRequestId"),
                            200,
                        )
                        return self._public_enrollment_request(
                            candidate_request, profile_record, active
                        ), True
                    if connection.execute(
                        "SELECT enrollment_request_id FROM matm_commons_enrollment_requests "
                        "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
                        "AND agent_name = ? AND status = 'pending' AND expires_at > ?",
                        (
                            self.workspace_id,
                            self.project_id,
                            scope["company_id"],
                            agent_name,
                            _iso_now(),
                        ),
                    ).fetchone():
                        raise CommonsContractError(
                            "enrollment_request_exists", "409 Conflict"
                        )
                    if policy["humanApprovalRequired"]:
                        self._pending_capacity_sql(connection, scope["company_id"])
                        if connection.execute(
                            "SELECT agent_identity_id FROM matm_agent_identities "
                            "WHERE company_id = ? AND agent_name_normalized = ?",
                            (scope["company_id"], agent_name),
                        ).fetchone() or connection.execute(
                            "SELECT profile_id FROM matm_commons_agent_profiles WHERE "
                            "workspace_id = ? AND project_id = ? AND agent_id = ?",
                            (self.workspace_id, self.project_id, agent_name),
                        ).fetchone():
                            raise CommonsContractError(
                                "agent_name_unavailable", "409 Conflict"
                            )
                        if connection.execute(
                            "SELECT enrollment_request_id FROM matm_commons_enrollment_requests "
                            "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
                            "AND agent_name = ? AND status = 'pending' AND expires_at > ?",
                            (
                                self.workspace_id,
                                self.project_id,
                                scope["company_id"],
                                agent_name,
                                _iso_now(),
                            ),
                        ).fetchone():
                            raise CommonsContractError(
                                "enrollment_request_exists", "409 Conflict"
                            )
                        if connection.execute(
                            "SELECT agent_token_id FROM matm_agent_tokens "
                            "WHERE agent_token_id = ? OR token_hash = ?",
                            (token_id, token_digest),
                        ).fetchone() or connection.execute(
                            "SELECT enrollment_request_id FROM matm_commons_enrollment_requests "
                            "WHERE candidate_token_id = ? OR candidate_token_hash = ?",
                            (token_id, token_digest),
                        ).fetchone():
                            raise CommonsContractError(
                                "agent_credential_candidate_unavailable", "409 Conflict"
                            )
                        now = _iso_now()
                        request_id = _stable_id(
                            "commonsenrollment",
                            self.workspace_id,
                            self.project_id,
                            token_id,
                        )
                        expires_at = credential_expiry(
                            self.settings.get("enrollmentRequestTtlSeconds") or 86400
                        )
                        connection.execute(
                            """
                            INSERT INTO matm_commons_enrollment_requests (
                              enrollment_request_id, workspace_id, project_id,
                              company_id, agent_name, display_name, listed,
                              implementation, capabilities_json, profile_url,
                              capability_url, availability, candidate_token_id,
                              candidate_token_hash, status, revision, created_at,
                              expires_at, decided_at, decided_by_credential_id,
                              activated_agent_identity_id, activated_profile_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, NULL, NULL, NULL, NULL)
                            """,
                            (
                                request_id,
                                self.workspace_id,
                                self.project_id,
                                scope["company_id"],
                                agent_name,
                                display_name,
                                1 if profile.get("listed") else 0,
                                profile.get("implementation") or "",
                                _json(list(profile.get("capabilities") or [])),
                                profile.get("profileUrl") or "",
                                profile.get("capabilityUrl") or "",
                                profile.get("availability") or "",
                                token_id,
                                token_digest,
                                now,
                                expires_at,
                            ),
                        )
                        self._record_sql_idempotency(
                            connection,
                            "anonymous-enrollment",
                            "enroll",
                            key,
                            request_digest,
                            "enrollment_request",
                            request_id,
                            202,
                        )
                        self.store._record_audit_sql(
                            connection,
                            self.workspace_id,
                            "commons.enrollment.pending",
                            "anonymous-enrollment",
                            request_id,
                            {"projectId": self.project_id, "revision": 1},
                        )
                        row = connection.execute(
                            "SELECT * FROM matm_commons_enrollment_requests "
                            "WHERE workspace_id = ? AND project_id = ? "
                            "AND company_id = ? AND enrollment_request_id = ?",
                            (
                                self.workspace_id,
                                self.project_id,
                                scope["company_id"],
                                request_id,
                            ),
                        ).fetchone()
                        return self._public_enrollment_request(
                            self._enrollment_request_from_sql(row)
                        ), False
                    if connection.execute(
                        "SELECT agent_identity_id FROM matm_agent_identities WHERE company_id = ? AND agent_name_normalized = ?",
                        (scope["company_id"], agent_name),
                    ).fetchone() or connection.execute(
                        "SELECT profile_id FROM matm_commons_agent_profiles WHERE "
                        "workspace_id = ? AND project_id = ? AND agent_id = ?",
                        (self.workspace_id, self.project_id, agent_name),
                    ).fetchone():
                        raise CommonsContractError(
                            "agent_name_unavailable", "409 Conflict", "That agentName was already activated."
                        )
                    self._active_capacity_sql(connection, scope["company_id"])
                    now = _iso_now()
                    identity_id = storage_module._id("agentidentity")
                    grant_id = storage_module._id("grant")
                    if connection.execute(
                        "SELECT agent_token_id FROM matm_agent_tokens WHERE agent_token_id = ? OR token_hash = ?",
                        (token_id, token_digest),
                    ).fetchone():
                        raise CommonsContractError(
                            "agent_credential_candidate_unavailable", "409 Conflict"
                        )
                    expires_at = credential_expiry(
                        self.settings.get("credentialTtlSeconds")
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_agent_identities (
                          agent_identity_id, company_id, agent_id, agent_name,
                          agent_name_normalized, display_name, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, NULL)
                        """,
                        (
                            identity_id,
                            scope["company_id"],
                            agent_name,
                            agent_name,
                            agent_name,
                            display_name,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_agent_access_grants (
                          grant_id, company_id, agent_identity_id, scope_type, scope_id,
                          workspace_id, project_id, supersedes_token_id,
                          memory_transfer_from_token_id, status, created_at,
                          commons_only,
                          pending_expires_at, predecessor_token_id, activated_at,
                          cancelled_at, revoked_at, revoked_by_master_key_id
                        ) VALUES (?, ?, ?, 'project', ?, ?, ?, NULL, NULL, 'active', ?, 1, NULL, NULL, ?, NULL, NULL, NULL)
                        """,
                        (
                            grant_id,
                            scope["company_id"],
                            identity_id,
                            self.project_id,
                            self.workspace_id,
                            self.project_id,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_agent_tokens (
                          agent_token_id, grant_id, agent_identity_id, token_hash,
                          created_at, last_used_at, revoked_at
                        ) VALUES (?, ?, ?, ?, ?, NULL, NULL)
                        """,
                        (token_id, grant_id, identity_id, token_digest, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_agents (
                          agent_record_id, workspace_id, agent_id, display_name,
                          status, registered_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (
                            self.store._agent_record_id(self.workspace_id, agent_name),
                            self.workspace_id,
                            agent_name,
                            display_name,
                            now,
                            now,
                        ),
                    )
                    profile_id = storage_module._id("commonsprofile")
                    connection.execute(
                        """
                        INSERT INTO matm_commons_agent_profiles (
                          profile_id, workspace_id, project_id, agent_identity_id,
                          agent_token_id, agent_id, display_name, listed,
                          implementation, capabilities_json, profile_url,
                          capability_url, availability, credential_expires_at,
                          status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL)
                        """,
                        (
                            profile_id,
                            self.workspace_id,
                            self.project_id,
                            identity_id,
                            token_id,
                            agent_name,
                            display_name,
                            1 if profile.get("listed") else 0,
                            profile.get("implementation") or "",
                            _json(list(profile.get("capabilities") or [])),
                            profile.get("profileUrl") or "",
                            profile.get("capabilityUrl") or "",
                            profile.get("availability") or "",
                            expires_at,
                            now,
                        ),
                    )
                    self._ensure_room_sql(connection)
                    self._record_sql_idempotency(
                        connection,
                        "anonymous-enrollment",
                        "enroll",
                        key,
                        request_digest,
                        "agent",
                        token_id,
                        201,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.agent.enroll",
                        agent_name,
                        identity_id,
                        {
                            "projectId": self.project_id,
                            "listed": bool(profile.get("listed")),
                            "credentialExpiresAt": expires_at,
                        },
                    )
                    profile_record = self._profile_from_sql(
                        self._profile_sql(connection, agent_name)
                    )
                    return self._enrollment_result(
                        profile_record, True, token_id
                    ), False

    def current_enrollment(self, auth):
        if (auth or {}).get("authType") != "commons_enrollment_candidate":
            raise CommonsContractError(
                "commons_enrollment_candidate_required", "401 Unauthorized"
            )
        request_id = str((auth or {}).get("enrollmentRequestId") or "")
        if self.sql:
            with self.store._open_connection() as connection:
                scope = self._scope_sql(connection)
                row = connection.execute(
                    "SELECT * FROM matm_commons_enrollment_requests WHERE "
                    "workspace_id = ? AND project_id = ? AND company_id = ? "
                    "AND enrollment_request_id = ?",
                    (
                        self.workspace_id,
                        self.project_id,
                        scope["company_id"],
                        request_id,
                    ),
                ).fetchone()
                request = self._enrollment_request_from_sql(row)
                profile = (
                    self._profile_from_sql(
                        self._profile_sql(connection, request.get("agentName"))
                    )
                    if request and request.get("status") == "approved"
                    else None
                )
                active = bool(
                    profile
                    and self._profile_sql(
                        connection, request.get("agentName"), active_only=True
                    )
                )
        else:
            data = self.store._load()
            _workspace, _project, company = self._scope_file(data)
            request = data.get("commonsEnrollmentRequests", {}).get(request_id)
            if request and (
                request.get("workspaceId") != self.workspace_id
                or request.get("projectId") != self.project_id
                or request.get("companyId") != company.get("companyId")
            ):
                request = None
            profile = (
                self._profile_file(data, request.get("agentName"))
                if request and request.get("status") == "approved"
                else None
            )
            active = self._profile_active_file(data, profile)
        if not request:
            raise CommonsContractError(
                "commons_enrollment_candidate_invalid", "401 Unauthorized"
            )
        return self._public_enrollment_request(request, profile, active)

    def _assert_company_master_scope(self, auth, company_id):
        if (
            (auth or {}).get("credentialType") != "company_master"
            or (auth or {}).get("companyId") != company_id
        ):
            raise CommonsContractError("company_master_required", "403 Forbidden")
        return _credential_reference(auth)

    def _assert_bound_company_master_file(self, data, auth, company_id):
        principal_id = self._assert_company_master_scope(auth, company_id)
        record = data.get("companyMasterKeys", {}).get(principal_id)
        if (
            not record
            or record.get("companyId") != company_id
            or record.get("revokedAt")
        ):
            raise CommonsContractError("company_master_required", "403 Forbidden")
        return principal_id

    def _assert_bound_company_master_sql(self, connection, auth, company_id):
        principal_id = self._assert_company_master_scope(auth, company_id)
        row = connection.execute(
            "SELECT master_key_id FROM matm_company_master_keys WHERE "
            "master_key_id = ? AND company_id = ? AND revoked_at IS NULL",
            (principal_id, company_id),
        ).fetchone()
        if not row:
            raise CommonsContractError("company_master_required", "403 Forbidden")
        return principal_id

    def enrollment_request(self, auth, request_id):
        if self.sql:
            with self.store._open_connection() as connection:
                scope = self._scope_sql(connection)
                self._assert_bound_company_master_sql(
                    connection, auth, scope["company_id"]
                )
                row = connection.execute(
                    "SELECT * FROM matm_commons_enrollment_requests WHERE "
                    "workspace_id = ? AND project_id = ? AND company_id = ? "
                    "AND enrollment_request_id = ?",
                    (
                        self.workspace_id,
                        self.project_id,
                        scope["company_id"],
                        request_id,
                    ),
                ).fetchone()
                request = self._enrollment_request_from_sql(row)
                profile = (
                    self._profile_from_sql(
                        self._profile_sql(connection, request.get("agentName"))
                    )
                    if request and request.get("status") == "approved"
                    else None
                )
                active = bool(
                    profile
                    and self._profile_sql(
                        connection, request.get("agentName"), active_only=True
                    )
                )
        else:
            data = self.store._load()
            _workspace, _project, company = self._scope_file(data)
            self._assert_bound_company_master_file(
                data, auth, company.get("companyId")
            )
            request = data.get("commonsEnrollmentRequests", {}).get(request_id)
            if request and (
                request.get("workspaceId") != self.workspace_id
                or request.get("projectId") != self.project_id
                or request.get("companyId") != company.get("companyId")
            ):
                request = None
            profile = (
                self._profile_file(data, request.get("agentName"))
                if request and request.get("status") == "approved"
                else None
            )
            active = self._profile_active_file(data, profile)
        if not request:
            raise CommonsContractError("enrollment_request_not_found", "404 Not Found")
        return self._public_enrollment_request(request, profile, active)

    def enrollment_requests(self, auth, after=None, limit=50):
        context = "\n".join((self.workspace_id, self.project_id, "enrollments"))
        anchor = decode_enrollment_cursor(
            after, storage_module._credential_pepper(), context
        )
        limit = int(limit)
        if self.sql:
            with self.store._open_connection() as connection:
                scope = self._scope_sql(connection)
                self._assert_bound_company_master_sql(
                    connection, auth, scope["company_id"]
                )
                params = [self.workspace_id, self.project_id, scope["company_id"]]
                clause = ""
                if anchor:
                    anchor_row = connection.execute(
                        "SELECT enrollment_request_id FROM matm_commons_enrollment_requests "
                        "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
                        "AND created_at = ? AND enrollment_request_id = ?",
                        (
                            self.workspace_id,
                            self.project_id,
                            scope["company_id"],
                            anchor[0],
                            anchor[1],
                        ),
                    ).fetchone()
                    if not anchor_row:
                        raise CommonsContractError("cursor_invalid")
                    clause = (
                        " AND (created_at > ? OR (created_at = ? "
                        "AND enrollment_request_id > ?))"
                    )
                    params.extend((anchor[0], anchor[0], anchor[1]))
                params.append(limit + 1)
                rows = connection.execute(
                    "SELECT * FROM matm_commons_enrollment_requests WHERE "
                    "workspace_id = ? AND project_id = ? AND company_id = ?"
                    + clause
                    + " ORDER BY created_at, enrollment_request_id LIMIT ?",
                    tuple(params),
                ).fetchall()
                requests = [self._enrollment_request_from_sql(row) for row in rows]
                projected = []
                for request in requests[:limit]:
                    profile = (
                        self._profile_from_sql(
                            self._profile_sql(
                                connection, request.get("agentName")
                            )
                        )
                        if request.get("status") == "approved"
                        else None
                    )
                    active = bool(
                        profile
                        and self._profile_sql(
                            connection,
                            request.get("agentName"),
                            active_only=True,
                        )
                    )
                    projected.append(
                        self._public_enrollment_request(request, profile, active)
                    )
        else:
            data = self.store._load()
            _workspace, _project, company = self._scope_file(data)
            self._assert_bound_company_master_file(
                data, auth, company.get("companyId")
            )
            scoped = sorted(
                [
                    item
                    for item in data.get("commonsEnrollmentRequests", {}).values()
                    if item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("companyId") == company.get("companyId")
                ],
                key=lambda item: (
                    item.get("createdAt") or "",
                    item.get("enrollmentRequestId") or "",
                ),
            )
            if anchor:
                if not any(
                    item.get("createdAt") == anchor[0]
                    and item.get("enrollmentRequestId") == anchor[1]
                    for item in scoped
                ):
                    raise CommonsContractError("cursor_invalid")
                scoped = [
                    item
                    for item in scoped
                    if (item.get("createdAt") or "", item.get("enrollmentRequestId") or "")
                    > anchor
                ]
            requests = scoped[: limit + 1]
            projected = []
            for request in requests[:limit]:
                profile = (
                    self._profile_file(data, request.get("agentName"))
                    if request.get("status") == "approved"
                    else None
                )
                projected.append(
                    self._public_enrollment_request(
                        request, profile, self._profile_active_file(data, profile)
                    )
                )
        has_more = len(requests) > limit
        requests = requests[:limit]
        items = projected
        next_cursor = (
            encode_enrollment_cursor(
                requests[-1].get("createdAt"),
                requests[-1].get("enrollmentRequestId"),
                storage_module._credential_pepper(),
                context,
            )
            if requests
            else None
        )
        return {
            "items": items,
            "count": len(items),
            "hasMore": bool(has_more),
            "nextCursor": next_cursor,
            "cursorOpaque": True,
            "cursorIntegrity": "hmac-sha256",
            "order": "createdAt_enrollmentRequestId_ascending",
        }

    def _activate_enrollment_file(self, data, request, now, company_id):
        if request.get("companyId") != company_id:
            raise CommonsContractError(
                "enrollment_request_not_found", "404 Not Found"
            )
        agent_name = request.get("agentName")
        if self._profile_file(data, agent_name) or any(
            item.get("companyId") == company_id
            and item.get("agentNameNormalized") == agent_name
            for item in data.get("agentIdentities", {}).values()
        ):
            raise CommonsContractError(
                "enrollment_decision_conflict", "409 Conflict"
            )
        identity_id = storage_module._id("agentidentity")
        grant_id = storage_module._id("grant")
        token_id = request.get("candidateTokenId")
        expires_at = credential_expiry(self.settings.get("credentialTtlSeconds"))
        data.setdefault("agentIdentities", {})[identity_id] = {
            "agentIdentityId": identity_id,
            "companyId": company_id,
            "agentId": agent_name,
            "agentName": agent_name,
            "agentNameNormalized": agent_name,
            "displayName": request.get("displayName"),
            "status": "active",
            "createdAt": now,
            "updatedAt": None,
        }
        data.setdefault("agentAccessGrants", {})[grant_id] = {
            "grantId": grant_id,
            "companyId": company_id,
            "agentIdentityId": identity_id,
            "scopeType": "project",
            "scopeId": self.project_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "supersedesTokenId": None,
            "memoryTransferFromTokenId": None,
            "commonsOnly": True,
            "status": "active",
            "createdAt": now,
            "pendingExpiresAt": None,
            "predecessorTokenId": None,
            "activatedAt": now,
            "cancelledAt": None,
            "revokedAt": None,
            "revokedByMasterKeyId": None,
        }
        data.setdefault("agentTokens", {})[token_id] = {
            "agentTokenId": token_id,
            "grantId": grant_id,
            "agentIdentityId": identity_id,
            "tokenHash": request.get("candidateTokenHash"),
            "createdAt": now,
            "lastUsedAt": None,
            "revokedAt": None,
        }
        data.setdefault("agents", {})["%s:%s" % (self.workspace_id, agent_name)] = {
            "workspaceId": self.workspace_id,
            "agentId": agent_name,
            "displayName": request.get("displayName"),
            "registeredAt": now,
            "status": "active",
        }
        profile_id = storage_module._id("commonsprofile")
        profile = {
            "profileId": profile_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentIdentityId": identity_id,
            "agentTokenId": token_id,
            "agentId": agent_name,
            "displayName": request.get("displayName"),
            "listed": bool(request.get("listed")),
            "implementation": request.get("implementation") or "",
            "capabilities": list(request.get("capabilities") or []),
            "profileUrl": request.get("profileUrl") or "",
            "capabilityUrl": request.get("capabilityUrl") or "",
            "availability": request.get("availability") or "",
            "credentialExpiresAt": expires_at,
            "status": "active",
            "createdAt": now,
            "updatedAt": None,
        }
        data.setdefault("commonsAgentProfiles", {})[
            "%s:%s" % (self.project_id, agent_name)
        ] = profile
        self._ensure_room_file(data)
        return profile

    def decide_enrollment(
        self, auth, request_id, decision, expected_revision, key, request_digest
    ):
        if decision not in ("approved", "denied"):
            raise CommonsContractError("enrollment_decision_invalid")
        if self.sql:
            return self._decide_enrollment_sql(
                auth,
                request_id,
                decision,
                expected_revision,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            _workspace, _project, company = self._scope_file(data)
            principal_id = self._assert_bound_company_master_file(
                data, auth, company.get("companyId")
            )
            record_key, replay = self._file_idempotency(
                data,
                principal_id,
                "enrollment-" + decision,
                key,
                request_digest,
            )
            request = data.get("commonsEnrollmentRequests", {}).get(request_id)
            if not request or (
                request.get("workspaceId") != self.workspace_id
                or request.get("projectId") != self.project_id
                or request.get("companyId") != company.get("companyId")
            ):
                raise CommonsContractError("enrollment_request_not_found", "404 Not Found")
            if replay:
                if replay.get("resultId") != request_id:
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._public_enrollment_request(
                    request,
                    self._profile_file(data, request.get("agentName")),
                    self._profile_active_file(
                        data, self._profile_file(data, request.get("agentName"))
                    ),
                ), True
            if self._effective_enrollment_status(request) == "expired":
                raise CommonsContractError("enrollment_request_expired", "409 Conflict")
            if request.get("status") != "pending":
                raise CommonsContractError("enrollment_decision_conflict", "409 Conflict")
            if int(request.get("revision") or 1) != int(expected_revision):
                raise CommonsContractError("revision_conflict", "409 Conflict")
            profile = None
            now = _iso_now()
            if decision == "approved":
                if any(
                    item.get("companyId") == company.get("companyId")
                    and item.get("agentNameNormalized") == request.get("agentName")
                    for item in data.get("agentIdentities", {}).values()
                ) or self._profile_file(
                    data, request.get("agentName")
                ) or request.get("candidateTokenId") in data.get("agentTokens", {}):
                    raise CommonsContractError(
                        "enrollment_decision_conflict", "409 Conflict"
                    )
                self._active_capacity_file(data, company.get("companyId"))
                profile = self._activate_enrollment_file(
                    data, request, now, company.get("companyId")
                )
                request["activatedAgentIdentityId"] = profile.get("agentIdentityId")
                request["activatedProfileId"] = profile.get("profileId")
            request.update(
                {
                    "status": decision,
                    "revision": int(request.get("revision") or 1) + 1,
                    "decidedAt": now,
                    "decidedByCredentialId": principal_id,
                }
            )
            self._record_file_idempotency(
                data,
                record_key,
                principal_id,
                "enrollment-" + decision,
                key,
                request_digest,
                "enrollment_request",
                request_id,
                200,
            )
            self.store.audit(
                data,
                "commons.enrollment." + decision,
                principal_id,
                request_id,
                self.workspace_id,
                {"projectId": self.project_id, "revision": request["revision"]},
            )
            self.store._save(data)
            return self._public_enrollment_request(
                request, profile, bool(profile)
            ), False

    def _activate_enrollment_sql(self, connection, request, now, company_id):
        if request.get("companyId") != company_id:
            raise CommonsContractError(
                "enrollment_request_not_found", "404 Not Found"
            )
        identity_id = storage_module._id("agentidentity")
        grant_id = storage_module._id("grant")
        profile_id = storage_module._id("commonsprofile")
        agent_name = request.get("agentName")
        if connection.execute(
            "SELECT agent_identity_id FROM matm_agent_identities WHERE "
            "company_id = ? AND agent_name_normalized = ?",
            (company_id, agent_name),
        ).fetchone() or connection.execute(
            "SELECT profile_id FROM matm_commons_agent_profiles WHERE "
            "workspace_id = ? AND project_id = ? AND agent_id = ?",
            (self.workspace_id, self.project_id, agent_name),
        ).fetchone():
            raise CommonsContractError(
                "enrollment_decision_conflict", "409 Conflict"
            )
        token_id = request.get("candidateTokenId")
        expires_at = credential_expiry(self.settings.get("credentialTtlSeconds"))
        connection.execute(
            """
            INSERT INTO matm_agent_identities (
              agent_identity_id, company_id, agent_id, agent_name,
              agent_name_normalized, display_name, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, NULL)
            """,
            (
                identity_id,
                company_id,
                agent_name,
                agent_name,
                agent_name,
                request.get("displayName"),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO matm_agent_access_grants (
              grant_id, company_id, agent_identity_id, scope_type, scope_id,
              workspace_id, project_id, supersedes_token_id,
              memory_transfer_from_token_id, status, created_at, commons_only,
              pending_expires_at, predecessor_token_id, activated_at,
              cancelled_at, revoked_at, revoked_by_master_key_id
            ) VALUES (?, ?, ?, 'project', ?, ?, ?, NULL, NULL, 'active', ?, 1, NULL, NULL, ?, NULL, NULL, NULL)
            """,
            (
                grant_id,
                company_id,
                identity_id,
                self.project_id,
                self.workspace_id,
                self.project_id,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO matm_agent_tokens (agent_token_id, grant_id, "
            "agent_identity_id, token_hash, created_at, last_used_at, revoked_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (
                token_id,
                grant_id,
                identity_id,
                request.get("candidateTokenHash"),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO matm_agents (
              agent_record_id, workspace_id, agent_id, display_name,
              status, registered_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                self.store._agent_record_id(self.workspace_id, agent_name),
                self.workspace_id,
                agent_name,
                request.get("displayName"),
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO matm_commons_agent_profiles (
              profile_id, workspace_id, project_id, agent_identity_id,
              agent_token_id, agent_id, display_name, listed,
              implementation, capabilities_json, profile_url,
              capability_url, availability, credential_expires_at,
              status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL)
            """,
            (
                profile_id,
                self.workspace_id,
                self.project_id,
                identity_id,
                token_id,
                agent_name,
                request.get("displayName"),
                1 if request.get("listed") else 0,
                request.get("implementation") or "",
                _json(list(request.get("capabilities") or [])),
                request.get("profileUrl") or "",
                request.get("capabilityUrl") or "",
                request.get("availability") or "",
                expires_at,
                now,
            ),
        )
        self._ensure_room_sql(connection)
        return self._profile_from_sql(self._profile_sql(connection, agent_name))

    def _decide_enrollment_sql(
        self, auth, request_id, decision, expected_revision, key, request_digest
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    scope = self._scope_sql(connection, lock=True)
                    principal_id = self._assert_bound_company_master_sql(
                        connection, auth, scope["company_id"]
                    )
                    replay = self._sql_idempotency(
                        connection,
                        principal_id,
                        "enrollment-" + decision,
                        key,
                        request_digest,
                    )
                    query = (
                        "SELECT * FROM matm_commons_enrollment_requests WHERE "
                        "workspace_id = ? AND project_id = ? AND company_id = ? "
                        "AND enrollment_request_id = ?"
                    )
                    if getattr(connection, "dialect", "sqlite") == "mysql":
                        query += " FOR UPDATE"
                    row = connection.execute(
                        query,
                        (
                            self.workspace_id,
                            self.project_id,
                            scope["company_id"],
                            request_id,
                        ),
                    ).fetchone()
                    request = self._enrollment_request_from_sql(row)
                    if not request:
                        raise CommonsContractError(
                            "enrollment_request_not_found", "404 Not Found"
                        )
                    profile = (
                        self._profile_from_sql(
                            self._profile_sql(connection, request.get("agentName"))
                        )
                        if request.get("status") == "approved"
                        else None
                    )
                    if replay:
                        if replay["result_id"] != request_id:
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        active = bool(
                            profile
                            and self._profile_sql(
                                connection,
                                request.get("agentName"),
                                active_only=True,
                            )
                        )
                        return self._public_enrollment_request(
                            request, profile, active
                        ), True
                    if self._effective_enrollment_status(request) == "expired":
                        raise CommonsContractError(
                            "enrollment_request_expired", "409 Conflict"
                        )
                    if request.get("status") != "pending":
                        raise CommonsContractError(
                            "enrollment_decision_conflict", "409 Conflict"
                        )
                    if int(request.get("revision") or 1) != int(expected_revision):
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    now = _iso_now()
                    if decision == "approved":
                        if connection.execute(
                            "SELECT agent_identity_id FROM matm_agent_identities "
                            "WHERE company_id = ? AND agent_name_normalized = ?",
                            (scope["company_id"], request.get("agentName")),
                        ).fetchone() or connection.execute(
                            "SELECT profile_id FROM matm_commons_agent_profiles WHERE "
                            "workspace_id = ? AND project_id = ? AND agent_id = ?",
                            (
                                self.workspace_id,
                                self.project_id,
                                request.get("agentName"),
                            ),
                        ).fetchone() or connection.execute(
                            "SELECT agent_token_id FROM matm_agent_tokens WHERE "
                            "agent_token_id = ? OR token_hash = ?",
                            (
                                request.get("candidateTokenId"),
                                request.get("candidateTokenHash"),
                            ),
                        ).fetchone():
                            raise CommonsContractError(
                                "enrollment_decision_conflict", "409 Conflict"
                            )
                        self._active_capacity_sql(connection, scope["company_id"])
                        try:
                            profile = self._activate_enrollment_sql(
                                connection, request, now, scope["company_id"]
                            )
                        except Exception as exc:
                            if storage_module._is_sql_duplicate_key_conflict(exc):
                                raise CommonsContractError(
                                    "enrollment_decision_conflict", "409 Conflict"
                                )
                            raise
                    next_revision = int(request.get("revision") or 1) + 1
                    changed = connection.execute(
                        "UPDATE matm_commons_enrollment_requests SET status = ?, "
                        "revision = ?, decided_at = ?, decided_by_credential_id = ?, "
                        "activated_agent_identity_id = ?, activated_profile_id = ? "
                        "WHERE workspace_id = ? AND project_id = ? AND company_id = ? "
                        "AND enrollment_request_id = ? AND status = 'pending' AND revision = ?",
                        (
                            decision,
                            next_revision,
                            now,
                            principal_id,
                            (profile or {}).get("agentIdentityId"),
                            (profile or {}).get("profileId"),
                            self.workspace_id,
                            self.project_id,
                            scope["company_id"],
                            request_id,
                            int(expected_revision),
                        ),
                    )
                    if changed.rowcount != 1:
                        raise CommonsContractError(
                            "enrollment_decision_conflict", "409 Conflict"
                        )
                    self._record_sql_idempotency(
                        connection,
                        principal_id,
                        "enrollment-" + decision,
                        key,
                        request_digest,
                        "enrollment_request",
                        request_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.enrollment." + decision,
                        principal_id,
                        request_id,
                        {"projectId": self.project_id, "revision": next_revision},
                    )
                    row = connection.execute(
                        "SELECT * FROM matm_commons_enrollment_requests WHERE "
                        "workspace_id = ? AND project_id = ? AND company_id = ? "
                        "AND enrollment_request_id = ?",
                        (
                            self.workspace_id,
                            self.project_id,
                            scope["company_id"],
                            request_id,
                        ),
                    ).fetchone()
                    request = self._enrollment_request_from_sql(row)
                    return self._public_enrollment_request(
                        request, profile, bool(profile)
                    ), False

    def agent_profile(self, agent_id, public_only=True):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                row = self._profile_sql(connection, agent_id, active_only=True)
                profile = self._profile_from_sql(row)
                if not profile or (public_only and not profile.get("listed")):
                    return None
                return public_agent(profile, active=True)
        data = self.store._load()
        self._scope_file(data)
        profile = self._profile_file(data, agent_id)
        if (
            not self._profile_active_file(data, profile)
            or (public_only and not profile.get("listed"))
        ):
            return None
        return public_agent(profile, active=True)

    def agents(self, after=None, limit=50):
        context = "\n".join((self.workspace_id, self.project_id, "agents"))
        anchor = decode_agent_cursor(
            after, storage_module._credential_pepper(), context
        )
        limit = int(limit)
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                clause = " AND p.agent_id > ?" if anchor else ""
                params = [self.workspace_id, self.project_id, _iso_now()]
                if anchor:
                    params.append(anchor)
                params.append(limit + 1)
                rows = connection.execute(
                    """
                    SELECT p.*
                    FROM matm_commons_agent_profiles p
                    JOIN matm_agent_identities i ON i.agent_identity_id = p.agent_identity_id
                    JOIN matm_agent_tokens t ON t.agent_token_id = p.agent_token_id
                      AND t.agent_identity_id = p.agent_identity_id
                    JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id
                      AND g.agent_identity_id = p.agent_identity_id
                    JOIN matm_workspaces w ON w.workspace_id = p.workspace_id
                      AND w.company_id = g.company_id AND w.company_id = i.company_id
                    JOIN matm_projects pr ON pr.project_id = p.project_id
                      AND pr.workspace_id = p.workspace_id
                      AND g.project_id = pr.project_id AND g.workspace_id = pr.workspace_id
                    JOIN matm_companies c ON c.company_id = w.company_id
                    WHERE p.workspace_id = ? AND p.project_id = ? AND p.listed = 1
                      AND p.status = 'active' AND p.credential_expires_at > ?
                      AND i.agent_id = p.agent_id AND i.status = 'active'
                      AND t.revoked_at IS NULL AND g.scope_type = 'project'
                      AND g.scope_id = p.project_id AND g.commons_only = 1
                      AND g.status = 'active' AND g.revoked_at IS NULL
                      AND c.status = 'active'
                    """
                    + clause
                    + " ORDER BY p.agent_id LIMIT ?",
                    tuple(params),
                ).fetchall()
                profiles = [self._profile_from_sql(row) for row in rows]
        else:
            data = self.store._load()
            self._scope_file(data)
            profiles = sorted(
                [
                    profile
                    for profile in data.get("commonsAgentProfiles", {}).values()
                    if profile.get("workspaceId") == self.workspace_id
                    and profile.get("projectId") == self.project_id
                    and profile.get("listed")
                    and self._profile_active_file(data, profile)
                    and (not anchor or profile.get("agentId") > anchor)
                ],
                key=lambda item: item.get("agentId") or "",
            )[: limit + 1]
        has_more = len(profiles) > limit
        profiles = profiles[:limit]
        items = [public_agent(profile, active=True) for profile in profiles]
        next_cursor = (
            encode_agent_cursor(
                profiles[-1].get("agentId"),
                storage_module._credential_pepper(),
                context,
            )
            if profiles
            else None
        )
        return {
            "items": items,
            "count": len(items),
            "hasMore": bool(has_more),
            "nextCursor": next_cursor,
            "cursorOpaque": True,
            "cursorIntegrity": "hmac-sha256",
            "order": "agentId_ascending",
        }

    def _agent_binding(self, auth):
        if (
            (auth or {}).get("credentialType") != "agent"
            or (auth or {}).get("workspaceId") != self.workspace_id
            or (auth or {}).get("projectId") != self.project_id
            or (auth or {}).get("scopeType") != "project"
            or (auth or {}).get("scopeId") != self.project_id
            or not (auth or {}).get("companyId")
            or not (auth or {}).get("agentId")
            or not (auth or {}).get("commonsOnly")
        ):
            raise CommonsContractError(
                "commons_agent_credential_required",
                "403 Forbidden",
                "An active agent credential with the exact configured project grant is required.",
            )
        return str(auth.get("agentId")), str(auth.get("agentTokenId") or "")

    def _assert_bound_agent_file(self, data, auth):
        agent_id, token_id = self._agent_binding(auth)
        profile = self._profile_file(data, agent_id)
        token = data.get("agentTokens", {}).get(token_id)
        grant = data.get("agentAccessGrants", {}).get((token or {}).get("grantId"))
        identity = data.get("agentIdentities", {}).get(
            (profile or {}).get("agentIdentityId")
        )
        if (
            not token_id
            or not self._profile_active_file(data, profile)
            or profile.get("agentTokenId") != token_id
            or (auth or {}).get("companyId") != (identity or {}).get("companyId")
            or (
                (auth or {}).get("authType") == "agent"
                and (
                    (auth or {}).get("agentIdentityId")
                    != (profile or {}).get("agentIdentityId")
                )
            )
        ):
            raise CommonsContractError(
                "commons_agent_credential_inactive",
                "401 Unauthorized",
                "The Commons credential is revoked, expired, or inactive.",
            )
        return agent_id

    def _assert_bound_agent_sql(self, connection, auth):
        agent_id, token_id = self._agent_binding(auth)
        scope = self._scope_sql(connection)
        profile = self._profile_from_sql(
            self._profile_sql(connection, agent_id, active_only=True)
        )
        if (
            not token_id
            or not profile
            or profile.get("agentTokenId") != token_id
            or (auth or {}).get("companyId") != scope["company_id"]
            or (
                (auth or {}).get("authType") == "agent"
                and (auth or {}).get("agentIdentityId")
                != profile.get("agentIdentityId")
            )
        ):
            raise CommonsContractError(
                "commons_agent_credential_inactive",
                "401 Unauthorized",
                "The Commons credential is revoked, expired, or inactive.",
            )
        return agent_id

    def assert_active_agent(self, auth):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                return self._assert_bound_agent_sql(connection, auth)
        else:
            data = self.store._load()
            self._scope_file(data)
            return self._assert_bound_agent_file(data, auth)

    def _room_from_sql(self, row):
        if not row:
            return None
        return {
            "roomId": row["room_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "name": row["name"],
            "description": row["description"],
            "visibility": row["visibility"],
            "membershipRequired": bool(row["membership_required"]),
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _membership_from_sql(self, row):
        if not row:
            return None
        return {
            "membershipId": row["membership_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "roomId": row["room_id"],
            "agentId": row["agent_id"],
            "state": row["state"],
            "revision": int(row["revision"] or 0),
            "joinedAt": row["joined_at"],
            "leftAt": row["left_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _public_membership(membership):
        if not membership:
            return {"state": "not_joined", "revision": 0}
        return {
            "state": membership.get("state"),
            "revision": int(membership.get("revision") or 0),
            "joinedAt": membership.get("joinedAt"),
            "leftAt": membership.get("leftAt"),
            "updatedAt": membership.get("updatedAt"),
        }

    def _membership_file(self, data, room_id, agent_id):
        return data.get("commonsMemberships", {}).get("%s:%s" % (room_id, agent_id))

    def _room_projection_file(self, data, room, viewer_agent_id=None):
        memberships = [
            item
            for item in data.get("commonsMemberships", {}).values()
            if item.get("roomId") == room.get("roomId") and item.get("state") == "joined"
        ]
        messages = [
            item
            for item in data.get("commonsMessages", {}).values()
            if item.get("roomId") == room.get("roomId")
        ]
        recent = max((item.get("createdAt") or "" for item in messages), default="") or None
        membership = None
        if viewer_agent_id:
            membership = self._public_membership(
                self._membership_file(data, room.get("roomId"), viewer_agent_id)
            )
        return public_room(room, len(memberships), recent, membership)

    def _room_projection_sql(self, connection, room, viewer_agent_id=None):
        participant = connection.execute(
            "SELECT COUNT(*) AS count FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND state = 'joined'",
            (self.workspace_id, self.project_id, room.get("roomId")),
        ).fetchone()
        recent = connection.execute(
            "SELECT MAX(created_at) AS recent_at FROM matm_commons_messages WHERE workspace_id = ? AND project_id = ? AND room_id = ?",
            (self.workspace_id, self.project_id, room.get("roomId")),
        ).fetchone()
        membership = None
        if viewer_agent_id:
            membership_row = connection.execute(
                "SELECT * FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND agent_id = ?",
                (self.workspace_id, self.project_id, room.get("roomId"), viewer_agent_id),
            ).fetchone()
            membership = self._public_membership(
                self._membership_from_sql(membership_row)
            )
        return public_room(
            room,
            int((participant or {}).get("count", 0) if isinstance(participant, dict) else participant["count"]),
            recent["recent_at"] if recent else None,
            membership,
        )

    def rooms(self, viewer_agent_id=None):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                row = connection.execute(
                    "SELECT * FROM matm_commons_rooms WHERE room_id = ? AND workspace_id = ? AND project_id = ? AND status = 'active'",
                    (self.room_id, self.workspace_id, self.project_id),
                ).fetchone()
                room = self._room_from_sql(row) if row else self._canonical_room(None)
                return [self._room_projection_sql(connection, room, viewer_agent_id)]
        data = self.store._load()
        self._scope_file(data)
        room = data.get("commonsRooms", {}).get(self.room_id) or self._canonical_room(None)
        return [self._room_projection_file(data, room, viewer_agent_id)]

    def room(self, room_id, viewer_agent_id=None):
        if room_id != self.room_id:
            return None
        return self.rooms(viewer_agent_id)[0]

    def membership(self, room_id, agent_id):
        if room_id != self.room_id:
            return None
        if self.sql:
            with self.store._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND agent_id = ?",
                    (self.workspace_id, self.project_id, room_id, agent_id),
                ).fetchone()
                return self._membership_from_sql(row)
        return self._membership_file(self.store._load(), room_id, agent_id)

    def _require_joined_file(self, data, room_id, agent_id):
        membership = self._membership_file(data, room_id, agent_id)
        if not membership or membership.get("state") != "joined":
            raise CommonsContractError(
                "room_membership_required",
                "403 Forbidden",
                "The authenticated agent must explicitly join this room before writing.",
            )
        return membership

    def _require_joined_sql(self, connection, room_id, agent_id):
        row = connection.execute(
            "SELECT * FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND agent_id = ? AND state = 'joined'",
            (self.workspace_id, self.project_id, room_id, agent_id),
        ).fetchone()
        if not row:
            raise CommonsContractError(
                "room_membership_required",
                "403 Forbidden",
                "The authenticated agent must explicitly join this room before writing.",
            )
        return self._membership_from_sql(row)

    def set_membership(self, room_id, auth, desired_state, key, request_digest):
        if room_id != self.room_id:
            raise CommonsContractError("room_not_found", "404 Not Found")
        if desired_state not in ("joined", "left"):
            raise CommonsContractError("membership_state_invalid")
        operation = "room-join" if desired_state == "joined" else "room-leave"
        if self.sql:
            return self._set_membership_sql(
                room_id, auth, desired_state, operation, key, request_digest
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            agent_id = self._assert_bound_agent_file(data, auth)
            room = self._ensure_room_file(data)
            record_key, replay = self._file_idempotency(
                data, agent_id, operation, key, request_digest
            )
            existing = self._membership_file(data, room_id, agent_id)
            if replay:
                if (
                    not existing
                    or replay.get("resultId") != existing.get("membershipId")
                ):
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._public_membership(existing), self._room_projection_file(data, room, agent_id), True
            now = _iso_now()
            if existing:
                existing["revision"] = int(existing.get("revision") or 0) + 1
                existing["state"] = desired_state
                existing["updatedAt"] = now
                if desired_state == "joined":
                    existing["joinedAt"] = now
                    existing["leftAt"] = None
                else:
                    existing["leftAt"] = now
            else:
                existing = {
                    "membershipId": storage_module._id("commonsmembership"),
                    "workspaceId": self.workspace_id,
                    "projectId": self.project_id,
                    "roomId": room_id,
                    "agentId": agent_id,
                    "state": desired_state,
                    "revision": 1,
                    "joinedAt": now if desired_state == "joined" else None,
                    "leftAt": now if desired_state == "left" else None,
                    "createdAt": now,
                    "updatedAt": now,
                }
                data.setdefault("commonsMemberships", {})[
                    "%s:%s" % (room_id, agent_id)
                ] = existing
            self._record_file_idempotency(
                data,
                record_key,
                agent_id,
                operation,
                key,
                request_digest,
                "membership",
                existing["membershipId"],
                200,
            )
            self.store.audit(
                data,
                "commons.membership.%s" % desired_state,
                agent_id,
                room_id,
                self.workspace_id,
                {"projectId": self.project_id, "revision": existing["revision"]},
            )
            self.store._save(data)
            return self._public_membership(existing), self._room_projection_file(data, room, agent_id), False

    def _set_membership_sql(
        self, room_id, auth, desired_state, operation, key, request_digest
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    agent_id = self._assert_bound_agent_sql(connection, auth)
                    room = self._room_from_sql(self._ensure_room_sql(connection))
                    replay = self._sql_idempotency(
                        connection, agent_id, operation, key, request_digest
                    )
                    row = connection.execute(
                        "SELECT * FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND agent_id = ?",
                        (self.workspace_id, self.project_id, room_id, agent_id),
                    ).fetchone()
                    membership = self._membership_from_sql(row)
                    if replay:
                        if (
                            not membership
                            or replay["result_id"] != membership.get("membershipId")
                        ):
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._public_membership(membership), self._room_projection_sql(connection, room, agent_id), True
                    now = _iso_now()
                    if membership:
                        next_revision = int(membership["revision"]) + 1
                        connection.execute(
                            """
                            UPDATE matm_commons_memberships
                            SET state = ?, revision = ?, joined_at = ?, left_at = ?, updated_at = ?
                            WHERE membership_id = ?
                            """,
                            (
                                desired_state,
                                next_revision,
                                now if desired_state == "joined" else membership.get("joinedAt"),
                                now if desired_state == "left" else None,
                                now,
                                membership["membershipId"],
                            ),
                        )
                    else:
                        membership_id = storage_module._id("commonsmembership")
                        connection.execute(
                            """
                            INSERT INTO matm_commons_memberships (
                              membership_id, workspace_id, project_id, room_id, agent_id,
                              state, revision, joined_at, left_at, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                            """,
                            (
                                membership_id,
                                self.workspace_id,
                                self.project_id,
                                room_id,
                                agent_id,
                                desired_state,
                                now if desired_state == "joined" else None,
                                now if desired_state == "left" else None,
                                now,
                                now,
                            ),
                        )
                    row = connection.execute(
                        "SELECT * FROM matm_commons_memberships WHERE workspace_id = ? AND project_id = ? AND room_id = ? AND agent_id = ?",
                        (self.workspace_id, self.project_id, room_id, agent_id),
                    ).fetchone()
                    membership = self._membership_from_sql(row)
                    self._record_sql_idempotency(
                        connection,
                        agent_id,
                        operation,
                        key,
                        request_digest,
                        "membership",
                        membership["membershipId"],
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.membership.%s" % desired_state,
                        agent_id,
                        room_id,
                        {"projectId": self.project_id, "revision": membership["revision"]},
                    )
                    return self._public_membership(membership), self._room_projection_sql(connection, room, agent_id), False

    @staticmethod
    def _message_from_sql(row):
        if not row:
            return None
        return {
            "messageId": row["message_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "roomId": row["room_id"],
            "authorAgentId": row["author_agent_id"],
            "replyToMessageId": row["reply_to_message_id"],
            "currentRevision": int(row["current_revision"] or 1),
            "currentRevisionId": row["current_revision_id"],
            "state": row["state"],
            "createdAt": row["created_at"],
            "correctedAt": row["corrected_at"],
            "withdrawnAt": row["withdrawn_at"],
        }

    @staticmethod
    def _revision_from_sql(row):
        if not row:
            return None
        return {
            "revisionId": row["revision_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "roomId": row["room_id"],
            "messageId": row["message_id"],
            "revisionNumber": int(row["revision_number"] or 0),
            "kind": row["kind"],
            "authorAgentId": row["author_agent_id"],
            "content": row["content"],
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _withdrawal_from_sql(row):
        if not row:
            return None
        return {
            "withdrawalId": row["withdrawal_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "roomId": row["room_id"],
            "messageId": row["message_id"],
            "withdrawnByAgentId": row["withdrawn_by_agent_id"],
            "revisionAtWithdrawal": int(row["revision_at_withdrawal"] or 0),
            "withdrawnAt": row["withdrawn_at"],
        }

    def _message_file(self, data, message_id):
        item = data.get("commonsMessages", {}).get(message_id)
        if (
            not item
            or item.get("workspaceId") != self.workspace_id
            or item.get("projectId") != self.project_id
        ):
            return None
        return item

    def _message_sql(self, connection, message_id, lock=False):
        sql = (
            "SELECT * FROM matm_commons_messages WHERE workspace_id = ? "
            "AND project_id = ? AND message_id = ?"
        )
        params = (self.workspace_id, self.project_id, message_id)
        row = (
            storage_module._connector_select_for_update(connection, sql, params)
            if lock
            else connection.execute(sql, params).fetchone()
        )
        return self._message_from_sql(row)

    def _history_file(self, data, message_id):
        return sorted(
            [
                item
                for item in data.get("commonsMessageRevisions", {}).values()
                if item.get("workspaceId") == self.workspace_id
                and item.get("projectId") == self.project_id
                and item.get("messageId") == message_id
            ],
            key=lambda item: int(item.get("revisionNumber") or 0),
        )

    def _history_sql(self, connection, message_id, include_content=True):
        columns = "*" if include_content else (
            "revision_id, workspace_id, project_id, room_id, message_id, "
            "revision_number, kind, author_agent_id, NULL AS content, created_at"
        )
        rows = connection.execute(
            "SELECT %s FROM matm_commons_message_revisions WHERE workspace_id = ? "
            "AND project_id = ? AND message_id = ? ORDER BY revision_number" % columns,
            (self.workspace_id, self.project_id, message_id),
        ).fetchall()
        return [self._revision_from_sql(row) for row in rows]

    def _withdrawal_file(self, data, message_id):
        return data.get("commonsWithdrawals", {}).get(message_id)

    def _withdrawal_sql(self, connection, message_id):
        row = connection.execute(
            "SELECT * FROM matm_commons_withdrawals WHERE workspace_id = ? "
            "AND project_id = ? AND message_id = ?",
            (self.workspace_id, self.project_id, message_id),
        ).fetchone()
        return self._withdrawal_from_sql(row)

    def _ack_file(self, data, message_id, agent_id):
        return data.get("commonsAcknowledgements", {}).get(
            "%s:%s" % (message_id, agent_id)
        )

    def _ack_sql(self, connection, message_id, agent_id):
        return connection.execute(
            "SELECT acknowledgement_id, acknowledged_revision, "
            "acknowledged_revision_id, acknowledged_state, "
            "acknowledged_withdrawal_id FROM matm_commons_acknowledgements "
            "WHERE workspace_id = ? AND project_id = ? AND message_id = ? AND agent_id = ?",
            (self.workspace_id, self.project_id, message_id, agent_id),
        ).fetchone()

    def _project_message_file(
        self, data, message, viewer_agent_id=None, include_history=True
    ):
        history = (
            self._history_file(data, message.get("messageId"))
            if include_history
            else []
        )
        withdrawal = self._withdrawal_file(data, message.get("messageId"))
        acknowledgement = (
            self._ack_file(data, message.get("messageId"), viewer_agent_id)
            if viewer_agent_id
            else None
        )
        revision = data.get("commonsMessageRevisions", {}).get(
            message.get("currentRevisionId")
        )
        binding = message_acknowledgement_binding(message, withdrawal)
        return public_message(
            message,
            revision,
            withdrawal,
            bool(
                acknowledgement
                and int(acknowledgement.get("acknowledgedRevision") or 0)
                == binding["expectedRevision"]
                and acknowledgement.get("acknowledgedRevisionId")
                == binding["expectedRevisionId"]
                and acknowledgement.get("acknowledgedState")
                == binding["expectedState"]
                and (acknowledgement.get("acknowledgedWithdrawalId") or None)
                == (binding["expectedWithdrawalId"] or None)
            ),
            history,
            include_history,
        )

    def _project_message_sql(
        self, connection, message, viewer_agent_id=None, include_history=True
    ):
        history = (
            self._history_sql(
                connection, message.get("messageId"), include_content=False
            )
            if include_history
            else []
        )
        withdrawal = self._withdrawal_sql(connection, message.get("messageId"))
        acknowledgement = (
            self._ack_sql(connection, message.get("messageId"), viewer_agent_id)
            if viewer_agent_id
            else None
        )
        revision = self._revision_from_sql(
            connection.execute(
                "SELECT * FROM matm_commons_message_revisions WHERE "
                "workspace_id = ? AND project_id = ? AND revision_id = ?",
                (
                    self.workspace_id,
                    self.project_id,
                    message.get("currentRevisionId"),
                ),
            ).fetchone()
        )
        binding = message_acknowledgement_binding(message, withdrawal)
        return public_message(
            message,
            revision,
            withdrawal,
            bool(
                acknowledgement
                and int(acknowledgement["acknowledged_revision"] or 0)
                == binding["expectedRevision"]
                and acknowledgement["acknowledged_revision_id"]
                == binding["expectedRevisionId"]
                and acknowledgement["acknowledged_state"]
                == binding["expectedState"]
                and (acknowledgement["acknowledged_withdrawal_id"] or None)
                == (binding["expectedWithdrawalId"] or None)
            ),
            history,
            include_history,
        )

    def _project_message_list_sql(self, connection, messages, viewer_agent_id=None):
        if not messages:
            return []
        message_ids = [item.get("messageId") for item in messages]
        revision_ids = [item.get("currentRevisionId") for item in messages]
        revision_marks = ",".join("?" for _item in revision_ids)
        message_marks = ",".join("?" for _item in message_ids)
        revisions = {
            row["revision_id"]: self._revision_from_sql(row)
            for row in connection.execute(
                "SELECT * FROM matm_commons_message_revisions WHERE "
                "workspace_id = ? AND project_id = ? AND revision_id IN (%s)"
                % revision_marks,
                tuple([self.workspace_id, self.project_id] + revision_ids),
            ).fetchall()
        }
        withdrawals = {
            row["message_id"]: self._withdrawal_from_sql(row)
            for row in connection.execute(
                "SELECT * FROM matm_commons_withdrawals WHERE workspace_id = ? "
                "AND project_id = ? AND message_id IN (%s)" % message_marks,
                tuple([self.workspace_id, self.project_id] + message_ids),
            ).fetchall()
        }
        acknowledgements = {}
        if viewer_agent_id:
            acknowledgements = {
                row["message_id"]: row
                for row in connection.execute(
                    "SELECT message_id, acknowledged_revision, "
                    "acknowledged_revision_id, acknowledged_state, "
                    "acknowledged_withdrawal_id FROM matm_commons_acknowledgements "
                    "WHERE workspace_id = ? AND project_id = ? AND agent_id = ? "
                    "AND message_id IN (%s)" % message_marks,
                    tuple(
                        [self.workspace_id, self.project_id, viewer_agent_id]
                        + message_ids
                    ),
                ).fetchall()
            }
        projected = []
        for message in messages:
            withdrawal = withdrawals.get(message.get("messageId"))
            binding = message_acknowledgement_binding(message, withdrawal)
            acknowledgement = acknowledgements.get(message.get("messageId"))
            acknowledged = bool(
                acknowledgement
                and int(acknowledgement["acknowledged_revision"] or 0)
                == binding["expectedRevision"]
                and acknowledgement["acknowledged_revision_id"]
                == binding["expectedRevisionId"]
                and acknowledgement["acknowledged_state"]
                == binding["expectedState"]
                and (acknowledgement["acknowledged_withdrawal_id"] or None)
                == (binding["expectedWithdrawalId"] or None)
            )
            projected.append(
                public_message(
                    message,
                    revisions.get(message.get("currentRevisionId")),
                    withdrawal,
                    acknowledged,
                    [],
                    False,
                )
            )
        return projected

    def _cursor_context(self, room_id):
        return "\n".join((self.workspace_id, self.project_id, room_id))

    def _validate_cursor_file(self, data, room_id, cursor):
        decoded = decode_cursor(
            cursor,
            storage_module._credential_pepper(),
            self._cursor_context(room_id),
        )
        if not decoded:
            return None
        anchor = self._message_file(data, decoded["messageId"])
        if (
            not anchor
            or anchor.get("roomId") != room_id
            or anchor.get("createdAt") != decoded["createdAt"]
        ):
            raise CommonsContractError(
                "cursor_invalid",
                detail="after is not an issued cursor for this Commons room.",
            )
        return decoded

    def _validate_cursor_sql(self, connection, room_id, cursor):
        decoded = decode_cursor(
            cursor,
            storage_module._credential_pepper(),
            self._cursor_context(room_id),
        )
        if not decoded:
            return None
        row = connection.execute(
            "SELECT message_id FROM matm_commons_messages WHERE workspace_id = ? "
            "AND project_id = ? AND room_id = ? AND message_id = ? AND created_at = ?",
            (
                self.workspace_id,
                self.project_id,
                room_id,
                decoded["messageId"],
                decoded["createdAt"],
            ),
        ).fetchone()
        if not row:
            raise CommonsContractError(
                "cursor_invalid",
                detail="after is not an issued cursor for this Commons room.",
            )
        return decoded

    def list_messages(self, room_id, after=None, limit=50, viewer_agent_id=None):
        if room_id != self.room_id:
            raise CommonsContractError("room_not_found", "404 Not Found")
        limit = int(limit)
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                cursor = self._validate_cursor_sql(connection, room_id, after)
                params = [self.workspace_id, self.project_id, room_id]
                clause = ""
                if cursor:
                    clause = (
                        " AND (created_at > ? OR (created_at = ? AND message_id > ?))"
                    )
                    params.extend(
                        [cursor["createdAt"], cursor["createdAt"], cursor["messageId"]]
                    )
                params.append(limit + 1)
                rows = connection.execute(
                    "SELECT * FROM matm_commons_messages WHERE workspace_id = ? "
                    "AND project_id = ? AND room_id = ?"
                    + clause
                    + " ORDER BY created_at, message_id LIMIT ?",
                    tuple(params),
                ).fetchall()
                messages = [self._message_from_sql(row) for row in rows]
                has_more = len(messages) > limit
                messages = messages[:limit]
                items = self._project_message_list_sql(
                    connection, messages, viewer_agent_id
                )
        else:
            data = self.store._load()
            self._scope_file(data)
            cursor = self._validate_cursor_file(data, room_id, after)
            messages = sorted(
                [
                    item
                    for item in data.get("commonsMessages", {}).values()
                    if item.get("workspaceId") == self.workspace_id
                    and item.get("projectId") == self.project_id
                    and item.get("roomId") == room_id
                    and (
                        not cursor
                        or (item.get("createdAt"), item.get("messageId"))
                        > (cursor["createdAt"], cursor["messageId"])
                    )
                ],
                key=lambda item: (item.get("createdAt") or "", item.get("messageId") or ""),
            )
            has_more = len(messages) > limit
            messages = messages[:limit]
            items = [
                self._project_message_file(
                    data, item, viewer_agent_id, include_history=False
                )
                for item in messages
            ]
        bounded_items = []
        encoded_bytes = 0
        for item in items:
            item_bytes = len(
                json.dumps(item, indent=2, sort_keys=True).encode("utf-8")
            )
            if bounded_items and encoded_bytes + item_bytes > 786432:
                has_more = True
                break
            bounded_items.append(item)
            encoded_bytes += item_bytes
        if len(bounded_items) < len(items):
            messages = messages[: len(bounded_items)]
        items = bounded_items
        next_cursor = None
        if messages:
            next_cursor = encode_cursor(
                messages[-1].get("createdAt"),
                messages[-1].get("messageId"),
                storage_module._credential_pepper(),
                self._cursor_context(room_id),
            )
        return {
            "items": items,
            "count": len(items),
            "hasMore": bool(has_more),
            "nextCursor": next_cursor,
            "cursorOpaque": True,
            "cursorIntegrity": "hmac-sha256",
            "cursorAnchorValidated": True,
            "pageByteBudget": 786432,
        }

    def message(self, message_id, viewer_agent_id=None):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                message = self._message_sql(connection, message_id)
                return (
                    self._project_message_sql(connection, message, viewer_agent_id)
                    if message
                    else None
                )
        data = self.store._load()
        self._scope_file(data)
        message = self._message_file(data, message_id)
        return (
            self._project_message_file(data, message, viewer_agent_id)
            if message
            else None
        )

    def message_revision(self, message_id, revision_number):
        if self.sql:
            with self.store._open_connection() as connection:
                self._scope_sql(connection)
                message = self._message_sql(connection, message_id)
                if not message:
                    return None
                row = connection.execute(
                    "SELECT * FROM matm_commons_message_revisions WHERE "
                    "workspace_id = ? AND project_id = ? AND message_id = ? "
                    "AND revision_number = ?",
                    (
                        self.workspace_id,
                        self.project_id,
                        message_id,
                        int(revision_number),
                    ),
                ).fetchone()
                revision = self._revision_from_sql(row)
                if not revision:
                    return None
                return public_message_revision(
                    message, revision, self._withdrawal_sql(connection, message_id)
                )
        data = self.store._load()
        self._scope_file(data)
        message = self._message_file(data, message_id)
        if not message:
            return None
        revision = next(
            (
                item
                for item in data.get("commonsMessageRevisions", {}).values()
                if item.get("workspaceId") == self.workspace_id
                and item.get("projectId") == self.project_id
                and item.get("messageId") == message_id
                and int(item.get("revisionNumber") or 0) == int(revision_number)
            ),
            None,
        )
        if not revision:
            return None
        return public_message_revision(
            message, revision, self._withdrawal_file(data, message_id)
        )

    def publish(
        self, room_id, auth, content, reply_to_message_id, key, request_digest
    ):
        if room_id != self.room_id:
            raise CommonsContractError("room_not_found", "404 Not Found")
        if self.sql:
            return self._publish_sql(
                room_id,
                auth,
                content,
                reply_to_message_id,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            agent_id = self._assert_bound_agent_file(data, auth)
            self._require_joined_file(data, room_id, agent_id)
            record_key, replay = self._file_idempotency(
                data, agent_id, "message-publish", key, request_digest
            )
            if replay:
                existing = self._message_file(data, replay.get("resultId"))
                if not existing or existing.get("roomId") != room_id:
                    raise CommonsContractError("idempotency_state_unavailable", "409 Conflict")
                return self._project_message_file(data, existing, agent_id), True
            if reply_to_message_id:
                parent = self._message_file(data, reply_to_message_id)
                if (
                    not parent
                    or parent.get("roomId") != room_id
                    or parent.get("state") == "withdrawn"
                ):
                    raise CommonsContractError("reply_target_unavailable", "409 Conflict")
            now = _iso_now()
            message_id = _stable_id(
                "commonsmessage",
                self.workspace_id,
                self.project_id,
                agent_id,
                digest_text(key),
            )
            revision_id = _stable_id("commonsrevision", message_id, "1")
            message = {
                "messageId": message_id,
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "roomId": room_id,
                "authorAgentId": agent_id,
                "replyToMessageId": reply_to_message_id or None,
                "currentRevision": 1,
                "currentRevisionId": revision_id,
                "state": "active",
                "createdAt": now,
                "correctedAt": None,
                "withdrawnAt": None,
            }
            revision = {
                "revisionId": revision_id,
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "roomId": room_id,
                "messageId": message_id,
                "revisionNumber": 1,
                "kind": "initial",
                "authorAgentId": agent_id,
                "content": content,
                "createdAt": now,
            }
            data.setdefault("commonsMessages", {})[message_id] = message
            data.setdefault("commonsMessageRevisions", {})[revision_id] = revision
            self._record_file_idempotency(
                data,
                record_key,
                agent_id,
                "message-publish",
                key,
                request_digest,
                "message",
                message_id,
                201,
            )
            self.store.audit(
                data,
                "commons.message.publish",
                agent_id,
                message_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "roomId": room_id,
                    "reply": bool(reply_to_message_id),
                    "revision": 1,
                },
            )
            self.store._save(data)
            return self._project_message_file(data, message, agent_id), False

    def _publish_sql(
        self, room_id, auth, content, reply_to_message_id, key, request_digest
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    agent_id = self._assert_bound_agent_sql(connection, auth)
                    self._require_joined_sql(connection, room_id, agent_id)
                    replay = self._sql_idempotency(
                        connection, agent_id, "message-publish", key, request_digest
                    )
                    if replay:
                        existing = self._message_sql(connection, replay["result_id"])
                        if not existing or existing.get("roomId") != room_id:
                            raise CommonsContractError(
                                "idempotency_state_unavailable", "409 Conflict"
                            )
                        return self._project_message_sql(connection, existing, agent_id), True
                    if reply_to_message_id:
                        parent = self._message_sql(connection, reply_to_message_id, lock=True)
                        if (
                            not parent
                            or parent.get("roomId") != room_id
                            or parent.get("state") == "withdrawn"
                        ):
                            raise CommonsContractError("reply_target_unavailable", "409 Conflict")
                    now = _iso_now()
                    message_id = _stable_id(
                        "commonsmessage",
                        self.workspace_id,
                        self.project_id,
                        agent_id,
                        digest_text(key),
                    )
                    revision_id = _stable_id("commonsrevision", message_id, "1")
                    connection.execute(
                        """
                        INSERT INTO matm_commons_messages (
                          message_id, workspace_id, project_id, room_id, author_agent_id,
                          reply_to_message_id, current_revision, current_revision_id,
                          state, created_at, corrected_at, withdrawn_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'active', ?, NULL, NULL)
                        """,
                        (
                            message_id,
                            self.workspace_id,
                            self.project_id,
                            room_id,
                            agent_id,
                            reply_to_message_id or None,
                            revision_id,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_commons_message_revisions (
                          revision_id, workspace_id, project_id, room_id, message_id,
                          revision_number, kind, author_agent_id, content, created_at
                        ) VALUES (?, ?, ?, ?, ?, 1, 'initial', ?, ?, ?)
                        """,
                        (
                            revision_id,
                            self.workspace_id,
                            self.project_id,
                            room_id,
                            message_id,
                            agent_id,
                            content,
                            now,
                        ),
                    )
                    self._record_sql_idempotency(
                        connection,
                        agent_id,
                        "message-publish",
                        key,
                        request_digest,
                        "message",
                        message_id,
                        201,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.message.publish",
                        agent_id,
                        message_id,
                        {
                            "projectId": self.project_id,
                            "roomId": room_id,
                            "reply": bool(reply_to_message_id),
                            "revision": 1,
                        },
                    )
                    message = self._message_sql(connection, message_id)
                    return self._project_message_sql(connection, message, agent_id), False

    def correct(
        self, message_id, auth, content, expected_revision, key, request_digest
    ):
        if self.sql:
            return self._correct_sql(
                message_id,
                auth,
                content,
                expected_revision,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            agent_id = self._assert_bound_agent_file(data, auth)
            message = self._message_file(data, message_id)
            if not message:
                raise CommonsContractError("message_not_found", "404 Not Found")
            self._require_joined_file(data, message.get("roomId"), agent_id)
            if message.get("authorAgentId") != agent_id:
                raise CommonsContractError("message_owner_required", "403 Forbidden")
            record_key, replay = self._file_idempotency(
                data, agent_id, "message-correct", key, request_digest
            )
            if replay:
                if replay.get("resultId") != message_id:
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._project_message_file(data, message, agent_id), True
            if message.get("state") == "withdrawn":
                raise CommonsContractError("message_withdrawn", "409 Conflict")
            if int(message.get("currentRevision") or 1) != int(expected_revision):
                raise CommonsContractError("revision_conflict", "409 Conflict")
            if int(expected_revision) >= 32:
                raise CommonsContractError("revision_limit_reached", "409 Conflict")
            now = _iso_now()
            next_revision = int(expected_revision) + 1
            revision_id = _stable_id("commonsrevision", message_id, str(next_revision))
            revision = {
                "revisionId": revision_id,
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "roomId": message.get("roomId"),
                "messageId": message_id,
                "revisionNumber": next_revision,
                "kind": "correction",
                "authorAgentId": agent_id,
                "content": content,
                "createdAt": now,
            }
            data.setdefault("commonsMessageRevisions", {})[revision_id] = revision
            message.update(
                {
                    "currentRevision": next_revision,
                    "currentRevisionId": revision_id,
                    "state": "active",
                    "correctedAt": now,
                }
            )
            self._record_file_idempotency(
                data,
                record_key,
                agent_id,
                "message-correct",
                key,
                request_digest,
                "message",
                message_id,
                200,
            )
            self.store.audit(
                data,
                "commons.message.correct",
                agent_id,
                message_id,
                self.workspace_id,
                {"projectId": self.project_id, "revision": next_revision},
            )
            self.store._save(data)
            return self._project_message_file(data, message, agent_id), False

    def _correct_sql(
        self, message_id, auth, content, expected_revision, key, request_digest
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    agent_id = self._assert_bound_agent_sql(connection, auth)
                    message = self._message_sql(connection, message_id, lock=True)
                    if not message:
                        raise CommonsContractError("message_not_found", "404 Not Found")
                    self._require_joined_sql(connection, message.get("roomId"), agent_id)
                    if message.get("authorAgentId") != agent_id:
                        raise CommonsContractError("message_owner_required", "403 Forbidden")
                    replay = self._sql_idempotency(
                        connection, agent_id, "message-correct", key, request_digest
                    )
                    if replay:
                        if replay["result_id"] != message_id:
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._project_message_sql(connection, message, agent_id), True
                    if message.get("state") == "withdrawn":
                        raise CommonsContractError("message_withdrawn", "409 Conflict")
                    if int(message.get("currentRevision") or 1) != int(expected_revision):
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    if int(expected_revision) >= 32:
                        raise CommonsContractError("revision_limit_reached", "409 Conflict")
                    now = _iso_now()
                    next_revision = int(expected_revision) + 1
                    revision_id = _stable_id(
                        "commonsrevision", message_id, str(next_revision)
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_commons_message_revisions (
                          revision_id, workspace_id, project_id, room_id, message_id,
                          revision_number, kind, author_agent_id, content, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'correction', ?, ?, ?)
                        """,
                        (
                            revision_id,
                            self.workspace_id,
                            self.project_id,
                            message.get("roomId"),
                            message_id,
                            next_revision,
                            agent_id,
                            content,
                            now,
                        ),
                    )
                    changed = connection.execute(
                        "UPDATE matm_commons_messages SET current_revision = ?, "
                        "current_revision_id = ?, state = 'active', corrected_at = ? "
                        "WHERE message_id = ? AND current_revision = ? AND state = 'active'",
                        (next_revision, revision_id, now, message_id, int(expected_revision)),
                    )
                    if changed.rowcount != 1:
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    self._record_sql_idempotency(
                        connection,
                        agent_id,
                        "message-correct",
                        key,
                        request_digest,
                        "message",
                        message_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.message.correct",
                        agent_id,
                        message_id,
                        {"projectId": self.project_id, "revision": next_revision},
                    )
                    return self._project_message_sql(
                        connection, self._message_sql(connection, message_id), agent_id
                    ), False

    def withdraw(
        self, message_id, auth, expected_revision, key, request_digest
    ):
        if self.sql:
            return self._withdraw_sql(
                message_id, auth, expected_revision, key, request_digest
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            agent_id = self._assert_bound_agent_file(data, auth)
            message = self._message_file(data, message_id)
            if not message:
                raise CommonsContractError("message_not_found", "404 Not Found")
            self._require_joined_file(data, message.get("roomId"), agent_id)
            if message.get("authorAgentId") != agent_id:
                raise CommonsContractError("message_owner_required", "403 Forbidden")
            record_key, replay = self._file_idempotency(
                data, agent_id, "message-withdraw", key, request_digest
            )
            if replay:
                if replay.get("resultId") != message_id:
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._project_message_file(data, message, agent_id), True
            if message.get("state") == "withdrawn":
                raise CommonsContractError("message_withdrawn", "409 Conflict")
            if int(message.get("currentRevision") or 1) != int(expected_revision):
                raise CommonsContractError("revision_conflict", "409 Conflict")
            now = _iso_now()
            withdrawal = {
                "withdrawalId": _stable_id("commonswithdrawal", message_id),
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "roomId": message.get("roomId"),
                "messageId": message_id,
                "withdrawnByAgentId": agent_id,
                "revisionAtWithdrawal": int(expected_revision),
                "withdrawnAt": now,
            }
            data.setdefault("commonsWithdrawals", {})[message_id] = withdrawal
            message.update({"state": "withdrawn", "withdrawnAt": now})
            self._record_file_idempotency(
                data,
                record_key,
                agent_id,
                "message-withdraw",
                key,
                request_digest,
                "message",
                message_id,
                200,
            )
            self.store.audit(
                data,
                "commons.message.withdraw",
                agent_id,
                message_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "revisionAtWithdrawal": int(expected_revision),
                },
            )
            self.store._save(data)
            return self._project_message_file(data, message, agent_id), False

    def _withdraw_sql(
        self, message_id, auth, expected_revision, key, request_digest
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    agent_id = self._assert_bound_agent_sql(connection, auth)
                    message = self._message_sql(connection, message_id, lock=True)
                    if not message:
                        raise CommonsContractError("message_not_found", "404 Not Found")
                    self._require_joined_sql(connection, message.get("roomId"), agent_id)
                    if message.get("authorAgentId") != agent_id:
                        raise CommonsContractError("message_owner_required", "403 Forbidden")
                    replay = self._sql_idempotency(
                        connection, agent_id, "message-withdraw", key, request_digest
                    )
                    if replay:
                        if replay["result_id"] != message_id:
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._project_message_sql(connection, message, agent_id), True
                    if message.get("state") == "withdrawn":
                        raise CommonsContractError("message_withdrawn", "409 Conflict")
                    if int(message.get("currentRevision") or 1) != int(expected_revision):
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    now = _iso_now()
                    withdrawal_id = _stable_id("commonswithdrawal", message_id)
                    connection.execute(
                        """
                        INSERT INTO matm_commons_withdrawals (
                          withdrawal_id, workspace_id, project_id, room_id, message_id,
                          withdrawn_by_agent_id, revision_at_withdrawal, withdrawn_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            withdrawal_id,
                            self.workspace_id,
                            self.project_id,
                            message.get("roomId"),
                            message_id,
                            agent_id,
                            int(expected_revision),
                            now,
                        ),
                    )
                    changed = connection.execute(
                        "UPDATE matm_commons_messages SET state = 'withdrawn', withdrawn_at = ? "
                        "WHERE message_id = ? AND current_revision = ? AND state = 'active'",
                        (now, message_id, int(expected_revision)),
                    )
                    if changed.rowcount != 1:
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    self._record_sql_idempotency(
                        connection,
                        agent_id,
                        "message-withdraw",
                        key,
                        request_digest,
                        "message",
                        message_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.message.withdraw",
                        agent_id,
                        message_id,
                        {
                            "projectId": self.project_id,
                            "revisionAtWithdrawal": int(expected_revision),
                        },
                    )
                    return self._project_message_sql(
                        connection, self._message_sql(connection, message_id), agent_id
                    ), False

    def acknowledge(
        self,
        message_id,
        auth,
        expected_revision,
        expected_revision_id,
        expected_state,
        expected_withdrawal_id,
        key,
        request_digest,
    ):
        if self.sql:
            return self._acknowledge_sql(
                message_id,
                auth,
                expected_revision,
                expected_revision_id,
                expected_state,
                expected_withdrawal_id,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            agent_id = self._assert_bound_agent_file(data, auth)
            message = self._message_file(data, message_id)
            if not message:
                raise CommonsContractError("message_not_found", "404 Not Found")
            self._require_joined_file(data, message.get("roomId"), agent_id)
            record_key, replay = self._file_idempotency(
                data, agent_id, "message-acknowledge", key, request_digest
            )
            acknowledgement_key = "%s:%s" % (message_id, agent_id)
            acknowledgement = data.get("commonsAcknowledgements", {}).get(
                acknowledgement_key
            )
            if replay:
                if replay.get("resultId") != _stable_id(
                    "commonsack", message_id, agent_id
                ):
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._project_message_file(data, message, agent_id), True
            withdrawal = self._withdrawal_file(data, message_id)
            binding = message_acknowledgement_binding(message, withdrawal)
            if (
                binding["expectedRevision"] != int(expected_revision)
                or binding["expectedRevisionId"] != expected_revision_id
                or binding["expectedState"] != expected_state
                or (binding["expectedWithdrawalId"] or None)
                != (expected_withdrawal_id or None)
            ):
                raise CommonsContractError("revision_conflict", "409 Conflict")
            if not acknowledgement:
                acknowledgement = {
                    "acknowledgementId": _stable_id(
                        "commonsack", message_id, agent_id
                    ),
                    "workspaceId": self.workspace_id,
                    "projectId": self.project_id,
                    "roomId": message.get("roomId"),
                    "messageId": message_id,
                    "agentId": agent_id,
                    "acknowledgedRevision": int(expected_revision),
                    "acknowledgedRevisionId": expected_revision_id,
                    "acknowledgedState": expected_state,
                    "acknowledgedWithdrawalId": expected_withdrawal_id or None,
                    "acknowledgedAt": _iso_now(),
                }
                data.setdefault("commonsAcknowledgements", {})[acknowledgement_key] = acknowledgement
            elif (
                int(acknowledgement.get("acknowledgedRevision") or 0)
                != int(expected_revision)
                or acknowledgement.get("acknowledgedRevisionId")
                != expected_revision_id
                or acknowledgement.get("acknowledgedState") != expected_state
                or (acknowledgement.get("acknowledgedWithdrawalId") or None)
                != (expected_withdrawal_id or None)
            ):
                acknowledgement.update(
                    {
                        "acknowledgedRevision": int(expected_revision),
                        "acknowledgedRevisionId": expected_revision_id,
                        "acknowledgedState": expected_state,
                        "acknowledgedWithdrawalId": expected_withdrawal_id or None,
                        "acknowledgedAt": _iso_now(),
                    }
                )
            self._record_file_idempotency(
                data,
                record_key,
                agent_id,
                "message-acknowledge",
                key,
                request_digest,
                "acknowledgement",
                acknowledgement["acknowledgementId"],
                200,
            )
            self.store.audit(
                data,
                "commons.message.acknowledge",
                agent_id,
                message_id,
                self.workspace_id,
                {
                    "projectId": self.project_id,
                    "acknowledgedRevision": acknowledgement["acknowledgedRevision"],
                },
            )
            self.store._save(data)
            return self._project_message_file(data, message, agent_id), False

    def _acknowledge_sql(
        self,
        message_id,
        auth,
        expected_revision,
        expected_revision_id,
        expected_state,
        expected_withdrawal_id,
        key,
        request_digest,
    ):
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    agent_id = self._assert_bound_agent_sql(connection, auth)
                    message = self._message_sql(connection, message_id, lock=True)
                    if not message:
                        raise CommonsContractError("message_not_found", "404 Not Found")
                    self._require_joined_sql(connection, message.get("roomId"), agent_id)
                    replay = self._sql_idempotency(
                        connection, agent_id, "message-acknowledge", key, request_digest
                    )
                    if replay:
                        if replay["result_id"] != _stable_id(
                            "commonsack", message_id, agent_id
                        ):
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._project_message_sql(connection, message, agent_id), True
                    withdrawal = self._withdrawal_sql(connection, message_id)
                    binding = message_acknowledgement_binding(message, withdrawal)
                    if (
                        binding["expectedRevision"] != int(expected_revision)
                        or binding["expectedRevisionId"] != expected_revision_id
                        or binding["expectedState"] != expected_state
                        or (binding["expectedWithdrawalId"] or None)
                        != (expected_withdrawal_id or None)
                    ):
                        raise CommonsContractError("revision_conflict", "409 Conflict")
                    acknowledgement = self._ack_sql(connection, message_id, agent_id)
                    acknowledgement_id = (
                        acknowledgement["acknowledgement_id"]
                        if acknowledgement
                        else _stable_id("commonsack", message_id, agent_id)
                    )
                    if not acknowledgement:
                        connection.execute(
                            """
                            INSERT INTO matm_commons_acknowledgements (
                              acknowledgement_id, workspace_id, project_id, room_id,
                              message_id, agent_id, acknowledged_revision,
                              acknowledged_revision_id, acknowledged_state,
                              acknowledged_withdrawal_id, acknowledged_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                acknowledgement_id,
                                self.workspace_id,
                                self.project_id,
                                message.get("roomId"),
                                message_id,
                                agent_id,
                                int(expected_revision),
                                expected_revision_id,
                                expected_state,
                                expected_withdrawal_id or None,
                                _iso_now(),
                            ),
                        )
                    elif (
                        int(acknowledgement["acknowledged_revision"] or 0)
                        != int(expected_revision)
                        or acknowledgement["acknowledged_revision_id"]
                        != expected_revision_id
                        or acknowledgement["acknowledged_state"] != expected_state
                        or (acknowledgement["acknowledged_withdrawal_id"] or None)
                        != (expected_withdrawal_id or None)
                    ):
                        connection.execute(
                            "UPDATE matm_commons_acknowledgements SET "
                            "acknowledged_revision = ?, acknowledged_revision_id = ?, "
                            "acknowledged_state = ?, acknowledged_withdrawal_id = ?, "
                            "acknowledged_at = ? "
                            "WHERE acknowledgement_id = ?",
                            (
                                int(expected_revision),
                                expected_revision_id,
                                expected_state,
                                expected_withdrawal_id or None,
                                _iso_now(),
                                acknowledgement_id,
                            ),
                        )
                    self._record_sql_idempotency(
                        connection,
                        agent_id,
                        "message-acknowledge",
                        key,
                        request_digest,
                        "acknowledgement",
                        acknowledgement_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.message.acknowledge",
                        agent_id,
                        message_id,
                        {
                            "projectId": self.project_id,
                            "acknowledgedRevision": int(expected_revision),
                        },
                    )
                    return self._project_message_sql(connection, message, agent_id), False

    @staticmethod
    def _public_browser_session(record):
        status = record.get("status")
        if status == "active" and timestamp_expired(record.get("expiresAt")):
            status = "expired"
        return {
            "browserSessionId": record.get("browserSessionId"),
            "workspaceId": record.get("workspaceId"),
            "projectId": record.get("projectId"),
            "agentId": record.get("agentId"),
            "issuingCredentialId": record.get("agentTokenId"),
            "status": status,
            "createdAt": record.get("createdAt"),
            "expiresAt": record.get("expiresAt"),
            "lastUsedAt": record.get("lastUsedAt"),
            "revokedAt": record.get("revokedAt"),
            "authority": "commons_only",
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawCredentialPersisted": False,
            "rawPayloadExposed": False,
        }

    @staticmethod
    def _browser_session_from_sql(row):
        if not row:
            return None
        return {
            "browserSessionId": row["browser_session_id"],
            "workspaceId": row["workspace_id"],
            "projectId": row["project_id"],
            "agentId": row["agent_id"],
            "agentTokenId": row["agent_token_id"],
            "secretHash": row["secret_hash"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "expiresAt": row["expires_at"],
            "lastUsedAt": row["last_used_at"],
            "revokedAt": row["revoked_at"],
        }

    def create_browser_session(
        self, auth, candidate_session_secret, key, request_digest
    ):
        if (auth or {}).get("authType") != "agent":
            raise CommonsContractError(
                "bearer_agent_credential_required",
                "403 Forbidden",
                "Only the original governed Bearer agent credential may create a Commons browser session.",
            )
        agent_id = self.assert_active_agent(auth)
        company_id = str((auth or {}).get("companyId") or "")
        agent_token_id = str((auth or {}).get("agentTokenId") or "")
        if not company_id or not agent_token_id:
            raise CommonsContractError("commons_agent_credential_required", "403 Forbidden")
        session_id, secret_hash = _candidate_browser_session(
            candidate_session_secret, company_id
        )
        now = _iso_now()
        expires_at = credential_expiry(
            self.settings.get("browserSessionTtlSeconds") or 8 * 60 * 60
        )
        record = {
            "browserSessionId": session_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentId": agent_id,
            "agentTokenId": agent_token_id,
            "secretHash": secret_hash,
            "status": "active",
            "createdAt": now,
            "expiresAt": expires_at,
            "lastUsedAt": None,
            "revokedAt": None,
        }
        if self.sql:
            with storage_module._LOCK:
                with self.store._open_connection() as connection:
                    with connection:
                        storage_module._connector_begin_immediate(connection)
                        self._scope_sql(connection, lock=True)
                        agent_id = self._assert_bound_agent_sql(connection, auth)
                        replay = self._sql_idempotency(
                            connection,
                            agent_token_id,
                            "browser-session-create",
                            key,
                            request_digest,
                        )
                        if replay:
                            row = connection.execute(
                                "SELECT * FROM matm_commons_browser_sessions WHERE "
                                "browser_session_id = ? AND workspace_id = ? AND project_id = ?",
                                (replay["result_id"], self.workspace_id, self.project_id),
                            ).fetchone()
                            prior = self._browser_session_from_sql(row)
                            if not prior:
                                raise CommonsContractError(
                                    "idempotency_state_unavailable", "409 Conflict"
                                )
                            projected = self._public_browser_session(prior)
                            profile = self._profile_from_sql(
                                self._profile_sql(
                                    connection, prior.get("agentId"), active_only=True
                                )
                            )
                            accepted = bool(
                                projected.get("status") == "active"
                                and profile
                                and profile.get("agentTokenId")
                                == prior.get("agentTokenId")
                            )
                            return {
                                "browserSession": projected,
                                "credentialAccepted": accepted,
                                "credentialCustody": "client_generated_and_retained",
                                "credentialReturnedOnce": False,
                                "rawCredentialPersisted": False,
                                "valuesRedacted": True,
                                "rawPayloadExposed": False,
                            }, True
                        if connection.execute(
                            "SELECT browser_session_id FROM matm_commons_browser_sessions "
                            "WHERE browser_session_id = ? OR secret_hash = ?",
                            (session_id, secret_hash),
                        ).fetchone():
                            raise CommonsContractError(
                                "browser_session_candidate_unavailable", "409 Conflict"
                            )
                        superseded = connection.execute(
                            "UPDATE matm_commons_browser_sessions SET status = 'revoked', "
                            "revoked_at = ? WHERE workspace_id = ? AND project_id = ? "
                            "AND agent_token_id = ? AND status = 'active'",
                            (
                                now,
                                self.workspace_id,
                                self.project_id,
                                agent_token_id,
                            ),
                        ).rowcount
                        connection.execute(
                            """
                            INSERT INTO matm_commons_browser_sessions (
                              browser_session_id, workspace_id, project_id, agent_id,
                              agent_token_id, secret_hash, status, created_at, expires_at,
                              last_used_at, revoked_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL, NULL)
                            """,
                            (
                                session_id,
                                self.workspace_id,
                                self.project_id,
                                agent_id,
                                agent_token_id,
                                secret_hash,
                                now,
                                expires_at,
                            ),
                        )
                        self._record_sql_idempotency(
                            connection,
                            agent_token_id,
                            "browser-session-create",
                            key,
                            request_digest,
                            "browser_session",
                            session_id,
                            201,
                        )
                        self.store._record_audit_sql(
                            connection,
                            self.workspace_id,
                            "commons.browser_session.create",
                            agent_id,
                            session_id,
                            {
                                "projectId": self.project_id,
                                "expiresAt": expires_at,
                                "authority": "commons_only",
                                "supersededSessionCount": int(superseded or 0),
                            },
                        )
        else:
            with storage_module._LOCK:
                data = self.store._load()
                self._scope_file(data)
                agent_id = self._assert_bound_agent_file(data, auth)
                record_key, replay = self._file_idempotency(
                    data,
                    agent_token_id,
                    "browser-session-create",
                    key,
                    request_digest,
                )
                if replay:
                    prior = data.get("commonsBrowserSessions", {}).get(
                        replay.get("resultId")
                    )
                    if not prior:
                        raise CommonsContractError(
                            "idempotency_state_unavailable", "409 Conflict"
                        )
                    projected = self._public_browser_session(prior)
                    profile = self._profile_file(data, prior.get("agentId"))
                    accepted = bool(
                        projected.get("status") == "active"
                        and self._profile_active_file(data, profile)
                        and profile.get("agentTokenId")
                        == prior.get("agentTokenId")
                    )
                    return {
                        "browserSession": projected,
                        "credentialAccepted": accepted,
                        "credentialCustody": "client_generated_and_retained",
                        "credentialReturnedOnce": False,
                        "rawCredentialPersisted": False,
                        "valuesRedacted": True,
                        "rawPayloadExposed": False,
                    }, True
                if session_id in data.get("commonsBrowserSessions", {}) or any(
                    item.get("secretHash") == secret_hash
                    for item in data.get("commonsBrowserSessions", {}).values()
                ):
                    raise CommonsContractError(
                        "browser_session_candidate_unavailable", "409 Conflict"
                    )
                superseded = 0
                for prior in data.get("commonsBrowserSessions", {}).values():
                    if (
                        prior.get("workspaceId") == self.workspace_id
                        and prior.get("projectId") == self.project_id
                        and prior.get("agentTokenId") == agent_token_id
                        and prior.get("status") == "active"
                    ):
                        prior.update({"status": "revoked", "revokedAt": now})
                        superseded += 1
                data.setdefault("commonsBrowserSessions", {})[session_id] = record
                self._record_file_idempotency(
                    data,
                    record_key,
                    agent_token_id,
                    "browser-session-create",
                    key,
                    request_digest,
                    "browser_session",
                    session_id,
                    201,
                )
                self.store.audit(
                    data,
                    "commons.browser_session.create",
                    agent_id,
                    session_id,
                    self.workspace_id,
                    {
                        "projectId": self.project_id,
                        "expiresAt": expires_at,
                        "authority": "commons_only",
                        "supersededSessionCount": superseded,
                    },
                )
                self.store._save(data)
        return {
            "browserSession": self._public_browser_session(record),
            "credentialAccepted": True,
            "credentialCustody": "client_generated_and_retained",
            "credentialReturnedOnce": False,
            "rawCredentialPersisted": False,
            "valuesRedacted": True,
            "rawPayloadExposed": False,
        }, False

    def current_browser_session(self, auth):
        if (auth or {}).get("authType") != "commons_browser_session":
            raise CommonsContractError(
                "commons_browser_session_required", "403 Forbidden"
            )
        session_id = str((auth or {}).get("browserSessionId") or "")
        if self.sql:
            with self.store._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_commons_browser_sessions WHERE "
                    "browser_session_id = ? AND workspace_id = ? AND project_id = ?",
                    (session_id, self.workspace_id, self.project_id),
                ).fetchone()
                record = self._browser_session_from_sql(row)
        else:
            record = self.store._load().get("commonsBrowserSessions", {}).get(
                session_id
            )
        if not record or record.get("status") != "active":
            raise CommonsContractError(
                "commons_browser_session_invalid", "401 Unauthorized"
            )
        return self._public_browser_session(record)

    def me(self, auth):
        agent_id = self.assert_active_agent(auth)
        agent = self.agent_profile(agent_id, public_only=False)
        if not agent:
            raise CommonsContractError(
                "commons_agent_credential_inactive", "401 Unauthorized"
            )
        profile = None
        if self.sql:
            with self.store._open_connection() as connection:
                profile = self._profile_from_sql(
                    self._profile_sql(connection, agent_id, active_only=True)
                )
        else:
            data = self.store._load()
            profile = self._profile_file(data, agent_id)
        principal = {
            "authType": (auth or {}).get("authType"),
            "credentialType": "commons_agent",
            "credentialId": (auth or {}).get("credentialId"),
            "agentId": agent_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "scopeType": "project",
            "scopeId": self.project_id,
            "authority": "commons_only",
            "credentialExpiresAt": (profile or {}).get("credentialExpiresAt"),
            "lifecycle": {
                "automaticExpiry": True,
                "rotationSupported": True,
                "selfRevocationSupported": True,
                "browserSessionExchangeSupported": True,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        result = {"principal": principal, "agent": agent}
        if (auth or {}).get("authType") == "commons_browser_session":
            result["browserSession"] = self.current_browser_session(auth)
        return result

    def _public_credential(self, profile, token_id, status, predecessor_id=None):
        return {
            "credentialId": token_id,
            "credentialType": "commons_agent",
            "authority": "commons_only",
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentId": (profile or {}).get("agentId"),
            "status": status,
            "expiresAt": (profile or {}).get("credentialExpiresAt"),
            "predecessorCredentialId": predecessor_id,
            "rawCredentialPersisted": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def _credential_projection_file(self, data, token_id, predecessor_id=None):
        token = data.get("agentTokens", {}).get(token_id)
        grant = data.get("agentAccessGrants", {}).get((token or {}).get("grantId"))
        profile = next(
            (
                item
                for item in data.get("commonsAgentProfiles", {}).values()
                if item.get("workspaceId") == self.workspace_id
                and item.get("projectId") == self.project_id
                and item.get("agentIdentityId") == (token or {}).get("agentIdentityId")
            ),
            None,
        )
        current = bool(profile and profile.get("agentTokenId") == token_id)
        if not token or not grant:
            status = "unavailable"
        elif token.get("revokedAt") or grant.get("status") in ("revoked", "superseded"):
            status = "revoked"
        elif not current:
            status = "superseded"
        elif timestamp_expired(profile.get("credentialExpiresAt")):
            status = "expired"
        elif self._profile_active_file(data, profile):
            status = "active"
        else:
            status = "inactive"
        return self._public_credential(
            profile if current else None, token_id, status, predecessor_id
        )

    def _credential_projection_sql(self, connection, token_id, predecessor_id=None):
        row = connection.execute(
            "SELECT t.revoked_at AS token_revoked_at, g.status AS grant_status, "
            "g.revoked_at AS grant_revoked_at, p.* FROM matm_agent_tokens t "
            "JOIN matm_agent_access_grants g ON g.grant_id = t.grant_id "
            "LEFT JOIN matm_commons_agent_profiles p ON "
            "p.workspace_id = ? AND p.project_id = ? "
            "AND p.agent_identity_id = t.agent_identity_id "
            "WHERE t.agent_token_id = ?",
            (self.workspace_id, self.project_id, token_id),
        ).fetchone()
        if not row:
            return self._public_credential(None, token_id, "unavailable", predecessor_id)
        profile = self._profile_from_sql(row) if row["profile_id"] else None
        current = bool(profile and profile.get("agentTokenId") == token_id)
        if row["token_revoked_at"] or row["grant_revoked_at"] or row["grant_status"] in (
            "revoked",
            "superseded",
        ):
            status = "revoked"
        elif not current:
            status = "superseded"
        elif timestamp_expired(profile.get("credentialExpiresAt")):
            status = "expired"
        elif row["grant_status"] == "active" and profile.get("status") == "active":
            status = "active"
        else:
            status = "inactive"
        return self._public_credential(
            profile if current else None, token_id, status, predecessor_id
        )

    def rotate_credential(
        self, auth, candidate_token_secret, key, request_digest
    ):
        if (
            (auth or {}).get("authType") != "agent"
            or not (auth or {}).get("commonsOnly")
        ):
            raise CommonsContractError(
                "commons_agent_credential_required", "403 Forbidden"
            )
        predecessor_id = str((auth or {}).get("agentTokenId") or "")
        agent_id = str((auth or {}).get("agentId") or "")
        company_id = str((auth or {}).get("companyId") or "")
        successor_id, successor_hash = _candidate_agent_credential(
            candidate_token_secret, company_id
        )
        if successor_id == predecessor_id:
            raise CommonsContractError(
                "agent_credential_candidate_unavailable", "409 Conflict"
            )
        if self.sql:
            return self._rotate_credential_sql(
                auth,
                successor_id,
                successor_hash,
                key,
                request_digest,
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            record_key, replay = self._file_idempotency(
                data,
                predecessor_id,
                "credential-rotate",
                key,
                request_digest,
            )
            profile = self._profile_file(data, agent_id)
            if replay:
                if replay.get("resultId") != successor_id or not profile:
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._credential_projection_file(
                    data, successor_id, predecessor_id
                ), True
            if (
                (auth or {}).get("active") is False
                or not self._profile_active_file(data, profile)
                or profile.get("agentTokenId") != predecessor_id
            ):
                raise CommonsContractError(
                    "commons_agent_credential_inactive", "401 Unauthorized"
                )
            if successor_id in data.get("agentTokens", {}) or any(
                hmac.compare_digest(
                    str(item.get("tokenHash") or ""), successor_hash
                )
                for item in data.get("agentTokens", {}).values()
            ) or any(
                item.get("candidateTokenId") == successor_id
                or hmac.compare_digest(
                    str(item.get("candidateTokenHash") or ""), successor_hash
                )
                for item in data.get("commonsEnrollmentRequests", {}).values()
            ):
                raise CommonsContractError(
                    "agent_credential_candidate_unavailable", "409 Conflict"
                )
            now = _iso_now()
            predecessor = data["agentTokens"][predecessor_id]
            predecessor_grant = data["agentAccessGrants"].get(
                predecessor.get("grantId")
            )
            grant_id = storage_module._id("grant")
            data["agentAccessGrants"][grant_id] = {
                "grantId": grant_id,
                "companyId": company_id,
                "agentIdentityId": profile.get("agentIdentityId"),
                "scopeType": "project",
                "scopeId": self.project_id,
                "workspaceId": self.workspace_id,
                "projectId": self.project_id,
                "supersedesTokenId": predecessor_id,
                "memoryTransferFromTokenId": predecessor_id,
                "commonsOnly": True,
                "status": "active",
                "createdAt": now,
                "pendingExpiresAt": None,
                "predecessorTokenId": predecessor_id,
                "activatedAt": now,
                "cancelledAt": None,
                "revokedAt": None,
                "revokedByMasterKeyId": None,
            }
            data["agentTokens"][successor_id] = {
                "agentTokenId": successor_id,
                "grantId": grant_id,
                "agentIdentityId": profile.get("agentIdentityId"),
                "tokenHash": successor_hash,
                "createdAt": now,
                "lastUsedAt": None,
                "revokedAt": None,
            }
            predecessor["revokedAt"] = now
            predecessor_grant.update(
                {"status": "revoked", "revokedAt": now}
            )
            profile.update(
                {
                    "agentTokenId": successor_id,
                    "credentialExpiresAt": credential_expiry(
                        self.settings.get("credentialTtlSeconds")
                    ),
                    "status": "active",
                    "updatedAt": now,
                }
            )
            for session in data.get("commonsBrowserSessions", {}).values():
                if (
                    session.get("workspaceId") == self.workspace_id
                    and session.get("projectId") == self.project_id
                    and session.get("agentTokenId") == predecessor_id
                    and session.get("status") == "active"
                ):
                    session.update({"status": "revoked", "revokedAt": now})
            self._record_file_idempotency(
                data,
                record_key,
                predecessor_id,
                "credential-rotate",
                key,
                request_digest,
                "agent_credential",
                successor_id,
                200,
            )
            self.store.audit(
                data,
                "commons.credential.rotate",
                agent_id,
                successor_id,
                self.workspace_id,
                {"projectId": self.project_id, "predecessorCredentialId": predecessor_id},
            )
            self.store._save(data)
            return self._public_credential(
                profile, successor_id, "active", predecessor_id
            ), False

    def _rotate_credential_sql(
        self, auth, successor_id, successor_hash, key, request_digest
    ):
        predecessor_id = str(auth.get("agentTokenId") or "")
        agent_id = str(auth.get("agentId") or "")
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    replay = self._sql_idempotency(
                        connection,
                        predecessor_id,
                        "credential-rotate",
                        key,
                        request_digest,
                    )
                    profile = self._profile_from_sql(
                        self._profile_sql(connection, agent_id)
                    )
                    if replay:
                        if replay["result_id"] != successor_id or not profile:
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._credential_projection_sql(
                            connection, successor_id, predecessor_id
                        ), True
                    if (
                        auth.get("active") is False
                        or not self._profile_sql(
                            connection, agent_id, active_only=True
                        )
                        or not profile
                        or profile.get("agentTokenId") != predecessor_id
                    ):
                        raise CommonsContractError(
                            "commons_agent_credential_inactive", "401 Unauthorized"
                        )
                    if connection.execute(
                        "SELECT agent_token_id FROM matm_agent_tokens WHERE "
                        "agent_token_id = ? OR token_hash = ?",
                        (successor_id, successor_hash),
                    ).fetchone():
                        raise CommonsContractError(
                            "agent_credential_candidate_unavailable", "409 Conflict"
                        )
                    if connection.execute(
                        "SELECT enrollment_request_id FROM "
                        "matm_commons_enrollment_requests WHERE "
                        "candidate_token_id = ? OR candidate_token_hash = ?",
                        (successor_id, successor_hash),
                    ).fetchone():
                        raise CommonsContractError(
                            "agent_credential_candidate_unavailable", "409 Conflict"
                        )
                    now = _iso_now()
                    grant_id = storage_module._id("grant")
                    try:
                        connection.execute(
                            """
                            INSERT INTO matm_agent_access_grants (
                              grant_id, company_id, agent_identity_id, scope_type,
                              scope_id, workspace_id, project_id, supersedes_token_id,
                              memory_transfer_from_token_id, status, created_at,
                              commons_only, pending_expires_at, predecessor_token_id,
                              activated_at, cancelled_at, revoked_at,
                              revoked_by_master_key_id
                            ) VALUES (?, ?, ?, 'project', ?, ?, ?, ?, ?, 'active', ?, 1, NULL, ?, ?, NULL, NULL, NULL)
                            """,
                            (
                                grant_id,
                                auth.get("companyId"),
                                profile.get("agentIdentityId"),
                                self.project_id,
                                self.workspace_id,
                                self.project_id,
                                predecessor_id,
                                predecessor_id,
                                now,
                                predecessor_id,
                                now,
                            ),
                        )
                        connection.execute(
                            "INSERT INTO matm_agent_tokens (agent_token_id, grant_id, "
                            "agent_identity_id, token_hash, created_at, last_used_at, revoked_at) "
                            "VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                            (
                                successor_id,
                                grant_id,
                                profile.get("agentIdentityId"),
                                successor_hash,
                                now,
                            ),
                        )
                    except Exception as exc:
                        if storage_module._is_sql_duplicate_key_conflict(exc):
                            raise CommonsContractError(
                                "agent_credential_candidate_unavailable", "409 Conflict"
                            )
                        raise
                    revoked_token = connection.execute(
                        "UPDATE matm_agent_tokens SET revoked_at = ? WHERE "
                        "agent_token_id = ? AND revoked_at IS NULL",
                        (now, predecessor_id),
                    )
                    revoked_grant = connection.execute(
                        "UPDATE matm_agent_access_grants SET status = 'revoked', "
                        "revoked_at = ? WHERE grant_id = ? AND status = 'active' "
                        "AND revoked_at IS NULL",
                        (now, auth.get("grantId")),
                    )
                    expires_at = credential_expiry(
                        self.settings.get("credentialTtlSeconds")
                    )
                    changed_profile = connection.execute(
                        "UPDATE matm_commons_agent_profiles SET agent_token_id = ?, "
                        "credential_expires_at = ?, status = 'active', updated_at = ? "
                        "WHERE workspace_id = ? AND project_id = ? AND agent_id = ? "
                        "AND agent_token_id = ?",
                        (
                            successor_id,
                            expires_at,
                            now,
                            self.workspace_id,
                            self.project_id,
                            agent_id,
                            predecessor_id,
                        ),
                    )
                    if (
                        revoked_token.rowcount != 1
                        or revoked_grant.rowcount != 1
                        or changed_profile.rowcount != 1
                    ):
                        raise CommonsContractError(
                            "credential_rotation_conflict", "409 Conflict"
                        )
                    connection.execute(
                        "UPDATE matm_commons_browser_sessions SET status = 'revoked', "
                        "revoked_at = ? WHERE workspace_id = ? AND project_id = ? "
                        "AND agent_token_id = ? AND status = 'active'",
                        (now, self.workspace_id, self.project_id, predecessor_id),
                    )
                    self._record_sql_idempotency(
                        connection,
                        predecessor_id,
                        "credential-rotate",
                        key,
                        request_digest,
                        "agent_credential",
                        successor_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.credential.rotate",
                        agent_id,
                        successor_id,
                        {
                            "projectId": self.project_id,
                            "predecessorCredentialId": predecessor_id,
                        },
                    )
                    profile = self._profile_from_sql(
                        self._profile_sql(connection, agent_id)
                    )
                    return self._public_credential(
                        profile, successor_id, "active", predecessor_id
                    ), False

    def revoke_credential(self, auth, key, request_digest):
        if (
            (auth or {}).get("authType") != "agent"
            or not (auth or {}).get("commonsOnly")
        ):
            raise CommonsContractError(
                "commons_agent_credential_required", "403 Forbidden"
            )
        token_id = str(auth.get("agentTokenId") or "")
        agent_id = str(auth.get("agentId") or "")
        if self.sql:
            return self._revoke_credential_sql(
                auth, key, request_digest
            )
        with storage_module._LOCK:
            data = self.store._load()
            self._scope_file(data)
            record_key, replay = self._file_idempotency(
                data, token_id, "credential-revoke", key, request_digest
            )
            profile = self._profile_file(data, agent_id)
            if replay:
                if replay.get("resultId") != token_id:
                    raise CommonsContractError("idempotency_conflict", "409 Conflict")
                return self._credential_projection_file(data, token_id), True
            token = data.get("agentTokens", {}).get(token_id)
            grant = data.get("agentAccessGrants", {}).get((token or {}).get("grantId"))
            if (
                not token
                or not grant
                or not profile
                or profile.get("agentTokenId") != token_id
                or token.get("revokedAt")
                or grant.get("status") != "active"
            ):
                raise CommonsContractError(
                    "commons_agent_credential_inactive", "401 Unauthorized"
                )
            now = _iso_now()
            token["revokedAt"] = now
            grant.update({"status": "revoked", "revokedAt": now})
            profile.update({"status": "revoked", "updatedAt": now})
            for session in data.get("commonsBrowserSessions", {}).values():
                if session.get("agentTokenId") == token_id and session.get("status") == "active":
                    session.update({"status": "revoked", "revokedAt": now})
            self._record_file_idempotency(
                data,
                record_key,
                token_id,
                "credential-revoke",
                key,
                request_digest,
                "agent_credential",
                token_id,
                200,
            )
            self.store.audit(
                data,
                "commons.credential.revoke",
                agent_id,
                token_id,
                self.workspace_id,
                {"projectId": self.project_id},
            )
            self.store._save(data)
            return self._public_credential(profile, token_id, "revoked"), False

    def _revoke_credential_sql(self, auth, key, request_digest):
        token_id = str(auth.get("agentTokenId") or "")
        agent_id = str(auth.get("agentId") or "")
        with storage_module._LOCK:
            with self.store._open_connection() as connection:
                with connection:
                    storage_module._connector_begin_immediate(connection)
                    self._scope_sql(connection, lock=True)
                    replay = self._sql_idempotency(
                        connection, token_id, "credential-revoke", key, request_digest
                    )
                    profile = self._profile_from_sql(
                        self._profile_sql(connection, agent_id)
                    )
                    if replay:
                        if replay["result_id"] != token_id:
                            raise CommonsContractError(
                                "idempotency_conflict", "409 Conflict"
                            )
                        return self._credential_projection_sql(
                            connection, token_id
                        ), True
                    if (
                        auth.get("active") is False
                        or not profile
                        or profile.get("agentTokenId") != token_id
                    ):
                        raise CommonsContractError(
                            "commons_agent_credential_inactive", "401 Unauthorized"
                        )
                    now = _iso_now()
                    token_changed = connection.execute(
                        "UPDATE matm_agent_tokens SET revoked_at = ? WHERE "
                        "agent_token_id = ? AND revoked_at IS NULL",
                        (now, token_id),
                    )
                    grant_changed = connection.execute(
                        "UPDATE matm_agent_access_grants SET status = 'revoked', revoked_at = ? "
                        "WHERE grant_id = ? AND status = 'active' AND revoked_at IS NULL",
                        (now, auth.get("grantId")),
                    )
                    profile_changed = connection.execute(
                        "UPDATE matm_commons_agent_profiles SET status = 'revoked', "
                        "updated_at = ? WHERE workspace_id = ? AND project_id = ? "
                        "AND agent_id = ? AND agent_token_id = ? AND status = 'active'",
                        (
                            now,
                            self.workspace_id,
                            self.project_id,
                            agent_id,
                            token_id,
                        ),
                    )
                    if (
                        token_changed.rowcount != 1
                        or grant_changed.rowcount != 1
                        or profile_changed.rowcount != 1
                    ):
                        raise CommonsContractError(
                            "credential_revocation_conflict", "409 Conflict"
                        )
                    connection.execute(
                        "UPDATE matm_commons_browser_sessions SET status = 'revoked', "
                        "revoked_at = ? WHERE workspace_id = ? AND project_id = ? "
                        "AND agent_token_id = ? AND status = 'active'",
                        (now, self.workspace_id, self.project_id, token_id),
                    )
                    self._record_sql_idempotency(
                        connection,
                        token_id,
                        "credential-revoke",
                        key,
                        request_digest,
                        "agent_credential",
                        token_id,
                        200,
                    )
                    self.store._record_audit_sql(
                        connection,
                        self.workspace_id,
                        "commons.credential.revoke",
                        agent_id,
                        token_id,
                        {"projectId": self.project_id},
                    )
                    profile["status"] = "revoked"
                    profile["updatedAt"] = now
                    return self._public_credential(
                        profile, token_id, "revoked"
                    ), False

    def authenticate_browser_session(self, session_secret, allow_revoked=False):
        session_id, secret_part = storage_module._parse_governed_credential(
            session_secret, "commonsbrowser"
        )
        if not session_id or not secret_part:
            return None
        now = _iso_now()
        if self.sql:
            with storage_module._LOCK:
                with self.store._open_connection() as connection:
                    with connection:
                        try:
                            scope = self._scope_sql(connection)
                        except CommonsContractError:
                            return None
                        row = connection.execute(
                            "SELECT * FROM matm_commons_browser_sessions "
                            "WHERE browser_session_id = ? AND workspace_id = ? AND project_id = ?",
                            (session_id, self.workspace_id, self.project_id),
                        ).fetchone()
                        record = self._browser_session_from_sql(row)
                        if (
                            not record
                            or (
                                not allow_revoked
                                and (
                                    record.get("status") != "active"
                                    or record.get("revokedAt")
                                )
                            )
                            or timestamp_expired(record.get("expiresAt"))
                        ):
                            return None
                        expected = storage_module._governed_credential_digest(
                            "commonsbrowser",
                            scope["company_id"],
                            session_id,
                            secret_part,
                        )
                        if not hmac.compare_digest(
                            expected, str(record.get("secretHash") or "")
                        ):
                            return None
                        if not allow_revoked:
                            profile_row = self._profile_sql(
                                connection, record.get("agentId"), active_only=True
                            )
                            profile = self._profile_from_sql(profile_row)
                            if (
                                not profile
                                or profile.get("agentTokenId")
                                != record.get("agentTokenId")
                            ):
                                return None
                            connection.execute(
                                "UPDATE matm_commons_browser_sessions SET last_used_at = ? "
                                "WHERE browser_session_id = ? AND status = 'active'",
                                (now, session_id),
                            )
                        company_id = scope["company_id"]
        else:
            with storage_module._LOCK:
                data = self.store._load()
                try:
                    _workspace, _project, company = self._scope_file(data)
                except CommonsContractError:
                    return None
                record = data.get("commonsBrowserSessions", {}).get(session_id)
                if (
                    not record
                    or record.get("workspaceId") != self.workspace_id
                    or record.get("projectId") != self.project_id
                    or (
                        not allow_revoked
                        and (
                            record.get("status") != "active"
                            or record.get("revokedAt")
                        )
                    )
                    or timestamp_expired(record.get("expiresAt"))
                ):
                    return None
                expected = storage_module._governed_credential_digest(
                    "commonsbrowser",
                    company.get("companyId"),
                    session_id,
                    secret_part,
                )
                if not hmac.compare_digest(
                    expected, str(record.get("secretHash") or "")
                ):
                    return None
                if not allow_revoked:
                    profile = self._profile_file(data, record.get("agentId"))
                    if (
                        not self._profile_active_file(data, profile)
                        or profile.get("agentTokenId") != record.get("agentTokenId")
                    ):
                        return None
                    record["lastUsedAt"] = now
                    self.store._save(data)
                company_id = company.get("companyId")
        return {
            "authType": "commons_browser_session",
            "credentialType": "agent",
            "publicCredentialType": "commons_browser_session",
            "companyId": company_id,
            "workspaceId": self.workspace_id,
            "projectId": self.project_id,
            "agentId": record.get("agentId"),
            "agentTokenId": record.get("agentTokenId"),
            "credentialId": session_id,
            "browserSessionId": session_id,
            "scopeType": "project",
            "scopeId": self.project_id,
            "commonsOnly": True,
            "active": record.get("status") == "active" and not record.get("revokedAt"),
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def revoke_browser_session(self, auth, key, request_digest):
        if (auth or {}).get("authType") != "commons_browser_session":
            raise CommonsContractError(
                "commons_browser_session_required", "403 Forbidden"
            )
        session_id = str((auth or {}).get("browserSessionId") or "")
        now = _iso_now()
        if self.sql:
            with storage_module._LOCK:
                with self.store._open_connection() as connection:
                    with connection:
                        storage_module._connector_begin_immediate(connection)
                        self._scope_sql(connection, lock=True)
                        replay_record = self._sql_idempotency(
                            connection,
                            session_id,
                            "browser-session-revoke",
                            key,
                            request_digest,
                        )
                        row = connection.execute(
                            "SELECT * FROM matm_commons_browser_sessions WHERE "
                            "browser_session_id = ? AND workspace_id = ? AND project_id = ?",
                            (session_id, self.workspace_id, self.project_id),
                        ).fetchone()
                        record = self._browser_session_from_sql(row)
                        if not record:
                            raise CommonsContractError(
                                "commons_browser_session_invalid", "401 Unauthorized"
                            )
                        if replay_record:
                            if replay_record["result_id"] != session_id:
                                raise CommonsContractError(
                                    "idempotency_conflict", "409 Conflict"
                                )
                            return self._public_browser_session(record), True
                        if record.get("status") == "active":
                            connection.execute(
                                "UPDATE matm_commons_browser_sessions SET status = 'revoked', "
                                "revoked_at = ? WHERE browser_session_id = ? AND status = 'active'",
                                (now, session_id),
                            )
                            record.update({"status": "revoked", "revokedAt": now})
                            self.store._record_audit_sql(
                                connection,
                                self.workspace_id,
                                "commons.browser_session.revoke",
                                record.get("agentId"),
                                session_id,
                                {"projectId": self.project_id},
                            )
                            self._record_sql_idempotency(
                                connection,
                                session_id,
                                "browser-session-revoke",
                                key,
                                request_digest,
                                "browser_session",
                                session_id,
                                200,
                            )
                            replay = False
                        else:
                            raise CommonsContractError(
                                "commons_browser_session_revoked", "409 Conflict"
                            )
        else:
            with storage_module._LOCK:
                data = self.store._load()
                record = data.get("commonsBrowserSessions", {}).get(session_id)
                if (
                    not record
                    or record.get("workspaceId") != self.workspace_id
                    or record.get("projectId") != self.project_id
                ):
                    raise CommonsContractError(
                        "commons_browser_session_invalid", "401 Unauthorized"
                    )
                record_key, replay_record = self._file_idempotency(
                    data,
                    session_id,
                    "browser-session-revoke",
                    key,
                    request_digest,
                )
                if replay_record:
                    if replay_record.get("resultId") != session_id:
                        raise CommonsContractError(
                            "idempotency_conflict", "409 Conflict"
                        )
                    return self._public_browser_session(record), True
                if record.get("status") == "active":
                    record.update({"status": "revoked", "revokedAt": now})
                    self._record_file_idempotency(
                        data,
                        record_key,
                        session_id,
                        "browser-session-revoke",
                        key,
                        request_digest,
                        "browser_session",
                        session_id,
                        200,
                    )
                    self.store.audit(
                        data,
                        "commons.browser_session.revoke",
                        record.get("agentId"),
                        session_id,
                        self.workspace_id,
                        {"projectId": self.project_id},
                    )
                    self.store._save(data)
                    replay = False
                else:
                    raise CommonsContractError(
                        "commons_browser_session_revoked", "409 Conflict"
                    )
        return self._public_browser_session(record), replay
