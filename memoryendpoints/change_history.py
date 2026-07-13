"""Pure policy helpers for reversible company change history.

The storage layer owns persistence and transaction boundaries.  This module
owns the safety contract: an agent mutation takes effect immediately, while
its redacted forensic record is visible only to an authenticated human-owner
session.  Routine history expires after seven days for free companies.  A
company deletion is a reversible soft-delete flag, never routine history, and
remains quota-counted until a human permanently purges the company.

Every clock value and identifier is supplied by the caller so the functions
remain deterministic and have no storage, network, or ambient-clock access.
"""

from __future__ import annotations

import copy
import datetime as _datetime
import hashlib
import json

from memoryendpoints.security import redact_payload


SCHEMA_VERSION = "memoryendpoints.change_history.v1"
AGENT_MUTATION_SCHEMA_VERSION = "memoryendpoints.agent_mutation.v1"
FREE_COMPANY_ROUTINE_HISTORY_RETENTION_DAYS = 7
COMPANY_STORAGE_QUOTA_BYTES = 200 * 1024 * 1024

HUMAN_OWNER_SESSION = "human_owner_session"
AGENT_CREDENTIAL_SESSION = "agent_credential"
COMPANY_MASTER_CREDENTIAL_SESSION = "company_master_credential"

ROUTINE_AGENT_MUTATION = "routine_agent_mutation"
COMPANY_SOFT_DELETE = "company_soft_delete"

PENDING_HUMAN_REVIEW = "pending_human_review"
REVIEWED_ACCEPTED = "reviewed_accepted"
UNDONE_BY_HUMAN = "undone_by_human"


class ChangeHistoryPolicyError(ValueError):
    """A requested change-history operation violates the domain contract."""


class HumanOwnerSessionRequired(PermissionError):
    """The operation is available only to a human-owner session."""


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ChangeHistoryPolicyError("%s must be a non-empty string." % name)
    return value.strip()


def _utc_datetime(value, name):
    text = _required_text(value, name)
    try:
        parsed = _datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChangeHistoryPolicyError("%s must be an ISO-8601 timestamp." % name) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChangeHistoryPolicyError("%s must include a timezone." % name)
    return parsed.astimezone(_datetime.timezone.utc)


def _utc_text(value, name):
    parsed = _utc_datetime(value, name)
    return parsed.isoformat().replace("+00:00", "Z")


