import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import uuid
from urllib.parse import unquote, urlparse

from .config import PUBLIC_STORAGE_BYTES, ROOT, utc_now
from .security import evaluate_memory_firewall, redact_text


_LOCK = threading.RLock()


def _id(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value):
    encoded = json.dumps(value or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_size(value):
    return len(json.dumps(value or {}, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _public_value(value):
    if isinstance(value, dict):
        return {str(key): _public_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _blank_store():
    return {
        "schemaVersion": "memoryendpoints.file_store.v1",
        "createdAt": utc_now(),
        "accounts": {},
        "companies": {},
        "accountCompanies": {},
        "workspaces": {},
        "projects": {},
        "apiKeys": {},
        "agents": {},
        "memoryEvents": [],
        "reviewQueue": [],
        "messages": [],
        "notifications": [],
        "receipts": [],
        "outboxEvents": [],
        "storageLedger": [],
        "auditLog": [],
        "idempotency": {},
    }


def _normalize_store(data):
    blank = _blank_store()
    if not isinstance(data, dict):
        return blank
    for key, value in blank.items():
        data.setdefault(key, value)
    return data


class _ClosingConnection(object):
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        close = getattr(self.connection, "close", None)
        if close:
            close()
        return False


class FileStore(object):
    def __init__(self, path=None):
        self.path = path or os.environ.get("MEMORYENDPOINTS_STORE_PATH")
        if not self.path:
            from .config import STORE_PATH

            self.path = STORE_PATH
        if not hasattr(self.path, "exists"):
            from pathlib import Path

            self.path = Path(self.path)

    def healthcheck(self):
        self._load()
        return True

    def _load(self):
        with _LOCK:
            if not self.path.exists():
                return _blank_store()
            with self.path.open("r", encoding="utf-8") as handle:
                return _normalize_store(json.load(handle))

    def _save(self, data):
        with _LOCK:
            parent = self.path.parent
            if not parent.exists():
                parent.mkdir(parents=True)
            tmp = str(self.path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            try:
                os.replace(tmp, str(self.path))
            except PermissionError:
                with self.path.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, sort_keys=True)
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def audit(self, data, action, actor, target, workspace_id=None, details=None):
        data["auditLog"].append(
            {
                "auditId": _id("audit"),
                "workspaceId": workspace_id,
                "action": redact_text(action),
                "actor": redact_text(actor),
                "target": redact_text(target),
                "details": _public_value(details or {}),
                "createdAt": utc_now(),
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
            }
        )

    def record_audit(self, workspace_id, action, actor, target, details=None):
        data = self._load()
        self.audit(data, action, actor, target, workspace_id, details)
        self._save(data)

    def audit_log(self, workspace_id, limit=50, action=None):
        data = self._load()
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        action_filter = (action or "").strip()
        items = []
        for item in data.get("auditLog", []):
            if item.get("workspaceId") != workspace_id:
                continue
            if action_filter and item.get("action") != action_filter:
                continue
            items.append(
                {
                    "auditId": item.get("auditId"),
                    "workspaceId": item.get("workspaceId"),
                    "action": item.get("action"),
                    "actor": redact_text(item.get("actor") or ""),
                    "target": redact_text(item.get("target") or ""),
                    "details": _public_value(item.get("details") or {}),
                    "createdAt": item.get("createdAt"),
                    "valuesRedacted": True,
                    "rawCredentialExposed": False,
                    "rawPayloadExposed": False,
                }
            )
        items.sort(key=lambda item: item.get("createdAt") or "")
        return items[-limit_value:]

    def workspace_usage_bytes(self, data, workspace_id):
        usage = _json_size(data.get("workspaces", {}).get(workspace_id))
        workspace = data.get("workspaces", {}).get(workspace_id) or {}
        company_id = workspace.get("companyId")
        company = data.get("companies", {}).get(company_id)
        if company:
            usage += _json_size(company)
        for membership in data.get("accountCompanies", {}).values():
            if membership.get("companyId") == company_id:
                usage += _json_size(membership)
                account = data.get("accounts", {}).get(membership.get("accountId"))
                if account:
                    usage += _json_size(account)
        for project in data.get("projects", {}).values():
            if project.get("workspaceId") == workspace_id:
                usage += _json_size(project)
        for key in ("agents",):
            for item in data.get(key, {}).values():
                if item.get("workspaceId") == workspace_id:
                    usage += _json_size(item)
        for key in ("memoryEvents", "reviewQueue", "messages", "notifications", "receipts", "outboxEvents", "storageLedger"):
            for item in data.get(key, []):
                if item.get("workspaceId") == workspace_id:
                    usage += _json_size(item)
        return usage

    def workspace_status(self, workspace_id):
        data = self._load()
        workspace = data.get("workspaces", {}).get(workspace_id)
        if not workspace:
            return None
        used = self.workspace_usage_bytes(data, workspace_id)
        limit = int(workspace.get("storageLimitBytes") or PUBLIC_STORAGE_BYTES)
        company_id = workspace.get("companyId")
        company = data.get("companies", {}).get(company_id) or {}
        memberships = [
            membership
            for membership in data.get("accountCompanies", {}).values()
            if membership.get("companyId") == company_id
        ]
        memberships.sort(key=lambda item: item.get("createdAt") or "")
        account_items = []
        for membership in memberships:
            account = data.get("accounts", {}).get(membership.get("accountId"))
            if account:
                item = dict(account)
                item["role"] = membership.get("role")
                account_items.append(item)
        projects = [
            project
            for project in data.get("projects", {}).values()
            if project.get("workspaceId") == workspace_id
        ]
        projects.sort(key=lambda item: item.get("createdAt") or "")
        return {
            "workspaceId": workspace_id,
            "label": workspace.get("label"),
            "accountId": workspace.get("primaryAccountId"),
            "companyId": company_id,
            "primaryProjectId": workspace.get("primaryProjectId"),
            "company": {
                "companyId": company.get("companyId") or company_id,
                "label": company.get("label") or "Free Agent Company",
                "status": company.get("status") or "active",
            },
            "accounts": account_items,
            "accountCompanyMemberships": memberships,
            "projects": projects,
            "plan": workspace.get("plan"),
            "status": workspace.get("status"),
            "storageLimitBytes": limit,
            "storageUsedBytes": used,
            "storageRemainingBytes": max(0, limit - used),
            "quotaExceeded": used > limit,
            "rawKeyStoredByServer": False,
        }

    def has_quota_for(self, workspace_id, candidate):
        data = self._load()
        workspace = data.get("workspaces", {}).get(workspace_id)
        if not workspace:
            return False
        limit = int(workspace.get("storageLimitBytes") or PUBLIC_STORAGE_BYTES)
        return self.workspace_usage_bytes(data, workspace_id) + _json_size(candidate) <= limit

    def check_idempotency(self, workspace_id, key, operation, body):
        if not key:
            return None
        data = self._load()
        record_key = "%s:%s:%s" % (workspace_id, operation, key)
        record = data.get("idempotency", {}).get(record_key)
        if not record:
            return None
        if record.get("bodyHash") != _canonical_hash(body):
            return {
                "ok": False,
                "status": "idempotency_conflict",
                "safeNoOp": True,
                "valuesRedacted": True,
                "rawCredentialExposed": False,
                "rawPayloadExposed": False,
                "idempotencyKeyExposed": False,
                "error": {
                    "code": "idempotency_conflict",
                    "title": "Idempotency conflict",
                    "detail": "The same idempotency key was reused with a different request body.",
                    "safeNoOp": True,
                    "valuesRedacted": True,
                },
            }
        replay = dict(record.get("response") or {})
        replay["idempotentReplay"] = True
        replay["idempotencyKeyExposed"] = False
        replay["_httpStatus"] = record.get("httpStatus") or "200 OK"
        return replay

    def record_idempotency(self, workspace_id, key, operation, body, response, http_status="200 OK"):
        if not key:
            return
        data = self._load()
        record_key = "%s:%s:%s" % (workspace_id, operation, key)
        data.setdefault("idempotency", {})[record_key] = {
            "workspaceId": workspace_id,
            "operation": operation,
            "bodyHash": _canonical_hash(body),
            "response": response,
            "httpStatus": http_status,
            "createdAt": utc_now(),
            "idempotencyKeyExposed": False,
        }
        self._save(data)

    def create_free_account(self, label, company_label=None, project_label=None):
        data = self._load()
        created_at = utc_now()
        account_id = _id("account")
        company_id = _id("company")
        membership_id = _id("membership")
        workspace_id = _id("workspace")
        project_id = _id("project")
        token = "me_live_" + secrets.token_urlsafe(32)
        key_id = _id("key")
        data.setdefault("accounts", {})[account_id] = {
            "accountId": account_id,
            "label": redact_text((company_label or label or "Free Agent Account") + " Account"),
            "status": "active",
            "createdAt": created_at,
            "valuesRedacted": True,
        }
        data.setdefault("companies", {})[company_id] = {
            "companyId": company_id,
            "label": redact_text(company_label or label or "Free Agent Company"),
            "status": "active",
            "createdAt": created_at,
            "valuesRedacted": True,
        }
        data.setdefault("accountCompanies", {})[membership_id] = {
            "membershipId": membership_id,
            "accountId": account_id,
            "companyId": company_id,
            "role": "owner",
            "status": "active",
            "createdAt": created_at,
            "valuesRedacted": True,
        }
        data["workspaces"][workspace_id] = {
            "workspaceId": workspace_id,
            "primaryAccountId": account_id,
            "companyId": company_id,
            "primaryProjectId": project_id,
            "label": redact_text(label or "Free Agent Workspace"),
            "plan": "free_agent",
            "storageLimitBytes": PUBLIC_STORAGE_BYTES,
            "createdAt": created_at,
            "status": "active",
        }
        data.setdefault("projects", {})[project_id] = {
            "projectId": project_id,
            "workspaceId": workspace_id,
            "label": redact_text(project_label or "MemoryEndpoints Verification Project"),
            "status": "active",
            "createdAt": created_at,
            "valuesRedacted": True,
        }
        data["apiKeys"][key_id] = {
            "keyId": key_id,
            "workspaceId": workspace_id,
            "tokenHash": _hash(token),
            "createdAt": created_at,
            "lastUsedAt": None,
            "revokedAt": None,
        }
        self.audit(
            data,
            "workspace.create_free_account",
            "system",
            workspace_id,
            workspace_id,
            {
                "accountId": account_id,
                "companyId": company_id,
                "accountCompanyMembershipId": membership_id,
                "projectId": project_id,
            },
        )
        self._save(data)
        return workspace_id, key_id, token, account_id, company_id, project_id

    def authenticate(self, token, workspace_id=None):
        if not token:
            return None
        data = self._load()
        token_hash = _hash(token)
        for key in data["apiKeys"].values():
            if key.get("tokenHash") == token_hash and not key.get("revokedAt"):
                if workspace_id and key.get("workspaceId") != workspace_id:
                    return None
                key["lastUsedAt"] = utc_now()
                self._save(data)
                return {"workspaceId": key["workspaceId"], "keyId": key["keyId"]}
        return None

    def register_agent(self, workspace_id, agent_id, display_name):
        data = self._load()
        agent_key = "%s:%s" % (workspace_id, agent_id)
        data["agents"][agent_key] = {
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "displayName": display_name or agent_id,
            "registeredAt": utc_now(),
            "status": "active",
        }
        self.audit(data, "agent.register", agent_id, workspace_id, workspace_id)
        self._save(data)
        return data["agents"][agent_key]

    def _append_outbox(self, data, workspace_id, event_type, aggregate_type, aggregate_id, payload=None):
        item = {
            "outboxEventId": _id("outbox"),
            "workspaceId": workspace_id,
            "eventType": event_type,
            "aggregateType": aggregate_type,
            "aggregateId": aggregate_id,
            "payloadHash": _canonical_hash(payload or {}),
            "status": "pending",
            "createdAt": utc_now(),
            "valuesRedacted": True,
        }
        data.setdefault("outboxEvents", []).append(item)
        return item

    def _append_storage_ledger(self, data, workspace_id, object_type, object_id, value):
        item = {
            "ledgerId": _id("ledger"),
            "workspaceId": workspace_id,
            "objectType": object_type,
            "objectId": object_id,
            "bytesDelta": _json_size(value),
            "createdAt": utc_now(),
            "valuesRedacted": True,
        }
        data.setdefault("storageLedger", []).append(item)
        return item

    def submit_memory(self, workspace_id, actor_agent_id, scope, title, summary, tags, source, memory_type=None, subject=None, confidence=None, scope_id=None):
        data = self._load()
        memory_type = (memory_type or "decision").strip().lower()
        if memory_type not in ("fact", "decision", "status", "procedure", "risk", "evidence", "handoff", "note"):
            memory_type = "note"
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.75
        confidence_value = max(0.0, min(1.0, confidence_value))
        firewall = evaluate_memory_firewall(
            {
                "title": title,
                "summary": summary,
                "tags": tags or [],
                "source": source or "api",
                "memoryType": memory_type,
                "subject": subject or title,
            }
        )
        sanitized = firewall["sanitizedPayload"]
        redacted_tags = sanitized.get("tags") if isinstance(sanitized.get("tags"), list) else []
        event_status = "quarantined" if firewall["decision"] == "quarantine_for_review" else "active"
        review_status = "quarantined" if firewall["decision"] == "quarantine_for_review" else "pending"
        promotion_state = "quarantined" if event_status == "quarantined" else "review_pending"
        event = {
            "eventId": _id("mem"),
            "workspaceId": workspace_id,
            "actorAgentId": actor_agent_id,
            "scope": scope or "workspace",
            "scopeId": scope_id or workspace_id,
            "memoryType": memory_type,
            "subject": sanitized.get("subject") or redact_text(subject or title),
            "title": sanitized.get("title") or redact_text(title),
            "summary": sanitized.get("summary") or redact_text(summary),
            "tags": [redact_text(tag) for tag in redacted_tags],
            "source": sanitized.get("source") or "api",
            "confidence": confidence_value,
            "promotionState": promotion_state,
            "reviewStatus": review_status,
            "bodyHash": _canonical_hash(sanitized),
            "revision": 1,
            "firewall": {
                "schemaVersion": firewall["schemaVersion"],
                "decision": firewall["decision"],
                "riskScore": firewall["riskScore"],
                "detectedThreats": firewall["detectedThreats"],
                "valuesRedacted": firewall["valuesRedacted"],
            },
            "createdAt": utc_now(),
            "status": event_status,
            "rawPrivatePayloadStored": False,
            "valuesRedacted": True,
        }
        data["memoryEvents"].append(event)
        review = {
            "reviewId": _id("review"),
            "workspaceId": workspace_id,
            "memoryEventId": event["eventId"],
            "proposedByAgentId": actor_agent_id,
            "reviewType": "memory_promotion",
            "status": review_status,
            "publicSafeSummary": event["summary"][:1000],
            "firewallDecision": firewall["decision"],
            "riskScore": firewall["riskScore"],
            "detectedThreats": firewall["detectedThreats"],
            "createdAt": utc_now(),
            "decidedAt": None,
            "reviewerAgentId": None,
            "reviewerNoteHash": None,
            "valuesRedacted": True,
        }
        data.setdefault("reviewQueue", []).append(review)
        self._append_outbox(data, workspace_id, "matm.memory_event.submitted", "memory_event", event["eventId"], event)
        self._append_storage_ledger(data, workspace_id, "memory_event", event["eventId"], event)
        self.audit(data, "memory.submit", actor_agent_id, event["eventId"], workspace_id, {"reviewId": review["reviewId"], "firewallDecision": firewall["decision"]})
        self._save(data)
        return event

    def search_memory(self, workspace_id, query):
        data = self._load()
        q = (query or "").lower().strip()
        items = []
        for event in data["memoryEvents"]:
            if event.get("workspaceId") != workspace_id:
                continue
            if event.get("status") in ("rejected", "quarantined"):
                continue
            haystack = " ".join(
                [
                    event.get("title", ""),
                    event.get("summary", ""),
                    " ".join(event.get("tags", [])),
                    event.get("scope", ""),
                    event.get("scopeId", ""),
                ]
            ).lower()
            if not q or q in haystack:
                items.append(event)
        return items

    def review_queue(self, workspace_id, status=None):
        data = self._load()
        wanted = (status or "").strip().lower()
        items = []
        for item in data.get("reviewQueue", []):
            if item.get("workspaceId") != workspace_id:
                continue
            if wanted and item.get("status") != wanted:
                continue
            items.append(item)
        return items

    def decide_review(self, workspace_id, review_id, reviewer_agent_id, decision, review_note=None):
        data = self._load()
        normalized = (decision or "").strip().lower()
        target_status = {
            "promote": "promoted",
            "approve": "promoted",
            "reject": "rejected",
            "quarantine": "quarantined",
        }.get(normalized)
        if not target_status:
            return None, "invalid_decision"
        review = None
        for item in data.get("reviewQueue", []):
            if item.get("workspaceId") == workspace_id and item.get("reviewId") == review_id:
                review = item
                break
        if not review:
            return None, "not_found"
        review["status"] = target_status
        review["decidedAt"] = utc_now()
        review["reviewerAgentId"] = reviewer_agent_id
        review["reviewerNoteHash"] = _canonical_hash({"reviewNote": review_note or ""}) if review_note else None
        for event in data.get("memoryEvents", []):
            if event.get("workspaceId") == workspace_id and event.get("eventId") == review.get("memoryEventId"):
                event["reviewStatus"] = target_status
                event["promotionState"] = target_status
                event["status"] = "active" if target_status == "promoted" else target_status
                event["updatedAt"] = utc_now()
                break
        self._append_outbox(data, workspace_id, "matm.review.decision", "review_queue", review_id, review)
        self.audit(data, "review.decide", reviewer_agent_id, review_id, workspace_id, {"decision": target_status})
        self._save(data)
        return review, None

    def submit_message(self, workspace_id, sender_agent_id, target_agent_id, safe_summary, response_required):
        data = self._load()
        safe_summary = redact_text(safe_summary)
        message = {
            "messageId": _id("msg"),
            "workspaceId": workspace_id,
            "senderAgentId": sender_agent_id,
            "targetAgentId": target_agent_id,
            "safeSummary": safe_summary,
            "responseRequired": bool(response_required),
            "createdAt": utc_now(),
            "rawMessageBodyStored": False,
            "valuesRedacted": True,
        }
        note = {
            "notificationId": _id("note"),
            "workspaceId": workspace_id,
            "messageId": message["messageId"],
            "targetAgentId": target_agent_id,
            "status": "unread",
            "responseDisposition": "required_response" if response_required else "viewed_acknowledgement",
            "createdAt": utc_now(),
            "readAt": None,
        }
        data["messages"].append(message)
        data["notifications"].append(note)
        self._append_outbox(data, workspace_id, "matm.agent_message.submitted", "message", message["messageId"], message)
        self._append_storage_ledger(data, workspace_id, "message", message["messageId"], message)
        self.audit(data, "message.submit", sender_agent_id, message["messageId"], workspace_id)
        self._save(data)
        return message, note

    def inbox(self, workspace_id, agent_id):
        data = self._load()
        messages = []
        for note in data["notifications"]:
            if note.get("workspaceId") != workspace_id or note.get("status") != "unread":
                continue
            if note.get("targetAgentId") and note.get("targetAgentId") != agent_id:
                continue
            message = None
            for item in data["messages"]:
                if item.get("messageId") == note.get("messageId"):
                    message = item
                    break
            if message:
                messages.append({"notification": note, "message": message})
        return messages

    def receipts(self, workspace_id, consumer_agent_id=None):
        data = self._load()
        items = []
        for receipt in data["receipts"]:
            if receipt.get("workspaceId") != workspace_id:
                continue
            if consumer_agent_id and receipt.get("consumerAgentId") != consumer_agent_id:
                continue
            items.append(receipt)
        return items

    def ack(self, workspace_id, notification_id, consumer_agent_id, status):
        data = self._load()
        for note in data["notifications"]:
            if note.get("workspaceId") == workspace_id and note.get("notificationId") == notification_id:
                note["status"] = status or "read"
                note["readAt"] = utc_now()
                receipt = {
                    "receiptId": _id("receipt"),
                    "workspaceId": workspace_id,
                    "notificationId": notification_id,
                    "consumerAgentId": consumer_agent_id,
                    "status": note["status"],
                    "createdAt": utc_now(),
                    "rawPayloadExposed": False,
                    "valuesRedacted": True,
                }
                data["receipts"].append(receipt)
                self.audit(data, "notification.ack", consumer_agent_id, notification_id, workspace_id)
                self._save(data)
                return receipt
        return None


class SQLiteStore(FileStore):
    DELETE_ORDER = [
        "matm_search_documents",
        "matm_crawl_sources",
        "matm_memory_revisions",
        "matm_memory_tags",
        "matm_review_queue",
        "matm_receipts",
        "matm_notifications",
        "matm_messages",
        "matm_outbox_events",
        "matm_storage_ledger",
        "matm_audit_log",
        "matm_idempotency",
        "matm_agents",
        "matm_api_keys",
        "matm_memory_records",
        "matm_projects",
        "matm_workspaces",
        "matm_account_companies",
        "matm_companies",
        "matm_accounts",
    ]

    def __init__(self, path=None):
        self.path = path or os.environ.get("MEMORYENDPOINTS_SQLITE_PATH")
        if not self.path:
            from .config import SQLITE_PATH

            self.path = SQLITE_PATH
        if not hasattr(self.path, "exists"):
            from pathlib import Path

            self.path = Path(self.path)

    def _connect(self):
        parent = self.path.parent
        if not parent.exists():
            parent.mkdir(parents=True)
        connection = sqlite3.connect(str(self.path), timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=TRUNCATE")
        connection.execute("PRAGMA busy_timeout=20000")
        self._ensure_schema(connection)
        return connection

    def _open_connection(self):
        return _ClosingConnection(self._connect())

    def _ensure_schema(self, connection):
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS matm_accounts (
              account_id TEXT PRIMARY KEY,
              label TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS matm_companies (
              company_id TEXT PRIMARY KEY,
              label TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS matm_account_companies (
              membership_id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL,
              company_id TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT,
              UNIQUE (account_id, company_id),
              FOREIGN KEY (account_id) REFERENCES matm_accounts (account_id),
              FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_account_companies_account ON matm_account_companies (account_id);
            CREATE INDEX IF NOT EXISTS ix_sqlite_account_companies_company ON matm_account_companies (company_id);

            CREATE TABLE IF NOT EXISTS matm_workspaces (
              workspace_id TEXT PRIMARY KEY,
              company_id TEXT NOT NULL,
              label TEXT NOT NULL,
              plan TEXT NOT NULL,
              storage_limit_bytes INTEGER NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_workspaces_company ON matm_workspaces (company_id);

            CREATE TABLE IF NOT EXISTS matm_projects (
              project_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              label TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_projects_workspace ON matm_projects (workspace_id);

            CREATE TABLE IF NOT EXISTS matm_api_keys (
              key_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              token_hash TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              last_used_at TEXT,
              revoked_at TEXT,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_api_keys_workspace ON matm_api_keys (workspace_id);

            CREATE TABLE IF NOT EXISTS matm_agents (
              agent_record_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              display_name TEXT NOT NULL,
              status TEXT NOT NULL,
              registered_at TEXT NOT NULL,
              last_seen_at TEXT,
              UNIQUE (workspace_id, agent_id),
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_agents_workspace ON matm_agents (workspace_id);

            CREATE TABLE IF NOT EXISTS matm_memory_records (
              memory_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              actor_agent_id TEXT,
              scope_type TEXT NOT NULL,
              scope_id TEXT,
              memory_type TEXT NOT NULL,
              subject TEXT,
              title TEXT NOT NULL,
              public_safe_summary TEXT NOT NULL,
              source_uri TEXT,
              confidence REAL NOT NULL,
              promotion_state TEXT NOT NULL,
              review_status TEXT NOT NULL,
              body_hash TEXT NOT NULL,
              revision INTEGER NOT NULL,
              firewall_json TEXT NOT NULL,
              status TEXT NOT NULL,
              raw_private_payload_stored INTEGER NOT NULL DEFAULT 0,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_memory_workspace_status ON matm_memory_records (workspace_id, status, promotion_state);

            CREATE TABLE IF NOT EXISTS matm_memory_revisions (
              revision_id TEXT PRIMARY KEY,
              memory_id TEXT NOT NULL,
              revision_number INTEGER NOT NULL,
              public_safe_summary TEXT NOT NULL,
              change_summary TEXT NOT NULL,
              body_hash TEXT NOT NULL,
              created_by_agent_id TEXT,
              created_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              UNIQUE (memory_id, revision_number),
              FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_memory_revisions_memory ON matm_memory_revisions (memory_id, revision_number);

            CREATE TABLE IF NOT EXISTS matm_memory_tags (
              memory_id TEXT NOT NULL,
              tag TEXT NOT NULL,
              PRIMARY KEY (memory_id, tag),
              FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_memory_tags_tag ON matm_memory_tags (tag);

            CREATE TABLE IF NOT EXISTS matm_crawl_sources (
              source_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              project_id TEXT,
              source_uri TEXT NOT NULL,
              source_type TEXT NOT NULL,
              crawl_policy TEXT NOT NULL,
              status TEXT NOT NULL,
              last_crawled_at TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (project_id) REFERENCES matm_projects (project_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_crawl_workspace ON matm_crawl_sources (workspace_id, status);

            CREATE TABLE IF NOT EXISTS matm_search_documents (
              search_document_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              memory_id TEXT,
              source_id TEXT,
              route_or_path TEXT,
              title TEXT NOT NULL,
              searchable_text TEXT NOT NULL,
              visibility TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id),
              FOREIGN KEY (source_id) REFERENCES matm_crawl_sources (source_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_search_workspace_visibility ON matm_search_documents (workspace_id, visibility);

            CREATE TABLE IF NOT EXISTS matm_review_queue (
              review_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              memory_id TEXT,
              proposed_by_agent_id TEXT,
              review_type TEXT NOT NULL,
              status TEXT NOT NULL,
              public_safe_summary TEXT NOT NULL,
              firewall_decision TEXT,
              risk_score INTEGER,
              detected_threats_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              decided_at TEXT,
              reviewer_agent_id TEXT,
              reviewer_note_hash TEXT,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_review_workspace_status ON matm_review_queue (workspace_id, status);

            CREATE TABLE IF NOT EXISTS matm_messages (
              message_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              sender_agent_id TEXT NOT NULL,
              target_agent_id TEXT,
              safe_summary TEXT NOT NULL,
              response_required INTEGER NOT NULL,
              raw_message_body_stored INTEGER NOT NULL DEFAULT 0,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_messages_target ON matm_messages (workspace_id, target_agent_id, created_at);

            CREATE TABLE IF NOT EXISTS matm_notifications (
              notification_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              message_id TEXT NOT NULL,
              target_agent_id TEXT,
              status TEXT NOT NULL,
              response_disposition TEXT NOT NULL,
              created_at TEXT NOT NULL,
              read_at TEXT,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (message_id) REFERENCES matm_messages (message_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_notifications_target_status ON matm_notifications (workspace_id, target_agent_id, status);

            CREATE TABLE IF NOT EXISTS matm_receipts (
              receipt_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              notification_id TEXT NOT NULL,
              consumer_agent_id TEXT NOT NULL,
              status TEXT NOT NULL,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (notification_id) REFERENCES matm_notifications (notification_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_receipts_consumer ON matm_receipts (workspace_id, consumer_agent_id);

            CREATE TABLE IF NOT EXISTS matm_idempotency (
              record_key TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              operation TEXT NOT NULL,
              body_hash TEXT NOT NULL,
              response_json TEXT NOT NULL,
              http_status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              idempotency_key_exposed INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_idempotency_workspace ON matm_idempotency (workspace_id);

            CREATE TABLE IF NOT EXISTS matm_outbox_events (
              outbox_event_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              aggregate_type TEXT NOT NULL,
              aggregate_id TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_outbox_status_created ON matm_outbox_events (status, created_at);

            CREATE TABLE IF NOT EXISTS matm_storage_ledger (
              ledger_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              object_type TEXT NOT NULL,
              object_id TEXT NOT NULL,
              bytes_delta INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_storage_workspace_created ON matm_storage_ledger (workspace_id, created_at);

            CREATE TABLE IF NOT EXISTS matm_audit_log (
              audit_id TEXT PRIMARY KEY,
              workspace_id TEXT,
              action TEXT NOT NULL,
              actor TEXT,
              target TEXT,
              details_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_credential_exposed INTEGER NOT NULL DEFAULT 0,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_audit_workspace_created ON matm_audit_log (workspace_id, created_at);
            """
        )
        connection.commit()

    def _json_load(self, value, fallback):
        if value in (None, ""):
            return fallback
        try:
            return json.loads(value)
        except ValueError:
            return fallback

    def _json_dump(self, value):
        return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))

    def _bool(self, value):
        return bool(value)

    def _int_bool(self, value):
        return 1 if bool(value) else 0

    def _agent_record_id(self, workspace_id, agent_id):
        return "agent-" + _hash("%s:%s" % (workspace_id, agent_id))[:20]

    def _memory_revision_id(self, memory_id, revision_number):
        return "rev-" + _hash("%s:%s" % (memory_id, revision_number))[:20]

    def _load(self):
        with _LOCK:
            with self._open_connection() as connection:
                data = _blank_store()
                data["schemaVersion"] = "memoryendpoints.sqlite_relational_store.v1"

                for row in connection.execute("SELECT * FROM matm_accounts ORDER BY created_at, account_id"):
                    data["accounts"][row["account_id"]] = {
                        "accountId": row["account_id"],
                        "label": row["label"],
                        "status": row["status"],
                        "createdAt": row["created_at"],
                        "valuesRedacted": True,
                    }
                    if row["updated_at"]:
                        data["accounts"][row["account_id"]]["updatedAt"] = row["updated_at"]

                for row in connection.execute("SELECT * FROM matm_companies ORDER BY created_at, company_id"):
                    data["companies"][row["company_id"]] = {
                        "companyId": row["company_id"],
                        "label": row["label"],
                        "status": row["status"],
                        "createdAt": row["created_at"],
                        "valuesRedacted": True,
                    }
                    if row["updated_at"]:
                        data["companies"][row["company_id"]]["updatedAt"] = row["updated_at"]

                for row in connection.execute("SELECT * FROM matm_account_companies ORDER BY created_at, membership_id"):
                    data["accountCompanies"][row["membership_id"]] = {
                        "membershipId": row["membership_id"],
                        "accountId": row["account_id"],
                        "companyId": row["company_id"],
                        "role": row["role"],
                        "status": row["status"],
                        "createdAt": row["created_at"],
                        "valuesRedacted": True,
                    }
                    if row["updated_at"]:
                        data["accountCompanies"][row["membership_id"]]["updatedAt"] = row["updated_at"]

                for row in connection.execute("SELECT * FROM matm_workspaces ORDER BY created_at, workspace_id"):
                    data["workspaces"][row["workspace_id"]] = {
                        "workspaceId": row["workspace_id"],
                        "companyId": row["company_id"],
                        "label": row["label"],
                        "plan": row["plan"],
                        "storageLimitBytes": row["storage_limit_bytes"],
                        "createdAt": row["created_at"],
                        "status": row["status"],
                    }
                    if row["updated_at"]:
                        data["workspaces"][row["workspace_id"]]["updatedAt"] = row["updated_at"]
                    for membership in data["accountCompanies"].values():
                        if membership.get("companyId") == row["company_id"]:
                            data["workspaces"][row["workspace_id"]]["primaryAccountId"] = membership.get("accountId")
                            break

                for row in connection.execute("SELECT * FROM matm_projects ORDER BY created_at, project_id"):
                    data["projects"][row["project_id"]] = {
                        "projectId": row["project_id"],
                        "workspaceId": row["workspace_id"],
                        "label": row["label"],
                        "status": row["status"],
                        "createdAt": row["created_at"],
                        "valuesRedacted": True,
                    }
                    if row["updated_at"]:
                        data["projects"][row["project_id"]]["updatedAt"] = row["updated_at"]
                    workspace = data["workspaces"].get(row["workspace_id"])
                    if workspace and not workspace.get("primaryProjectId"):
                        workspace["primaryProjectId"] = row["project_id"]

                for row in connection.execute("SELECT * FROM matm_api_keys ORDER BY created_at, key_id"):
                    data["apiKeys"][row["key_id"]] = {
                        "keyId": row["key_id"],
                        "workspaceId": row["workspace_id"],
                        "tokenHash": row["token_hash"],
                        "createdAt": row["created_at"],
                        "lastUsedAt": row["last_used_at"],
                        "revokedAt": row["revoked_at"],
                    }

                for row in connection.execute("SELECT * FROM matm_agents ORDER BY registered_at, agent_id"):
                    key = "%s:%s" % (row["workspace_id"], row["agent_id"])
                    data["agents"][key] = {
                        "workspaceId": row["workspace_id"],
                        "agentId": row["agent_id"],
                        "displayName": row["display_name"],
                        "registeredAt": row["registered_at"],
                        "status": row["status"],
                    }

                tag_rows = {}
                for row in connection.execute("SELECT memory_id, tag FROM matm_memory_tags ORDER BY tag"):
                    tag_rows.setdefault(row["memory_id"], []).append(row["tag"])
                for row in connection.execute("SELECT * FROM matm_memory_records ORDER BY created_at, memory_id"):
                    event = {
                        "eventId": row["memory_id"],
                        "workspaceId": row["workspace_id"],
                        "actorAgentId": row["actor_agent_id"],
                        "scope": row["scope_type"],
                        "scopeId": row["scope_id"],
                        "memoryType": row["memory_type"],
                        "subject": row["subject"],
                        "title": row["title"],
                        "summary": row["public_safe_summary"],
                        "tags": tag_rows.get(row["memory_id"], []),
                        "source": row["source_uri"],
                        "confidence": row["confidence"],
                        "promotionState": row["promotion_state"],
                        "reviewStatus": row["review_status"],
                        "bodyHash": row["body_hash"],
                        "revision": row["revision"],
                        "firewall": self._json_load(row["firewall_json"], {}),
                        "createdAt": row["created_at"],
                        "status": row["status"],
                        "rawPrivatePayloadStored": self._bool(row["raw_private_payload_stored"]),
                        "valuesRedacted": self._bool(row["values_redacted"]),
                    }
                    if row["updated_at"]:
                        event["updatedAt"] = row["updated_at"]
                    data["memoryEvents"].append(event)

                for row in connection.execute("SELECT * FROM matm_review_queue ORDER BY created_at, review_id"):
                    data["reviewQueue"].append(
                        {
                            "reviewId": row["review_id"],
                            "workspaceId": row["workspace_id"],
                            "memoryEventId": row["memory_id"],
                            "proposedByAgentId": row["proposed_by_agent_id"],
                            "reviewType": row["review_type"],
                            "status": row["status"],
                            "publicSafeSummary": row["public_safe_summary"],
                            "firewallDecision": row["firewall_decision"],
                            "riskScore": row["risk_score"],
                            "detectedThreats": self._json_load(row["detected_threats_json"], []),
                            "createdAt": row["created_at"],
                            "decidedAt": row["decided_at"],
                            "reviewerAgentId": row["reviewer_agent_id"],
                            "reviewerNoteHash": row["reviewer_note_hash"],
                            "valuesRedacted": self._bool(row["values_redacted"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_messages ORDER BY created_at, message_id"):
                    data["messages"].append(
                        {
                            "messageId": row["message_id"],
                            "workspaceId": row["workspace_id"],
                            "senderAgentId": row["sender_agent_id"],
                            "targetAgentId": row["target_agent_id"],
                            "safeSummary": row["safe_summary"],
                            "responseRequired": self._bool(row["response_required"]),
                            "createdAt": row["created_at"],
                            "rawMessageBodyStored": self._bool(row["raw_message_body_stored"]),
                            "valuesRedacted": self._bool(row["values_redacted"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_notifications ORDER BY created_at, notification_id"):
                    data["notifications"].append(
                        {
                            "notificationId": row["notification_id"],
                            "workspaceId": row["workspace_id"],
                            "messageId": row["message_id"],
                            "targetAgentId": row["target_agent_id"],
                            "status": row["status"],
                            "responseDisposition": row["response_disposition"],
                            "createdAt": row["created_at"],
                            "readAt": row["read_at"],
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_receipts ORDER BY created_at, receipt_id"):
                    data["receipts"].append(
                        {
                            "receiptId": row["receipt_id"],
                            "workspaceId": row["workspace_id"],
                            "notificationId": row["notification_id"],
                            "consumerAgentId": row["consumer_agent_id"],
                            "status": row["status"],
                            "createdAt": row["created_at"],
                            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                            "valuesRedacted": self._bool(row["values_redacted"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_outbox_events ORDER BY created_at, outbox_event_id"):
                    data["outboxEvents"].append(
                        {
                            "outboxEventId": row["outbox_event_id"],
                            "workspaceId": row["workspace_id"],
                            "eventType": row["event_type"],
                            "aggregateType": row["aggregate_type"],
                            "aggregateId": row["aggregate_id"],
                            "payloadHash": row["payload_hash"],
                            "status": row["status"],
                            "createdAt": row["created_at"],
                            "valuesRedacted": self._bool(row["values_redacted"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_storage_ledger ORDER BY created_at, ledger_id"):
                    data["storageLedger"].append(
                        {
                            "ledgerId": row["ledger_id"],
                            "workspaceId": row["workspace_id"],
                            "objectType": row["object_type"],
                            "objectId": row["object_id"],
                            "bytesDelta": row["bytes_delta"],
                            "createdAt": row["created_at"],
                            "valuesRedacted": self._bool(row["values_redacted"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_audit_log ORDER BY created_at, audit_id"):
                    data["auditLog"].append(
                        {
                            "auditId": row["audit_id"],
                            "workspaceId": row["workspace_id"],
                            "action": row["action"],
                            "actor": row["actor"],
                            "target": row["target"],
                            "details": self._json_load(row["details_json"], {}),
                            "createdAt": row["created_at"],
                            "valuesRedacted": self._bool(row["values_redacted"]),
                            "rawCredentialExposed": self._bool(row["raw_credential_exposed"]),
                            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_idempotency ORDER BY created_at, record_key"):
                    data["idempotency"][row["record_key"]] = {
                        "workspaceId": row["workspace_id"],
                        "operation": row["operation"],
                        "bodyHash": row["body_hash"],
                        "response": self._json_load(row["response_json"], {}),
                        "httpStatus": row["http_status"],
                        "createdAt": row["created_at"],
                        "idempotencyKeyExposed": self._bool(row["idempotency_key_exposed"]),
                    }
                return _normalize_store(data)

    def _save(self, data):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    for table in self.DELETE_ORDER:
                        connection.execute("DELETE FROM %s" % table)

                    for account in data.get("accounts", {}).values():
                        connection.execute(
                            """
                            INSERT INTO matm_accounts (
                              account_id, label, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                account.get("accountId"),
                                account.get("label") or "Free Agent Account",
                                account.get("status") or "active",
                                account.get("createdAt") or utc_now(),
                                account.get("updatedAt"),
                            ),
                        )

                    for company in data.get("companies", {}).values():
                        connection.execute(
                            """
                            INSERT INTO matm_companies (
                              company_id, label, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                company.get("companyId"),
                                company.get("label") or "Free Agent Company",
                                company.get("status") or "active",
                                company.get("createdAt") or utc_now(),
                                company.get("updatedAt"),
                            ),
                        )

                    for membership in data.get("accountCompanies", {}).values():
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO matm_account_companies (
                              membership_id, account_id, company_id, role, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                membership.get("membershipId"),
                                membership.get("accountId"),
                                membership.get("companyId"),
                                membership.get("role") or "member",
                                membership.get("status") or "active",
                                membership.get("createdAt") or utc_now(),
                                membership.get("updatedAt"),
                            ),
                        )

                    for workspace in data.get("workspaces", {}).values():
                        connection.execute(
                            """
                            INSERT INTO matm_workspaces (
                              workspace_id, company_id, label, plan, storage_limit_bytes, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                workspace.get("workspaceId"),
                                workspace.get("companyId"),
                                workspace.get("label") or "Free Agent Workspace",
                                workspace.get("plan") or "free_agent",
                                int(workspace.get("storageLimitBytes") or PUBLIC_STORAGE_BYTES),
                                workspace.get("status") or "active",
                                workspace.get("createdAt") or utc_now(),
                                workspace.get("updatedAt"),
                            ),
                        )

                    for project in data.get("projects", {}).values():
                        connection.execute(
                            """
                            INSERT INTO matm_projects (
                              project_id, workspace_id, label, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                project.get("projectId"),
                                project.get("workspaceId"),
                                project.get("label") or "MemoryEndpoints Verification Project",
                                project.get("status") or "active",
                                project.get("createdAt") or utc_now(),
                                project.get("updatedAt"),
                            ),
                        )

                    for key_id, api_key in data.get("apiKeys", {}).items():
                        connection.execute(
                            """
                            INSERT INTO matm_api_keys (
                              key_id, workspace_id, token_hash, created_at, last_used_at, revoked_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                api_key.get("keyId") or key_id,
                                api_key.get("workspaceId"),
                                api_key.get("tokenHash"),
                                api_key.get("createdAt") or utc_now(),
                                api_key.get("lastUsedAt"),
                                api_key.get("revokedAt"),
                            ),
                        )

                    for agent in data.get("agents", {}).values():
                        workspace_id = agent.get("workspaceId")
                        agent_id = agent.get("agentId")
                        connection.execute(
                            """
                            INSERT INTO matm_agents (
                              agent_record_id, workspace_id, agent_id, display_name, status, registered_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                agent.get("agentRecordId") or self._agent_record_id(workspace_id, agent_id),
                                workspace_id,
                                agent_id,
                                agent.get("displayName") or agent_id,
                                agent.get("status") or "active",
                                agent.get("registeredAt") or utc_now(),
                                agent.get("lastSeenAt"),
                            ),
                        )

                    for event in data.get("memoryEvents", []):
                        memory_id = event.get("eventId")
                        connection.execute(
                            """
                            INSERT INTO matm_memory_records (
                              memory_id, workspace_id, actor_agent_id, scope_type, scope_id, memory_type, subject, title,
                              public_safe_summary, source_uri, confidence, promotion_state, review_status,
                              body_hash, revision, firewall_json, status, raw_private_payload_stored,
                              values_redacted, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                memory_id,
                                event.get("workspaceId"),
                                event.get("actorAgentId"),
                                event.get("scope") or "workspace",
                                event.get("scopeId") or event.get("workspaceId"),
                                event.get("memoryType") or "note",
                                event.get("subject"),
                                event.get("title") or "Untitled memory",
                                event.get("summary") or "",
                                event.get("source") or "api",
                                float(event.get("confidence") or 0),
                                event.get("promotionState") or "review_pending",
                                event.get("reviewStatus") or "pending",
                                event.get("bodyHash") or _canonical_hash(event),
                                int(event.get("revision") or 1),
                                self._json_dump(event.get("firewall") or {}),
                                event.get("status") or "active",
                                self._int_bool(event.get("rawPrivatePayloadStored")),
                                self._int_bool(event.get("valuesRedacted", True)),
                                event.get("createdAt") or utc_now(),
                                event.get("updatedAt"),
                            ),
                        )
                        revisions = event.get("revisions") or [
                            {
                                "revisionId": self._memory_revision_id(memory_id, int(event.get("revision") or 1)),
                                "revisionNumber": int(event.get("revision") or 1),
                                "publicSafeSummary": event.get("summary") or "",
                                "changeSummary": "initial memory submission",
                                "bodyHash": event.get("bodyHash") or _canonical_hash(event),
                                "createdByAgentId": event.get("actorAgentId"),
                                "createdAt": event.get("createdAt") or utc_now(),
                                "valuesRedacted": event.get("valuesRedacted", True),
                            }
                        ]
                        for revision in revisions:
                            revision_number = int(revision.get("revisionNumber") or revision.get("revision") or 1)
                            connection.execute(
                                """
                                INSERT OR REPLACE INTO matm_memory_revisions (
                                  revision_id, memory_id, revision_number, public_safe_summary,
                                  change_summary, body_hash, created_by_agent_id, created_at, values_redacted
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    revision.get("revisionId") or self._memory_revision_id(memory_id, revision_number),
                                    memory_id,
                                    revision_number,
                                    revision.get("publicSafeSummary") or revision.get("summary") or event.get("summary") or "",
                                    revision.get("changeSummary") or "memory revision",
                                    revision.get("bodyHash") or event.get("bodyHash") or _canonical_hash(event),
                                    revision.get("createdByAgentId") or event.get("actorAgentId"),
                                    revision.get("createdAt") or event.get("createdAt") or utc_now(),
                                    self._int_bool(revision.get("valuesRedacted", True)),
                                ),
                            )
                        for tag in event.get("tags") or []:
                            connection.execute(
                                "INSERT OR IGNORE INTO matm_memory_tags (memory_id, tag) VALUES (?, ?)",
                                (memory_id, redact_text(tag)),
                            )

                    for review in data.get("reviewQueue", []):
                        connection.execute(
                            """
                            INSERT INTO matm_review_queue (
                              review_id, workspace_id, memory_id, proposed_by_agent_id, review_type, status,
                              public_safe_summary, firewall_decision, risk_score, detected_threats_json,
                              created_at, decided_at, reviewer_agent_id, reviewer_note_hash, values_redacted
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                review.get("reviewId"),
                                review.get("workspaceId"),
                                review.get("memoryEventId"),
                                review.get("proposedByAgentId"),
                                review.get("reviewType") or "memory_promotion",
                                review.get("status") or "pending",
                                review.get("publicSafeSummary") or "",
                                review.get("firewallDecision"),
                                review.get("riskScore"),
                                json.dumps(review.get("detectedThreats") or [], sort_keys=True, separators=(",", ":")),
                                review.get("createdAt") or utc_now(),
                                review.get("decidedAt"),
                                review.get("reviewerAgentId"),
                                review.get("reviewerNoteHash"),
                                self._int_bool(review.get("valuesRedacted", True)),
                            ),
                        )

                    for message in data.get("messages", []):
                        connection.execute(
                            """
                            INSERT INTO matm_messages (
                              message_id, workspace_id, sender_agent_id, target_agent_id, safe_summary,
                              response_required, raw_message_body_stored, values_redacted, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                message.get("messageId"),
                                message.get("workspaceId"),
                                message.get("senderAgentId"),
                                message.get("targetAgentId"),
                                message.get("safeSummary") or "",
                                self._int_bool(message.get("responseRequired")),
                                self._int_bool(message.get("rawMessageBodyStored")),
                                self._int_bool(message.get("valuesRedacted", True)),
                                message.get("createdAt") or utc_now(),
                            ),
                        )

                    for note in data.get("notifications", []):
                        connection.execute(
                            """
                            INSERT INTO matm_notifications (
                              notification_id, workspace_id, message_id, target_agent_id, status,
                              response_disposition, created_at, read_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                note.get("notificationId"),
                                note.get("workspaceId"),
                                note.get("messageId"),
                                note.get("targetAgentId"),
                                note.get("status") or "unread",
                                note.get("responseDisposition") or "viewed_acknowledgement",
                                note.get("createdAt") or utc_now(),
                                note.get("readAt"),
                            ),
                        )

                    for receipt in data.get("receipts", []):
                        connection.execute(
                            """
                            INSERT INTO matm_receipts (
                              receipt_id, workspace_id, notification_id, consumer_agent_id, status,
                              raw_payload_exposed, values_redacted, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                receipt.get("receiptId"),
                                receipt.get("workspaceId"),
                                receipt.get("notificationId"),
                                receipt.get("consumerAgentId"),
                                receipt.get("status") or "read",
                                self._int_bool(receipt.get("rawPayloadExposed")),
                                self._int_bool(receipt.get("valuesRedacted", True)),
                                receipt.get("createdAt") or utc_now(),
                            ),
                        )

                    for item in data.get("outboxEvents", []):
                        connection.execute(
                            """
                            INSERT INTO matm_outbox_events (
                              outbox_event_id, workspace_id, event_type, aggregate_type, aggregate_id,
                              payload_hash, status, created_at, values_redacted
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item.get("outboxEventId"),
                                item.get("workspaceId"),
                                item.get("eventType"),
                                item.get("aggregateType"),
                                item.get("aggregateId"),
                                item.get("payloadHash") or _canonical_hash(item),
                                item.get("status") or "pending",
                                item.get("createdAt") or utc_now(),
                                self._int_bool(item.get("valuesRedacted", True)),
                            ),
                        )

                    for item in data.get("storageLedger", []):
                        connection.execute(
                            """
                            INSERT INTO matm_storage_ledger (
                              ledger_id, workspace_id, object_type, object_id, bytes_delta, created_at, values_redacted
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item.get("ledgerId"),
                                item.get("workspaceId"),
                                item.get("objectType"),
                                item.get("objectId"),
                                int(item.get("bytesDelta") or 0),
                                item.get("createdAt") or utc_now(),
                                self._int_bool(item.get("valuesRedacted", True)),
                            ),
                        )

                    for item in data.get("auditLog", []):
                        connection.execute(
                            """
                            INSERT INTO matm_audit_log (
                              audit_id, workspace_id, action, actor, target, details_json, created_at,
                              values_redacted, raw_credential_exposed, raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item.get("auditId"),
                                item.get("workspaceId"),
                                item.get("action"),
                                item.get("actor"),
                                item.get("target"),
                                self._json_dump(item.get("details") or {}),
                                item.get("createdAt") or utc_now(),
                                self._int_bool(item.get("valuesRedacted", True)),
                                self._int_bool(item.get("rawCredentialExposed")),
                                self._int_bool(item.get("rawPayloadExposed")),
                            ),
                        )

                    for record_key, item in data.get("idempotency", {}).items():
                        connection.execute(
                            """
                            INSERT INTO matm_idempotency (
                              record_key, workspace_id, operation, body_hash, response_json, http_status,
                              created_at, idempotency_key_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_key,
                                item.get("workspaceId"),
                                item.get("operation"),
                                item.get("bodyHash"),
                                self._json_dump(item.get("response") or {}),
                                item.get("httpStatus") or "200 OK",
                                item.get("createdAt") or utc_now(),
                                self._int_bool(item.get("idempotencyKeyExposed")),
                            ),
                        )


class _DbCursor(object):
    def __init__(self, cursor):
        self.cursor = cursor

    def __iter__(self):
        return iter(self.cursor.fetchall())

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class _DbConnection(object):
    def __init__(self, connection, dialect, cursor_options=None):
        self.connection = connection
        self.dialect = dialect
        self.cursor_options = cursor_options or {}
        self._depth = 0
        self._closed = False

    def _sql(self, sql):
        out = sql
        if self.dialect == "mysql":
            out = out.replace("INSERT OR REPLACE INTO", "REPLACE INTO")
            out = out.replace("INSERT OR IGNORE INTO", "INSERT IGNORE INTO")
            out = out.replace("?", "%s")
        return out

    def execute(self, sql, params=None):
        cursor = self.connection.cursor(**self.cursor_options)
        cursor.execute(self._sql(sql), params or ())
        return _DbCursor(cursor)

    def executescript(self, script):
        for statement in script.split(";"):
            sql = statement.strip()
            if sql:
                self.execute(sql)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self):
        self._depth += 1
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        if self._depth <= 1:
            if exc_type:
                self.rollback()
            else:
                self.commit()
            self._depth = 0
            self.close()
        else:
            self._depth -= 1
        return False


def _mysql_config_from_secret_file():
    configured = os.environ.get("MEMORYENDPOINTS_MYSQL_CONFIG_PATH")
    path = Path(configured) if configured else ROOT / ".local-secrets" / "mysql.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError("MySQL secret config file is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MySQL secret config file must contain a JSON object.")
    return {
        "host": payload.get("host") or "localhost",
        "port": int(payload.get("port") or 3306),
        "user": payload.get("user") or payload.get("username") or "",
        "password": payload.get("password") or "",
        "database": payload.get("database") or payload.get("db") or "",
    }


def _mysql_config_from_env():
    url = os.environ.get("MEMORYENDPOINTS_MYSQL_URL") or os.environ.get("DATABASE_URL")
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("mysql", "mariadb"):
            raise RuntimeError("MEMORYENDPOINTS_MYSQL_URL must use mysql:// or mariadb://.")
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": unquote(parsed.path.lstrip("/")),
        }
    config = {
        "host": os.environ.get("MEMORYENDPOINTS_MYSQL_HOST") or os.environ.get("MYSQL_HOST") or "localhost",
        "port": int(os.environ.get("MEMORYENDPOINTS_MYSQL_PORT") or os.environ.get("MYSQL_PORT") or "3306"),
        "user": os.environ.get("MEMORYENDPOINTS_MYSQL_USER") or os.environ.get("MYSQL_USER") or "",
        "password": os.environ.get("MEMORYENDPOINTS_MYSQL_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or "",
        "database": os.environ.get("MEMORYENDPOINTS_MYSQL_DATABASE") or os.environ.get("MYSQL_DATABASE") or "",
    }
    if config["user"] or config["password"] or config["database"]:
        return config
    file_config = _mysql_config_from_secret_file()
    if file_config:
        file_config.setdefault("host", config["host"])
        file_config.setdefault("port", config["port"])
        return file_config
    return config


class MySQLStore(SQLiteStore):
    def _connect(self):
        config = _mysql_config_from_env()
        missing = [key for key in ("user", "password", "database") if not config.get(key)]
        if missing:
            raise RuntimeError("MySQL backend is selected but required database settings are missing.")
        try:
            import pymysql

            connection = pymysql.connect(
                host=config["host"],
                port=int(config["port"]),
                user=config["user"],
                password=config["password"],
                database=config["database"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
        except ImportError:
            try:
                import mysql.connector
            except ImportError as exc:
                raise RuntimeError("MySQL backend is selected but no MySQL Python driver is installed.") from exc
            connection = mysql.connector.connect(
                host=config["host"],
                port=int(config["port"]),
                user=config["user"],
                password=config["password"],
                database=config["database"],
            )
        cursor_options = {}
        if connection.__class__.__module__.startswith("mysql.connector"):
            cursor_options = {"dictionary": True}
        wrapped = _DbConnection(connection, "mysql", cursor_options)
        self._ensure_schema(wrapped)
        return wrapped

    def _ensure_schema(self, connection):
        schema = (Path(__file__).resolve().parents[1] / "docs" / "database-schema-canonical.sql").read_text(encoding="utf-8")
        connection.executescript(schema)
        connection.commit()