def _json_copy(value, name):
    """Return a detached, redacted JSON value suitable for forensic storage."""

    sanitized = redact_payload(copy.deepcopy(value))
    try:
        raw = json.dumps(
            sanitized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ChangeHistoryPolicyError("%s must be a normalized JSON value." % name) from exc
    return json.loads(raw)


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require_human_owner_session(session_kind):
    if session_kind != HUMAN_OWNER_SESSION:
        raise HumanOwnerSessionRequired(
            "A current human-owner session is required; bearer credentials cannot access company history."
        )


def _history_id(record):
    if not isinstance(record, dict):
        raise ChangeHistoryPolicyError("History records must be objects.")
    return _required_text(record.get("historyId"), "historyId")


def _record_company(record):
    return _required_text(record.get("companyId"), "companyId")


def _assert_company_records(records, company_id):
    normalized_company_id = _required_text(company_id, "company_id")
    copied = []
    seen = set()
    for record in records:
        copied_record = copy.deepcopy(record)
        history_id = _history_id(copied_record)
        if history_id in seen:
            raise ChangeHistoryPolicyError("History ids must be unique within a company operation.")
        seen.add(history_id)
        if _record_company(copied_record) != normalized_company_id:
            raise ChangeHistoryPolicyError("All history records must belong to the requested company.")
        copied.append(copied_record)
    return normalized_company_id, copied


def _routine_expiry(recorded_at, retention_days):
    if not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days < 1:
        raise ChangeHistoryPolicyError("retention_days must be a positive integer.")
    expires = _utc_datetime(recorded_at, "recorded_at") + _datetime.timedelta(days=retention_days)
    return expires.isoformat().replace("+00:00", "Z")


def apply_agent_mutation(
    *,
    history_id,
    company_id,
    agent_id,
    operation,
    resource_type,
    resource_id,
    before_snapshot,
    after_snapshot,
    recorded_at,
    retention_days=FREE_COMPANY_ROUTINE_HISTORY_RETENTION_DAYS,
):
    """Describe an immediately applied agent update/delete and hidden history.

    The return value is an internal storage envelope.  Routes serving agents
    must use :func:`agent_mutation_projection`; they must never serialize the
    ``historyRecord`` member.
    """

    normalized_operation = _required_text(operation, "operation").lower()
    if normalized_operation not in {"update", "delete"}:
        raise ChangeHistoryPolicyError("operation must be update or delete.")
    normalized_history_id = _required_text(history_id, "history_id")
    normalized_company_id = _required_text(company_id, "company_id")
    normalized_agent_id = _required_text(agent_id, "agent_id")
    normalized_resource_type = _required_text(resource_type, "resource_type")
    normalized_resource_id = _required_text(resource_id, "resource_id")
    normalized_recorded_at = _utc_text(recorded_at, "recorded_at")

    before = _json_copy(before_snapshot, "before_snapshot")
    if normalized_operation == "delete":
        if after_snapshot is not None:
            raise ChangeHistoryPolicyError("A delete must use a null after_snapshot.")
        after = None
    else:
        if after_snapshot is None:
            raise ChangeHistoryPolicyError("An update requires after_snapshot.")
        after = _json_copy(after_snapshot, "after_snapshot")

    company_soft_delete = normalized_operation == "delete" and normalized_resource_type == "company"
    history_class = COMPANY_SOFT_DELETE if company_soft_delete else ROUTINE_AGENT_MUTATION
    expires_at = None if company_soft_delete else _routine_expiry(normalized_recorded_at, retention_days)
    undo_window = "indefinite_until_human_purge" if company_soft_delete else "routine_retention_window"

    application = {
        "schemaVersion": SCHEMA_VERSION,
        "applied": True,
        "operation": normalized_operation,
        "companyId": normalized_company_id,
        "resourceType": normalized_resource_type,
        "resourceId": normalized_resource_id,
        "deleted": normalized_operation == "delete",
        "currentState": copy.deepcopy(after),
    }
    history_record = {
        "schemaVersion": SCHEMA_VERSION,
        "historyId": normalized_history_id,
        "companyId": normalized_company_id,
        "historyClass": history_class,
        "recordedAt": normalized_recorded_at,
        "actor": {"actorType": "agent", "agentId": normalized_agent_id},
        "operation": normalized_operation,
        "resource": {"resourceType": normalized_resource_type, "resourceId": normalized_resource_id},
        "visibility": {
            "humanOwnerSessionOnly": True,
            "agentCredentialsDenied": True,
            "companyMasterCredentialsDenied": True,
            "includedInCompanyExport": True,
        },
        "beforeSnapshot": before,
        "afterSnapshot": copy.deepcopy(after),
        "review": {
            "state": PENDING_HUMAN_REVIEW,
            "reviewedAt": None,
            "reviewedByHumanId": None,
        },
        "undo": {
            "available": True,
            "used": False,
            "window": undo_window,
            "expiresAt": expires_at,
        },
        "retention": {
            "routineRetentionDays": None if company_soft_delete else retention_days,
            "expiresAt": expires_at,
            "excludedFromRoutinePruning": company_soft_delete,
            "retainedUntilPermanentHumanPurge": company_soft_delete,
        },
        "quota": {
            "counted": True,
            "companyLimitBytes": COMPANY_STORAGE_QUOTA_BYTES,
        },
        "softDelete": (
            {
                "isDeleted": True,
                "mode": "reversible_flag",
                "underlyingCompanyDataRetained": True,
                "restorableWithoutTimeLimit": True,
            }
            if company_soft_delete
            else None
        ),
    }
    return {"application": application, "historyRecord": history_record}


def agent_mutation_projection(internal_result):
    """Return the only mutation fields safe for an agent response."""

    if not isinstance(internal_result, dict) or not isinstance(internal_result.get("application"), dict):
        raise ChangeHistoryPolicyError("An internal mutation result is required.")
    application = internal_result["application"]
    return {
        "schemaVersion": AGENT_MUTATION_SCHEMA_VERSION,
        "applied": bool(application.get("applied")),
        "operation": application.get("operation"),
        "companyId": application.get("companyId"),
        "resourceType": application.get("resourceType"),
        "resourceId": application.get("resourceId"),
        "deleted": bool(application.get("deleted")),
        "currentState": copy.deepcopy(application.get("currentState")),
    }


def history_records_for_human(records, *, session_kind):
    """Return detached forensic records only for a human-owner session."""

    _require_human_owner_session(session_kind)
    return copy.deepcopy(list(records))


def review_history_record(
    record,
    *,
    current_state,
    action,
    human_actor_id,
    reviewed_at,
    session_kind,
):
    """Acknowledge an applied change or undo it after human review."""

    _require_human_owner_session(session_kind)
    reviewed_record = copy.deepcopy(record)
    _history_id(reviewed_record)
    normalized_action = _required_text(action, "action").lower()
    if normalized_action not in {"accept", "undo"}:
        raise ChangeHistoryPolicyError("action must be accept or undo.")
    normalized_reviewer = _required_text(human_actor_id, "human_actor_id")
    normalized_reviewed_at = _utc_text(reviewed_at, "reviewed_at")
    review = reviewed_record.get("review")
    if not isinstance(review, dict) or review.get("state") != PENDING_HUMAN_REVIEW:
        raise ChangeHistoryPolicyError("Only pending history may be reviewed.")

    expected_current = reviewed_record.get("afterSnapshot")
    safe_current = _json_copy(current_state, "current_state") if current_state is not None else None
    if normalized_action == "undo" and safe_current != expected_current:
        raise ChangeHistoryPolicyError("The current state changed after this history record; undo requires conflict review.")

    undo = reviewed_record.get("undo")
    if not isinstance(undo, dict) or not undo.get("available"):
        raise ChangeHistoryPolicyError("This history record is not undoable.")
    expires_at = undo.get("expiresAt")
    if normalized_action == "undo" and expires_at is not None:
        if _utc_datetime(normalized_reviewed_at, "reviewed_at") > _utc_datetime(expires_at, "expiresAt"):
            raise ChangeHistoryPolicyError("The routine undo window has expired.")

    if normalized_action == "undo":
        resulting_state = copy.deepcopy(reviewed_record.get("beforeSnapshot"))
        review_state = UNDONE_BY_HUMAN
        undo["available"] = False
        undo["used"] = True
        undo["usedAt"] = normalized_reviewed_at
        undo["usedByHumanId"] = normalized_reviewer
        if isinstance(reviewed_record.get("softDelete"), dict):
            reviewed_record["softDelete"]["isDeleted"] = False
            reviewed_record["softDelete"]["restoredAt"] = normalized_reviewed_at
            reviewed_record["softDelete"]["restoredByHumanId"] = normalized_reviewer
    else:
        resulting_state = safe_current
        review_state = REVIEWED_ACCEPTED

    review.update(
        {
            "state": review_state,
            "reviewedAt": normalized_reviewed_at,
            "reviewedByHumanId": normalized_reviewer,
        }
    )
    return {
        "historyRecord": reviewed_record,
        "application": {
            "schemaVersion": SCHEMA_VERSION,
            "applied": normalized_action == "undo",
            "action": normalized_action,
            "currentState": resulting_state,
        },
    }


def restore_soft_deleted_company(
    record,
    *,
    human_actor_id,
    restored_at,
    session_kind,
):
    """Restore an agent-soft-deleted company without a retention deadline."""

    if not isinstance(record, dict) or record.get("historyClass") != COMPANY_SOFT_DELETE:
        raise ChangeHistoryPolicyError("A company soft-delete history record is required.")
    soft_delete = record.get("softDelete")
    if not isinstance(soft_delete, dict) or not soft_delete.get("isDeleted"):
        raise ChangeHistoryPolicyError("The company is not currently soft-deleted.")
    return review_history_record(
        record,
        current_state=None,
        action="undo",
        human_actor_id=human_actor_id,
        reviewed_at=restored_at,
        session_kind=session_kind,
    )


def prune_routine_history(
    records,
    *,
    company_id,
    now,
    retention_days=FREE_COMPANY_ROUTINE_HISTORY_RETENTION_DAYS,
):
    """Prune routine records strictly older than the retention boundary."""

    normalized_company_id, copied = _assert_company_records(records, company_id)
    now_value = _utc_datetime(now, "now")
    if not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days < 1:
        raise ChangeHistoryPolicyError("retention_days must be a positive integer.")
    cutoff = now_value - _datetime.timedelta(days=retention_days)
    retained = []
    pruned_ids = []
    for record in copied:
        if record.get("historyClass") == COMPANY_SOFT_DELETE:
            retained.append(record)
            continue
        recorded_at = _utc_datetime(record.get("recordedAt"), "recordedAt")
        if recorded_at < cutoff:
            pruned_ids.append(_history_id(record))
        else:
            retained.append(record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "companyId": normalized_company_id,
        "retentionDays": retention_days,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
        "records": retained,
        "prunedHistoryIds": pruned_ids,
    }


def summarize_company_history_usage(records, *, company_id):
    """Measure quota-counted history with canonical UTF-8 JSON bytes."""

    normalized_company_id, copied = _assert_company_records(records, company_id)
    used = sum(len(_canonical_bytes(record)) for record in copied if record.get("quota", {}).get("counted", True))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "companyId": normalized_company_id,
        "historyBytes": used,
        "companyLimitBytes": COMPANY_STORAGE_QUOTA_BYTES,
        "remainingCompanyBytes": max(0, COMPANY_STORAGE_QUOTA_BYTES - used),
        "quotaExceeded": used > COMPANY_STORAGE_QUOTA_BYTES,
        "softDeleteHistoryBytes": sum(
            len(_canonical_bytes(record))
            for record in copied
            if record.get("historyClass") == COMPANY_SOFT_DELETE and record.get("quota", {}).get("counted", True)
        ),
    }


def _clear_plan_digest(plan):
    basis = {key: value for key, value in plan.items() if key != "planDigest"}
    return hashlib.sha256(_canonical_bytes(basis)).hexdigest()


def plan_clear_all_history(
    records,
    *,
    company_id,
    human_actor_id,
    requested_at,
    session_kind,
    export_opportunity_acknowledged,
    export_receipt_digest=None,
):
    """Plan routine-history clearing after a human acknowledges export access."""

    _require_human_owner_session(session_kind)
    if export_opportunity_acknowledged is not True:
        raise ChangeHistoryPolicyError("The human must acknowledge the company export opportunity before clearing history.")
    normalized_company_id, copied = _assert_company_records(records, company_id)
    normalized_actor = _required_text(human_actor_id, "human_actor_id")
    normalized_requested_at = _utc_text(requested_at, "requested_at")
    if export_receipt_digest is not None:
        export_receipt_digest = _required_text(export_receipt_digest, "export_receipt_digest")

    clear_ids = sorted(
        _history_id(record) for record in copied if record.get("historyClass") != COMPANY_SOFT_DELETE
    )
    preserved_ids = sorted(
        _history_id(record) for record in copied if record.get("historyClass") == COMPANY_SOFT_DELETE
    )
    reclaimable = sum(
        len(_canonical_bytes(record)) for record in copied if _history_id(record) in set(clear_ids)
    )
    plan = {
        "schemaVersion": SCHEMA_VERSION,
        "planType": "clear_routine_company_history",
        "companyId": normalized_company_id,
        "requestedAt": normalized_requested_at,
        "requestedByHumanId": normalized_actor,
        "historyIdsToClear": clear_ids,
        "historyIdsPreserved": preserved_ids,
        "estimatedReclaimableBytes": reclaimable,
        "exportOpportunityAcknowledged": True,
        "exportDownloaded": export_receipt_digest is not None,
        "exportReceiptDigest": export_receipt_digest,
        "exportRecommendation": "download_the_complete_company_export_before_clearing_history",
        "companySoftDeleteHistoryPreserved": True,
    }
    plan["planDigest"] = _clear_plan_digest(plan)
    return plan


def execute_clear_all_history(
    records,
    plan,
    *,
    human_actor_id,
    completed_at,
    session_kind,
):
    """Execute an unchanged clear-history plan without mutating caller data."""

    _require_human_owner_session(session_kind)
    if not isinstance(plan, dict) or plan.get("planType") != "clear_routine_company_history":
        raise ChangeHistoryPolicyError("A clear-routine-company-history plan is required.")
    if plan.get("exportOpportunityAcknowledged") is not True:
        raise ChangeHistoryPolicyError("The clear plan lacks export opportunity acknowledgement.")
    if plan.get("planDigest") != _clear_plan_digest(plan):
        raise ChangeHistoryPolicyError("The clear-history plan digest is invalid.")
    normalized_company_id, copied = _assert_company_records(records, plan.get("companyId"))
    normalized_actor = _required_text(human_actor_id, "human_actor_id")
    normalized_completed_at = _utc_text(completed_at, "completed_at")

    actual_clear = sorted(
        _history_id(record) for record in copied if record.get("historyClass") != COMPANY_SOFT_DELETE
    )
    actual_preserved = sorted(
        _history_id(record) for record in copied if record.get("historyClass") == COMPANY_SOFT_DELETE
    )
    if actual_clear != plan.get("historyIdsToClear") or actual_preserved != plan.get("historyIdsPreserved"):
        raise ChangeHistoryPolicyError("History changed after planning; create a fresh clear-history plan.")
    remaining = [record for record in copied if record.get("historyClass") == COMPANY_SOFT_DELETE]
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "companyId": normalized_company_id,
        "completedAt": normalized_completed_at,
        "completedByHumanId": normalized_actor,
        "clearedHistoryIds": actual_clear,
        "preservedHistoryIds": actual_preserved,
        "remainingRecords": remaining,
        "exportOpportunityAcknowledged": True,
        "exportDownloaded": bool(plan.get("exportDownloaded")),
        "companySoftDeleteHistoryPreserved": True,
    }
    result.update(summarize_company_history_usage(remaining, company_id=normalized_company_id))
    return result


def required_permanent_purge_confirmation(company_id):
    """Return the exact human confirmation phrase for irreversible purge."""

    return "PERMANENTLY DELETE COMPANY %s" % _required_text(company_id, "company_id")


def authorize_permanent_company_purge(
    soft_delete_record,
    *,
    human_actor_id,
    authorized_at,
    session_kind,
    export_opportunity_acknowledged,
    confirmation_phrase,
):
    """Authorize irreversible purge; this is never an agent capability."""

    _require_human_owner_session(session_kind)
    if export_opportunity_acknowledged is not True:
        raise ChangeHistoryPolicyError("The human must acknowledge the company export opportunity before purge.")
    if not isinstance(soft_delete_record, dict) or soft_delete_record.get("historyClass") != COMPANY_SOFT_DELETE:
        raise ChangeHistoryPolicyError("A company soft-delete history record is required before permanent purge.")
    soft_delete = soft_delete_record.get("softDelete")
    if not isinstance(soft_delete, dict) or not soft_delete.get("isDeleted"):
        raise ChangeHistoryPolicyError("Only a currently soft-deleted company may be permanently purged.")
    company_id = _record_company(soft_delete_record)
    required_phrase = required_permanent_purge_confirmation(company_id)
    if confirmation_phrase != required_phrase:
        raise ChangeHistoryPolicyError("The permanent-purge confirmation phrase does not match.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "authorizationType": "permanent_company_purge",
        "companyId": company_id,
        "authorizedAt": _utc_text(authorized_at, "authorized_at"),
        "authorizedByHumanId": _required_text(human_actor_id, "human_actor_id"),
        "humanOwnerSessionVerified": True,
        "exportOpportunityAcknowledged": True,
        "irreversible": True,
        "removeUnderlyingCompanyData": True,
        "removeSoftDeleteMarkerAfterSuccessfulPurge": True,
    }
