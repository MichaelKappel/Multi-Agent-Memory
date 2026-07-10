import hashlib
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from urllib.parse import unquote, urlparse

from .config import PUBLIC_STORAGE_BYTES, ROOT, utc_now
from .security import evaluate_memory_firewall, redact_text


_LOCK = threading.RLock()
SQL_READ_AFTER_WRITE_RETRY_DELAYS = (0.05, 0.15, 0.35)
_MYSQL_SCHEMA_READY = set()


def _id(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _time_ordered_id(prefix):
    return "%s-%020d-%s" % (prefix, time.time_ns(), uuid.uuid4().hex[:8])


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


def _search_tokens(query):
    return [token for token in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(token) >= 2]


def _memory_query_matches(query, haystack):
    q = (query or "").lower().strip()
    if not q:
        return True
    if q in haystack:
        return True
    tokens = _search_tokens(q)
    return bool(tokens) and all(token in haystack for token in tokens)


def _audit_detail_summary(details):
    safe = _public_value(details or {})
    if not isinstance(safe, dict):
        return []
    items = []
    method = safe.get("method") or ""
    route = safe.get("route") or ""
    if method or route:
        items.append(("%s %s" % (method, route)).strip())
    for key, label in (
        ("count", "count"),
        ("memoryCount", "memory"),
        ("unreadCount", "unread"),
        ("limit", "limit"),
    ):
        if safe.get(key) not in (None, ""):
            items.append("%s %s" % (label, safe.get(key)))
    if safe.get("memorySource"):
        items.append("source %s" % safe.get("memorySource"))
    if safe.get("roomScope"):
        items.append("room %s" % safe.get("roomScope"))
    if safe.get("meetingRoomCount") not in (None, ""):
        items.append("meeting rooms %s" % (safe.get("meetingRoomCount") or 0))
    if safe.get("meetingMessageCount") not in (None, ""):
        items.append("meeting messages %s" % (safe.get("meetingMessageCount") or 0))
    if safe.get("unreadMeetingCount") not in (None, ""):
        items.append("meeting unread %s" % (safe.get("unreadMeetingCount") or 0))
    if safe.get("routingDecisionCount") not in (None, ""):
        items.append("routing decisions %s" % (safe.get("routingDecisionCount") or 0))
    if safe.get("routedAgentId"):
        items.append("routed %s" % safe.get("routedAgentId"))
    if safe.get("routingLane"):
        items.append("lane %s" % safe.get("routingLane"))
    if safe.get("statusFilter"):
        items.append("status %s" % safe.get("statusFilter"))
    if safe.get("actionFilter"):
        items.append("action %s" % safe.get("actionFilter"))
    long_term_reviews = safe.get("longTermMemoryReviews")
    if isinstance(long_term_reviews, dict):
        if long_term_reviews.get("sourcePathCount") not in (None, ""):
            duplicate_suffix = ""
            if long_term_reviews.get("duplicateRecordCount"):
                duplicate_suffix = " / %s duplicates" % long_term_reviews.get("duplicateRecordCount")
            items.append(
                "long-term reviews %s sources / %s actionable%s"
                % (
                    long_term_reviews.get("sourcePathCount") or 0,
                    long_term_reviews.get("actionableCount") or 0,
                    duplicate_suffix,
                )
            )
    if safe.get("hierarchyReady") is not None:
        items.append("hierarchy ready" if safe.get("hierarchyReady") else "hierarchy incomplete")
    filter_keys = safe.get("filterKeys")
    if isinstance(filter_keys, list) and filter_keys:
        items.append("filters %s" % ", ".join(str(item) for item in filter_keys[:4]))
    filters = safe.get("filters")
    if isinstance(filters, dict):
        for key in sorted(filters.keys())[:4]:
            value = filters.get(key)
            if value not in (None, ""):
                items.append("%s %s" % (key, value))
    delivery_counts = safe.get("deliveryCounts")
    if isinstance(delivery_counts, dict):
        items.append(
            "delivery %s broadcast / %s targeted"
            % (delivery_counts.get("broadcast") or 0, delivery_counts.get("targeted") or 0)
        )
    response_disposition_counts = safe.get("responseDispositionCounts")
    if isinstance(response_disposition_counts, dict):
        items.append(
            "responses %s required / %s ack"
            % (
                response_disposition_counts.get("required_response") or 0,
                response_disposition_counts.get("viewed_acknowledgement") or 0,
            )
        )
    scope_counts = safe.get("scopeCounts")
    if isinstance(scope_counts, dict):
        active = ["%s %s" % (key, scope_counts.get(key)) for key in ("account", "company", "workspace", "project") if scope_counts.get(key)]
        if active:
            items.append("scopes %s" % ", ".join(active))
    review_status_counts = safe.get("reviewStatusCounts")
    if isinstance(review_status_counts, dict):
        active = ["%s %s" % (key, review_status_counts.get(key)) for key in ("pending", "quarantined", "promoted", "rejected") if review_status_counts.get(key)]
        if active:
            items.append("reviews %s" % ", ".join(active))
    firewall_decision_counts = safe.get("firewallDecisionCounts")
    if isinstance(firewall_decision_counts, dict):
        active = ["%s %s" % (key, firewall_decision_counts.get(key)) for key in sorted(firewall_decision_counts.keys()) if firewall_decision_counts.get(key)]
        if active:
            items.append("firewall %s" % ", ".join(active[:3]))
    if safe.get("detectedThreatCount") not in (None, ""):
        items.append("threats %s" % (safe.get("detectedThreatCount") or 0))
    receipt_status_counts = safe.get("receiptStatusCounts")
    if isinstance(receipt_status_counts, dict):
        active = ["%s %s" % (key, receipt_status_counts.get(key)) for key in ("read", "unread", "acknowledged") if receipt_status_counts.get(key)]
        if active:
            items.append("receipts %s" % ", ".join(active))
    if safe.get("rawPayloadExposedCount") not in (None, ""):
        items.append("payloads %s exposed" % (safe.get("rawPayloadExposedCount") or 0))
    return items[:8]


def _public_memory_event(event):
    item = dict(event or {})
    firewall = dict(item.get("firewall") or {})
    if firewall:
        firewall.setdefault("redactionApplied", bool(firewall.get("valuesRedacted")))
        firewall["valuesRedacted"] = True
        item["firewall"] = firewall
    item["valuesRedacted"] = True
    item["rawPrivatePayloadStored"] = False
    return item


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
        "meetingRooms": {},
        "meetingMessages": [],
        "meetingReads": [],
        "routingDecisions": [],
        "syncDevices": {},
        "syncHeads": {},
        "syncRevisions": [],
        "syncReceipts": [],
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
                "detailsSummary": _audit_detail_summary(details),
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
                    "detailsSummary": _audit_detail_summary(item.get("details") or {}),
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
        for key in ("memoryEvents", "reviewQueue", "messages", "notifications", "receipts", "meetingMessages", "meetingReads", "outboxEvents", "storageLedger"):
            for item in data.get(key, []):
                if item.get("workspaceId") == workspace_id:
                    usage += _json_size(item)
        for room in data.get("meetingRooms", {}).values():
            if room.get("workspaceId") == workspace_id:
                usage += _json_size(room)
        return usage

    def _meeting_room_id(self, workspace_id, scope, scope_id):
        return "room-" + _hash("%s:%s:%s" % (workspace_id, scope, scope_id))[:20]

    def _meeting_read_id(self, workspace_id, room_id, agent_id):
        return "meetread-" + _hash("%s:%s:%s" % (workspace_id, room_id, agent_id))[:20]

    def _default_meeting_room_specs(self, data, workspace_id):
        workspace = data.get("workspaces", {}).get(workspace_id) or {}
        if not workspace:
            return []
        company_id = workspace.get("companyId")
        company = data.get("companies", {}).get(company_id) or {}
        projects = [
            project
            for project in data.get("projects", {}).values()
            if project.get("workspaceId") == workspace_id
        ]
        projects.sort(key=lambda item: item.get("createdAt") or "")
        specs = [
            {
                "scope": "company",
                "scopeId": company_id,
                "label": "Company-wide meeting",
                "name": "%s welcome and routing meeting" % (company.get("label") or "Company"),
                "purpose": "Highest-level welcome room for new agents to state who they are, why they are here, what they are working on, and which workspace, project, goal, or task room they should be routed into.",
            },
            {
                "scope": "workspace",
                "scopeId": workspace_id,
                "label": "Workspace-wide meeting",
                "name": "%s workspace meeting" % (workspace.get("label") or "Workspace"),
                "purpose": "Workspace operating room for active coordination, shared context, and cross-project routing after company-level intake.",
            },
        ]
        for project in projects:
            specs.append(
                {
                    "scope": "project",
                    "scopeId": project.get("projectId"),
                    "label": "Project-wide meeting",
                    "name": "%s project meeting" % (project.get("label") or "Project"),
                    "purpose": "Project implementation room for assigned work, decisions, blockers, and handoff after intake routing.",
                }
            )
        return [spec for spec in specs if spec.get("scopeId")]

    def _ensure_default_meeting_rooms(self, data, workspace_id):
        data.setdefault("meetingRooms", {})
        created = []
        for spec in self._default_meeting_room_specs(data, workspace_id):
            room_id = self._meeting_room_id(workspace_id, spec["scope"], spec["scopeId"])
            if room_id in data["meetingRooms"]:
                room = data["meetingRooms"][room_id]
                room.setdefault("workspaceId", workspace_id)
                room.setdefault("roomId", room_id)
                room.setdefault("scope", spec["scope"])
                room.setdefault("scopeId", spec["scopeId"])
                room.setdefault("status", "active")
                room.setdefault("defaultRoom", True)
                room.setdefault("alwaysAvailable", True)
                room.setdefault("valuesRedacted", True)
                continue
            room = {
                "roomId": room_id,
                "workspaceId": workspace_id,
                "scope": spec["scope"],
                "scopeId": spec["scopeId"],
                "label": spec["label"],
                "name": redact_text(spec["name"]),
                "purpose": redact_text(spec["purpose"]),
                "status": "active",
                "defaultRoom": True,
                "alwaysAvailable": True,
                "createdAt": utc_now(),
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            }
            data["meetingRooms"][room_id] = room
            created.append(room)
        return created

    def _meeting_messages_for_room(self, data, workspace_id, room_id):
        messages = [
            item
            for item in data.get("meetingMessages", [])
            if item.get("workspaceId") == workspace_id and item.get("roomId") == room_id
        ]
        messages.sort(key=lambda item: (item.get("createdAt") or "", item.get("meetingMessageId") or ""))
        return messages

    def _meeting_read_state(self, data, workspace_id, room_id, agent_id):
        if not agent_id:
            return None
        for item in data.get("meetingReads", []):
            if item.get("workspaceId") == workspace_id and item.get("roomId") == room_id and item.get("agentId") == agent_id:
                return item
        return None

    def _meeting_unread_count(self, data, workspace_id, room_id, agent_id):
        messages = self._meeting_messages_for_room(data, workspace_id, room_id)
        read_state = self._meeting_read_state(data, workspace_id, room_id, agent_id) or {}
        last_read_at = read_state.get("lastReadAt") or ""
        last_read_id = read_state.get("lastMeetingMessageId") or ""
        if not agent_id:
            return 0
        unread = 0
        seen_last_id = not last_read_id
        for message in messages:
            if last_read_id and message.get("meetingMessageId") == last_read_id:
                seen_last_id = True
                continue
            if last_read_at and (message.get("createdAt") or "") <= last_read_at:
                continue
            if seen_last_id or not last_read_at:
                unread += 1
        return unread

    def meeting_rooms(self, workspace_id, agent_id=None):
        data = self._load()
        created = self._ensure_default_meeting_rooms(data, workspace_id)
        if created:
            self.audit(
                data,
                "meeting_rooms.ensure_defaults",
                "system",
                workspace_id,
                workspace_id,
                {"meetingRoomCount": len(created)},
            )
            self._save(data)
        rooms = []
        scope_order = {"company": 0, "workspace": 1, "project": 2, "goal": 3, "task": 4}
        for room in data.get("meetingRooms", {}).values():
            if room.get("workspaceId") != workspace_id or room.get("status") != "active":
                continue
            item = dict(room)
            messages = self._meeting_messages_for_room(data, workspace_id, room.get("roomId"))
            item["messageCount"] = len(messages)
            item["lastMessageAt"] = messages[-1].get("createdAt") if messages else None
            item["unreadCount"] = self._meeting_unread_count(data, workspace_id, room.get("roomId"), agent_id)
            item["readState"] = self._meeting_read_state(data, workspace_id, room.get("roomId"), agent_id) or {}
            item["valuesRedacted"] = True
            item["rawPayloadExposed"] = False
            rooms.append(item)
        rooms.sort(key=lambda item: (scope_order.get(item.get("scope"), 99), item.get("name") or "", item.get("roomId") or ""))
        return rooms

    def create_meeting_room(self, workspace_id, scope, scope_id, label=None, name=None, purpose=None, creator_agent_id=None):
        data = self._load()
        self._ensure_default_meeting_rooms(data, workspace_id)
        data.setdefault("meetingRooms", {})
        scope = (scope or "").strip().lower()
        scope_id = str(scope_id or "").strip()
        room_id = self._meeting_room_id(workspace_id, scope, scope_id)
        now = utc_now()
        default_label = "%s coordination room" % scope.title()
        default_name = "%s %s meeting" % (scope.title(), scope_id)
        default_purpose = "%s-level coordination room for assigned agents, blockers, evidence, and handoff." % scope.title()
        existing = data["meetingRooms"].get(room_id)
        created = existing is None
        room = existing or {
            "roomId": room_id,
            "workspaceId": workspace_id,
            "scope": scope,
            "scopeId": scope_id,
            "createdAt": now,
        }
        room.update(
            {
                "label": redact_text(label or room.get("label") or default_label),
                "name": redact_text(name or room.get("name") or default_name),
                "purpose": redact_text(purpose or room.get("purpose") or default_purpose),
                "status": "active",
                "defaultRoom": False,
                "alwaysAvailable": True,
                "valuesRedacted": True,
                "rawPayloadExposed": False,
                "updatedAt": now,
            }
        )
        data["meetingRooms"][room_id] = room
        self._append_storage_ledger(data, workspace_id, "meeting_room", room_id, room)
        self.audit(
            data,
            "meeting_room.create" if created else "meeting_room.update",
            creator_agent_id or "system",
            room_id,
            workspace_id,
            {"roomScope": scope, "scopeId": scope_id, "created": created},
        )
        self._save(data)
        return dict(room), created

    def meeting_messages(self, workspace_id, room_id, agent_id=None, limit=50):
        data = self._load()
        created = self._ensure_default_meeting_rooms(data, workspace_id)
        if created:
            self._save(data)
        room = data.get("meetingRooms", {}).get(room_id)
        if not room or room.get("workspaceId") != workspace_id or room.get("status") != "active":
            return None, [], None
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        messages = self._meeting_messages_for_room(data, workspace_id, room_id)[-limit_value:]
        read_state = self._meeting_read_state(data, workspace_id, room_id, agent_id) or {}
        return dict(room), messages, read_state

    def meeting_message(self, workspace_id, meeting_message_id):
        data = self._load()
        meeting_message_id = str(meeting_message_id or "").strip()
        if not meeting_message_id:
            return None, None
        for message in data.get("meetingMessages", []):
            if message.get("workspaceId") == workspace_id and message.get("meetingMessageId") == meeting_message_id:
                room = data.get("meetingRooms", {}).get(message.get("roomId")) or {}
                return dict(message), dict(room)
        return None, None

    def routing_decisions(self, workspace_id, filters=None, limit=50):
        data = self._load()
        filters = filters or {}
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        key_pairs = (
            ("roomId", "sourceRoomId"),
            ("sourceRoomId", "sourceRoomId"),
            ("destinationRoomId", "destinationRoomId"),
            ("routedAgentId", "routedAgentId"),
            ("coordinatorAgentId", "coordinatorAgentId"),
            ("lane", "lane"),
            ("destinationScope", "destinationScope"),
            ("destinationScopeId", "destinationScopeId"),
            ("status", "status"),
        )
        items = []
        for item in data.get("routingDecisions", []):
            if item.get("workspaceId") != workspace_id:
                continue
            matched = True
            for filter_key, item_key in key_pairs:
                value = filters.get(filter_key)
                if value and item.get(item_key) != value:
                    matched = False
                    break
            if matched:
                items.append(dict(item))
        return items[-limit_value:]

    def submit_routing_decision(
        self,
        workspace_id,
        source_room_id,
        coordinator_agent_id,
        routed_agent_id,
        lane,
        destination_room_id,
        specific_goal,
        expected_evidence,
        next_action,
        support_plan,
        safe_summary,
    ):
        data = self._load()
        self._ensure_default_meeting_rooms(data, workspace_id)
        source_room = data.get("meetingRooms", {}).get(source_room_id)
        destination_room = data.get("meetingRooms", {}).get(destination_room_id)
        if (
            not source_room
            or source_room.get("workspaceId") != workspace_id
            or source_room.get("status") != "active"
            or not destination_room
            or destination_room.get("workspaceId") != workspace_id
            or destination_room.get("status") != "active"
        ):
            return None, None, None, None
        now = utc_now()
        message = {
            "meetingMessageId": _time_ordered_id("meetmsg"),
            "workspaceId": workspace_id,
            "roomId": source_room_id,
            "scope": source_room.get("scope"),
            "scopeId": source_room.get("scopeId"),
            "senderAgentId": coordinator_agent_id,
            "safeSummary": redact_text(safe_summary),
            "createdAt": now,
            "rawMessageBodyStored": False,
            "valuesRedacted": True,
            "rawPayloadExposed": False,
        }
        decision = {
            "routingDecisionId": _time_ordered_id("route"),
            "workspaceId": workspace_id,
            "sourceRoomId": source_room_id,
            "destinationRoomId": destination_room_id,
            "destinationScope": destination_room.get("scope"),
            "destinationScopeId": destination_room.get("scopeId"),
            "coordinatorAgentId": redact_text(coordinator_agent_id),
            "routedAgentId": redact_text(routed_agent_id),
            "lane": redact_text(lane),
            "specificGoal": redact_text(specific_goal),
            "expectedEvidence": [redact_text(str(item)) for item in (expected_evidence or [])],
            "nextAction": redact_text(next_action),
            "supportPlan": redact_text(support_plan),
            "meetingMessageId": message["meetingMessageId"],
            "status": "active",
            "createdAt": now,
            "valuesRedacted": True,
            "rawPayloadExposed": False,
        }
        data.setdefault("meetingMessages", []).append(message)
        data.setdefault("routingDecisions", []).append(decision)
        self._append_outbox(data, workspace_id, "matm.meeting_message.submitted", "meeting_message", message["meetingMessageId"], message)
        self._append_outbox(data, workspace_id, "matm.routing_decision.submitted", "routing_decision", decision["routingDecisionId"], decision)
        self._append_storage_ledger(data, workspace_id, "meeting_message", message["meetingMessageId"], message)
        self._append_storage_ledger(data, workspace_id, "routing_decision", decision["routingDecisionId"], decision)
        self.audit(
            data,
            "routing_decision.submit",
            coordinator_agent_id,
            decision["routingDecisionId"],
            workspace_id,
            {
                "roomScope": source_room.get("scope"),
                "routingDecisionCount": 1,
                "routedAgentId": routed_agent_id,
                "routingLane": lane,
            },
        )
        self._save(data)
        return decision, message, dict(source_room), dict(destination_room)

    def submit_meeting_message(self, workspace_id, room_id, sender_agent_id, safe_summary):
        data = self._load()
        self._ensure_default_meeting_rooms(data, workspace_id)
        room = data.get("meetingRooms", {}).get(room_id)
        if not room or room.get("workspaceId") != workspace_id or room.get("status") != "active":
            return None, None
        safe_summary = redact_text(safe_summary)
        message = {
            "meetingMessageId": _time_ordered_id("meetmsg"),
            "workspaceId": workspace_id,
            "roomId": room_id,
            "scope": room.get("scope"),
            "scopeId": room.get("scopeId"),
            "senderAgentId": sender_agent_id,
            "safeSummary": safe_summary,
            "createdAt": utc_now(),
            "rawMessageBodyStored": False,
            "valuesRedacted": True,
            "rawPayloadExposed": False,
        }
        data.setdefault("meetingMessages", []).append(message)
        self._append_outbox(data, workspace_id, "matm.meeting_message.submitted", "meeting_message", message["meetingMessageId"], message)
        self._append_storage_ledger(data, workspace_id, "meeting_message", message["meetingMessageId"], message)
        self.audit(
            data,
            "meeting_message.submit",
            sender_agent_id,
            message["meetingMessageId"],
            workspace_id,
            {"roomScope": room.get("scope"), "meetingMessageCount": 1},
        )
        self._save(data)
        return message, dict(room)

    def mark_meeting_room_read(self, workspace_id, room_id, agent_id, last_meeting_message_id=None):
        data = self._load()
        self._ensure_default_meeting_rooms(data, workspace_id)
        room = data.get("meetingRooms", {}).get(room_id)
        if not room or room.get("workspaceId") != workspace_id or room.get("status") != "active":
            return None, None
        messages = self._meeting_messages_for_room(data, workspace_id, room_id)
        if last_meeting_message_id:
            selected = None
            for message in messages:
                if message.get("meetingMessageId") == last_meeting_message_id:
                    selected = message
                    break
            if not selected:
                return None, "message_not_found"
        else:
            selected = messages[-1] if messages else None
            last_meeting_message_id = selected.get("meetingMessageId") if selected else ""
        read_id = self._meeting_read_id(workspace_id, room_id, agent_id)
        read_state = None
        for item in data.setdefault("meetingReads", []):
            if item.get("meetingReadId") == read_id:
                read_state = item
                break
        if not read_state:
            read_state = {
                "meetingReadId": read_id,
                "workspaceId": workspace_id,
                "roomId": room_id,
                "agentId": agent_id,
                "createdAt": utc_now(),
                "valuesRedacted": True,
            }
            data["meetingReads"].append(read_state)
        read_state.update(
            {
                "lastMeetingMessageId": last_meeting_message_id,
                "lastReadAt": selected.get("createdAt") if selected else utc_now(),
                "readMessageCount": len(messages),
                "updatedAt": utc_now(),
                "status": "read",
                "rawPayloadExposed": False,
                "valuesRedacted": True,
            }
        )
        self.audit(
            data,
            "meeting_room.read",
            agent_id,
            room_id,
            workspace_id,
            {"roomScope": room.get("scope"), "meetingMessageCount": len(messages), "unreadMeetingCount": 0},
        )
        self._save(data)
        return dict(read_state), None

    def workspace_status(self, workspace_id):
        data = self._load()
        workspace = data.get("workspaces", {}).get(workspace_id)
        if not workspace:
            return None
        created_rooms = self._ensure_default_meeting_rooms(data, workspace_id)
        if created_rooms:
            self.audit(
                data,
                "meeting_rooms.ensure_defaults",
                "system",
                workspace_id,
                workspace_id,
                {"meetingRoomCount": len(created_rooms)},
            )
            self._save(data)
            data = self._load()
            workspace = data.get("workspaces", {}).get(workspace_id)
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
        meeting_rooms = self.meeting_rooms(workspace_id)
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
            "meetingRooms": meeting_rooms,
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

    def _sync_device_key(self, workspace_id, device_id):
        return "%s:%s" % (workspace_id, device_id)

    def _sync_head_key(self, workspace_id, logical_memory_id):
        return "%s:%s" % (workspace_id, logical_memory_id)

    def _sync_next_sequence(self, data, workspace_id):
        current = 0
        for revision in data.get("syncRevisions", []):
            if revision.get("workspaceId") == workspace_id:
                current = max(current, int(revision.get("serverSequence") or 0))
        return current + 1

    def _public_sync_revision(self, revision):
        item = dict(revision or {})
        item["valuesRedacted"] = True
        item["rawPayloadExposed"] = False
        return item

    def _public_sync_receipt(self, receipt):
        item = dict(receipt or {})
        item["idempotencyKeyExposed"] = False
        item["valuesRedacted"] = True
        item["rawCredentialExposed"] = False
        item["rawPayloadExposed"] = False
        return item

    def register_sync_device(self, workspace_id, agent_id, device_id=None, label=None):
        data = self._load()
        now = utc_now()
        device_id = (device_id or _id("device")).strip()
        key = self._sync_device_key(workspace_id, device_id)
        device = data.setdefault("syncDevices", {}).get(key)
        if device:
            device["agentId"] = agent_id or device.get("agentId") or ""
            device["label"] = redact_text(label or device.get("label") or device_id)
            device["status"] = "active"
            device["updatedAt"] = now
        else:
            device = {
                "deviceId": device_id,
                "workspaceId": workspace_id,
                "agentId": agent_id or "",
                "label": redact_text(label or device_id),
                "status": "active",
                "authorityEpoch": 1,
                "createdAt": now,
                "updatedAt": now,
                "revokedAt": None,
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            }
            data.setdefault("syncDevices", {})[key] = device
        self.audit(data, "sync.device.register", agent_id, device_id, workspace_id, {"authorityEpoch": device["authorityEpoch"]})
        self._save(data)
        return dict(device)

    def rotate_sync_device(self, workspace_id, device_id, agent_id):
        data = self._load()
        key = self._sync_device_key(workspace_id, device_id)
        device = data.setdefault("syncDevices", {}).get(key)
        if not device:
            return None, "device_not_found"
        if device.get("status") == "revoked":
            return None, "device_revoked"
        device["authorityEpoch"] = int(device.get("authorityEpoch") or 1) + 1
        device["updatedAt"] = utc_now()
        self.audit(data, "sync.device.rotate", agent_id, device_id, workspace_id, {"authorityEpoch": device["authorityEpoch"]})
        self._save(data)
        return dict(device), None

    def revoke_sync_device(self, workspace_id, device_id, agent_id):
        data = self._load()
        key = self._sync_device_key(workspace_id, device_id)
        device = data.setdefault("syncDevices", {}).get(key)
        if not device:
            return None, "device_not_found"
        device["status"] = "revoked"
        device["revokedAt"] = utc_now()
        device["updatedAt"] = device["revokedAt"]
        self.audit(data, "sync.device.revoke", agent_id, device_id, workspace_id, {"authorityEpoch": device.get("authorityEpoch")})
        self._save(data)
        return dict(device), None

    def sync_device(self, workspace_id, device_id):
        if not device_id:
            return None
        data = self._load()
        return data.setdefault("syncDevices", {}).get(self._sync_device_key(workspace_id, device_id))

    def submit_sync_mutation(self, workspace_id, actor_agent_id, body, idempotency_key=""):
        data = self._load()
        now = utc_now()
        body = body or {}
        operation = (body.get("operation") or "upsert").strip().lower()
        if operation not in ("upsert", "delete", "hard_forget"):
            operation = "upsert"
        logical_memory_id = (body.get("logicalMemoryId") or body.get("logical_memory_id") or "").strip()
        if not logical_memory_id and operation == "upsert":
            logical_memory_id = _id("lm")
        parent_revision_id = (body.get("parentRevisionId") or body.get("parent_revision_id") or "").strip()
        device_id = (body.get("deviceId") or body.get("device_id") or "").strip()
        device_epoch = int(body.get("deviceEpoch") or body.get("device_epoch") or 0)
        idempotency_hash = _hash(idempotency_key) if idempotency_key else ""
        body_hash = (body.get("bodyHash") or body.get("body_hash") or "").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{64}", body_hash or ""):
            body_hash = _canonical_hash(
                {
                    "operation": operation,
                    "logicalMemoryId": logical_memory_id,
                    "parentRevisionId": parent_revision_id,
                    "summary": body.get("summary") or "",
                    "title": body.get("title") or "",
                    "source": body.get("source") or body.get("sourceRef") or "",
                }
            )
        device = self.sync_device(workspace_id, device_id) if device_id else None
        reject_code = ""
        if device_id and not device:
            reject_code = "device_not_registered"
        elif device and device.get("status") == "revoked":
            reject_code = "device_revoked"
        elif device and device_epoch and int(device.get("authorityEpoch") or 1) != device_epoch:
            reject_code = "device_epoch_mismatch"
        elif operation == "hard_forget":
            reject_code = "hard_forget_not_supported"
        elif not logical_memory_id:
            reject_code = "logical_memory_id_required"

        head_key = self._sync_head_key(workspace_id, logical_memory_id)
        current_head = data.setdefault("syncHeads", {}).get(head_key)
        current_head_revision = (current_head or {}).get("headRevisionId") or ""
        current_status = (current_head or {}).get("status") or ""
        conflict_code = ""
        if not reject_code:
            if operation in ("upsert", "delete") and current_head and parent_revision_id != current_head_revision:
                conflict_code = "parent_revision_mismatch"
            if operation == "upsert" and current_status == "tombstoned":
                conflict_code = "tombstone_resurrection_blocked"
            if operation == "delete" and not current_head:
                conflict_code = "head_not_found"

        server_sequence = self._sync_next_sequence(data, workspace_id)
        revision_id = _id("syncrev")
        receipt_id = _id("syncreceipt")
        status = "rejected" if reject_code else ("conflict" if conflict_code else "applied")
        http_status = "409 Conflict" if status in ("rejected", "conflict") else "202 Accepted"
        revision = None
        if status != "rejected":
            revision = {
                "syncRevisionId": revision_id,
                "workspaceId": workspace_id,
                "logicalMemoryId": logical_memory_id,
                "parentRevisionId": parent_revision_id,
                "memoryEventId": "",
                "actorAgentId": actor_agent_id,
                "deviceId": device_id,
                "deviceEpoch": device_epoch or (int(device.get("authorityEpoch") or 0) if device else 0),
                "operation": operation,
                "status": status,
                "conflict": bool(conflict_code),
                "conflictCode": conflict_code,
                "serverSequence": server_sequence,
                "bodyHash": body_hash,
                "source": redact_text(body.get("sourceRef") or body.get("source") or "api"),
                "title": redact_text(body.get("title") or logical_memory_id),
                "summary": redact_text(body.get("summary") or ""),
                "scope": (body.get("scope") or "workspace").strip().lower(),
                "scopeId": body.get("scopeId") or body.get("scope_id") or workspace_id,
                "memoryType": (body.get("memoryType") or body.get("memory_type") or "note").strip().lower(),
                "tombstone": operation == "delete",
                "createdAt": now,
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            }
            data.setdefault("syncRevisions", []).append(revision)
            if status == "applied":
                data.setdefault("syncHeads", {})[head_key] = {
                    "logicalMemoryId": logical_memory_id,
                    "workspaceId": workspace_id,
                    "headRevisionId": revision_id,
                    "serverSequence": server_sequence,
                    "indexedThroughSequence": server_sequence,
                    "status": "tombstoned" if operation == "delete" else "active",
                    "updatedAt": now,
                    "valuesRedacted": True,
                    "rawPayloadExposed": False,
                }
            self._append_outbox(data, workspace_id, "matm.sync.revision.%s" % status, "sync_revision", revision_id, revision)
            self._append_storage_ledger(data, workspace_id, "sync_revision", revision_id, revision)

        receipt = {
            "receiptId": receipt_id,
            "workspaceId": workspace_id,
            "idempotencyKeyHash": ("sha256:" + idempotency_hash) if idempotency_hash else "",
            "bodyHash": body_hash,
            "logicalMemoryId": logical_memory_id,
            "syncRevisionId": revision_id if revision else "",
            "serverSequence": server_sequence if revision else 0,
            "status": status,
            "conflict": bool(conflict_code),
            "conflictCode": conflict_code or reject_code,
            "currentHeadRevisionId": current_head_revision,
            "httpStatus": http_status,
            "createdAt": now,
            "idempotencyKeyExposed": False,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }
        data.setdefault("syncReceipts", []).append(receipt)
        self.audit(data, "sync.mutation.%s" % status, actor_agent_id, receipt_id, workspace_id, {"logicalMemoryId": logical_memory_id, "serverSequence": receipt["serverSequence"], "conflictCode": receipt["conflictCode"]})
        self._save(data)
        return {
            "ok": status == "applied",
            "persisted": True,
            "receipt": self._public_sync_receipt(receipt),
            "revision": self._public_sync_revision(revision) if revision else None,
            "head": data.setdefault("syncHeads", {}).get(head_key),
            "serverSequence": receipt["serverSequence"],
            "indexedThroughSequence": (data.setdefault("syncHeads", {}).get(head_key) or {}).get("indexedThroughSequence") or 0,
            "conflict": status == "conflict",
            "status": status,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }, http_status

    def sync_receipt(self, workspace_id, idempotency_key=None, receipt_id=None):
        data = self._load()
        idempotency_hash = _hash(idempotency_key) if idempotency_key else ""
        for receipt in reversed(data.get("syncReceipts", [])):
            if receipt.get("workspaceId") != workspace_id:
                continue
            if receipt_id and receipt.get("receiptId") == receipt_id:
                return self._public_sync_receipt(receipt)
            if idempotency_hash and receipt.get("idempotencyKeyHash") == "sha256:" + idempotency_hash:
                return self._public_sync_receipt(receipt)
        return None

    def sync_changes(self, workspace_id, after_sequence=0, limit=50, logical_memory_id=None):
        try:
            after_value = int(after_sequence or 0)
        except (TypeError, ValueError):
            after_value = 0
        limit_value = max(1, min(int(limit or 50), 200))
        data = self._load()
        rows = [
            self._public_sync_revision(item)
            for item in data.get("syncRevisions", [])
            if item.get("workspaceId") == workspace_id
            and int(item.get("serverSequence") or 0) > after_value
            and (not logical_memory_id or item.get("logicalMemoryId") == logical_memory_id)
        ]
        rows.sort(key=lambda item: int(item.get("serverSequence") or 0))
        page = rows[:limit_value]
        latest = max([int(item.get("serverSequence") or 0) for item in data.get("syncRevisions", []) if item.get("workspaceId") == workspace_id] or [0])
        return {
            "items": page,
            "count": len(page),
            "hasMore": len(rows) > len(page),
            "nextAfterSequence": int(page[-1].get("serverSequence") or after_value) if page else after_value,
            "indexedThroughSequence": latest,
            "checkpoint": {
                "workspaceIdHash": "sha256:" + _hash(workspace_id),
                "afterSequence": after_value,
                "nextAfterSequence": int(page[-1].get("serverSequence") or after_value) if page else after_value,
                "valuesRedacted": True,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def sync_heads(self, workspace_id, logical_memory_id=None):
        data = self._load()
        items = []
        for head in data.setdefault("syncHeads", {}).values():
            if head.get("workspaceId") != workspace_id:
                continue
            if logical_memory_id and head.get("logicalMemoryId") != logical_memory_id:
                continue
            item = dict(head)
            item["valuesRedacted"] = True
            item["rawPayloadExposed"] = False
            items.append(item)
        items.sort(key=lambda item: (item.get("logicalMemoryId") or ""))
        return items

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
        created_rooms = self._ensure_default_meeting_rooms(data, workspace_id)
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
                "meetingRoomCount": len(created_rooms),
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
                "redactionApplied": firewall["valuesRedacted"],
                "valuesRedacted": True,
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
        event["reviewId"] = review["reviewId"]
        data.setdefault("reviewQueue", []).append(review)
        self._append_outbox(data, workspace_id, "matm.memory_event.submitted", "memory_event", event["eventId"], event)
        self._append_storage_ledger(data, workspace_id, "memory_event", event["eventId"], event)
        self.audit(data, "memory.submit", actor_agent_id, event["eventId"], workspace_id, {"reviewId": review["reviewId"], "firewallDecision": firewall["decision"]})
        self._save(data)
        return event

    def search_memory(self, workspace_id, query, filters=None):
        data = self._load()
        q = (query or "").lower().strip()
        filters = filters or {}
        scope_filter = (filters.get("scope") or "").strip().lower()
        scope_id_filter = (filters.get("scopeId") or filters.get("scope_id") or "").strip()
        memory_type_filter = (filters.get("memoryType") or filters.get("memory_type") or "").strip().lower()
        review_status_filter = (filters.get("reviewStatus") or filters.get("review_status") or "").strip().lower()
        promotion_state_filter = (filters.get("promotionState") or filters.get("promotion_state") or "").strip().lower()
        source_prefix_filter = (filters.get("sourcePrefix") or filters.get("source_prefix") or "").strip()
        tag_filter = (filters.get("tag") or "").strip().lower()
        actor_agent_filter = (filters.get("actorAgentId") or filters.get("actor_agent_id") or "").strip().lower()
        event_id_filter = (
            filters.get("eventId")
            or filters.get("event_id")
            or filters.get("memoryEventId")
            or filters.get("memory_event_id")
            or ""
        ).strip()
        items = []
        for event in data["memoryEvents"]:
            if event.get("workspaceId") != workspace_id:
                continue
            if event.get("status") in ("rejected", "quarantined"):
                continue
            if scope_filter and (event.get("scope") or "").lower() != scope_filter:
                continue
            if scope_id_filter and event.get("scopeId") != scope_id_filter:
                continue
            if memory_type_filter and (event.get("memoryType") or "").lower() != memory_type_filter:
                continue
            if review_status_filter and (event.get("reviewStatus") or "").lower() != review_status_filter:
                continue
            if promotion_state_filter and (event.get("promotionState") or "").lower() != promotion_state_filter:
                continue
            if source_prefix_filter and not (event.get("source") or "").startswith(source_prefix_filter):
                continue
            if actor_agent_filter and (event.get("actorAgentId") or "").lower() != actor_agent_filter:
                continue
            if tag_filter and tag_filter not in [str(tag).lower() for tag in event.get("tags", [])]:
                continue
            if event_id_filter and event.get("eventId") != event_id_filter:
                continue
            haystack = " ".join(
                [
                    event.get("eventId", ""),
                    event.get("reviewId", ""),
                    event.get("actorAgentId", ""),
                    event.get("subject", ""),
                    event.get("title", ""),
                    event.get("summary", ""),
                    " ".join(event.get("tags", [])),
                    event.get("source", ""),
                    event.get("memoryType", ""),
                    event.get("scope", ""),
                    event.get("scopeId", ""),
                ]
            ).lower()
            if _memory_query_matches(q, haystack):
                items.append(_public_memory_event(event))
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

    def _active_agent_ids(self, data, workspace_id, fallback_agent_id=None):
        ids = []
        for agent in data.get("agents", {}).values():
            if agent.get("workspaceId") != workspace_id:
                continue
            if (agent.get("status") or "active") != "active":
                continue
            agent_id = agent.get("agentId")
            if agent_id and agent_id not in ids:
                ids.append(agent_id)
        if fallback_agent_id and fallback_agent_id not in ids:
            ids.append(fallback_agent_id)
        ids.sort()
        return ids

    def submit_message(self, workspace_id, sender_agent_id, target_agent_id, safe_summary, response_required):
        data = self._load()
        safe_summary = redact_text(safe_summary)
        target_agent_id = (target_agent_id or "").strip()
        recipient_agent_ids = [target_agent_id] if target_agent_id else self._active_agent_ids(data, workspace_id, sender_agent_id)
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
        notes = []
        for recipient_agent_id in recipient_agent_ids:
            notes.append(
                {
                    "notificationId": _id("note"),
                    "workspaceId": workspace_id,
                    "messageId": message["messageId"],
                    "targetAgentId": recipient_agent_id,
                    "status": "unread",
                    "responseDisposition": "required_response" if response_required else "viewed_acknowledgement",
                    "createdAt": utc_now(),
                    "readAt": None,
                }
            )
        data["messages"].append(message)
        data["notifications"].extend(notes)
        self._append_outbox(data, workspace_id, "matm.agent_message.submitted", "message", message["messageId"], message)
        self._append_storage_ledger(data, workspace_id, "message", message["messageId"], message)
        self.audit(
            data,
            "message.submit",
            sender_agent_id,
            message["messageId"],
            workspace_id,
            {
                "deliveryCounts": {"broadcast": 1 if not target_agent_id else 0, "targeted": 1 if target_agent_id else 0},
                "recipientCount": len(notes),
            },
        )
        self._save(data)
        return message, notes

    def inbox(self, workspace_id, agent_id, message_id=None, notification_id=None, limit=None):
        data = self._load()
        message_id = str(message_id or "").strip()
        notification_id = str(notification_id or "").strip()
        try:
            limit_value = int(limit or 0)
        except (TypeError, ValueError):
            limit_value = 0
        limit_value = max(0, min(limit_value, 200))
        messages = []
        for note in reversed(data["notifications"]):
            if note.get("workspaceId") != workspace_id or note.get("status") != "unread":
                continue
            if note.get("targetAgentId") and note.get("targetAgentId") != agent_id:
                continue
            if notification_id and note.get("notificationId") != notification_id:
                continue
            if message_id and note.get("messageId") != message_id:
                continue
            message = None
            for item in data["messages"]:
                if item.get("messageId") == note.get("messageId"):
                    message = item
                    break
            if message:
                messages.append({"notification": note, "message": message})
                if limit_value and len(messages) >= limit_value:
                    break
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
        "matm_meeting_reads",
        "matm_routing_decisions",
        "matm_meeting_messages",
        "matm_meeting_rooms",
        "matm_sync_receipts",
        "matm_sync_revisions",
        "matm_sync_heads",
        "matm_sync_devices",
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

            CREATE TABLE IF NOT EXISTS matm_meeting_rooms (
              room_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              scope_type TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              label TEXT NOT NULL,
              name TEXT NOT NULL,
              purpose TEXT NOT NULL,
              status TEXT NOT NULL,
              default_room INTEGER NOT NULL DEFAULT 1,
              always_available INTEGER NOT NULL DEFAULT 1,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              UNIQUE (workspace_id, scope_type, scope_id),
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_meeting_rooms_scope ON matm_meeting_rooms (workspace_id, scope_type, scope_id);

            CREATE TABLE IF NOT EXISTS matm_meeting_messages (
              meeting_message_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              scope_type TEXT NOT NULL,
              scope_id TEXT NOT NULL,
              sender_agent_id TEXT NOT NULL,
              safe_summary TEXT NOT NULL,
              raw_message_body_stored INTEGER NOT NULL DEFAULT 0,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (room_id) REFERENCES matm_meeting_rooms (room_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_meeting_messages_room_created ON matm_meeting_messages (workspace_id, room_id, created_at);

            CREATE TABLE IF NOT EXISTS matm_routing_decisions (
              routing_decision_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              source_room_id TEXT NOT NULL,
              destination_room_id TEXT NOT NULL,
              destination_scope TEXT NOT NULL,
              destination_scope_id TEXT NOT NULL,
              coordinator_agent_id TEXT NOT NULL,
              routed_agent_id TEXT NOT NULL,
              lane TEXT NOT NULL,
              specific_goal TEXT NOT NULL,
              expected_evidence_json TEXT NOT NULL,
              next_action TEXT NOT NULL,
              support_plan TEXT NOT NULL,
              meeting_message_id TEXT NOT NULL,
              status TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (source_room_id) REFERENCES matm_meeting_rooms (room_id),
              FOREIGN KEY (destination_room_id) REFERENCES matm_meeting_rooms (room_id),
              FOREIGN KEY (meeting_message_id) REFERENCES matm_meeting_messages (meeting_message_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_routing_decisions_agent ON matm_routing_decisions (workspace_id, routed_agent_id, created_at);
            CREATE INDEX IF NOT EXISTS ix_sqlite_routing_decisions_destination ON matm_routing_decisions (workspace_id, destination_room_id, created_at);
            CREATE INDEX IF NOT EXISTS ix_sqlite_routing_decisions_status ON matm_routing_decisions (workspace_id, status, created_at);

            CREATE TABLE IF NOT EXISTS matm_meeting_reads (
              meeting_read_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              room_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              last_meeting_message_id TEXT,
              last_read_at TEXT,
              read_message_count INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'read',
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              UNIQUE (workspace_id, room_id, agent_id),
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (room_id) REFERENCES matm_meeting_rooms (room_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_meeting_reads_agent ON matm_meeting_reads (workspace_id, agent_id);

            CREATE TABLE IF NOT EXISTS matm_sync_devices (
              device_record_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              agent_id TEXT,
              label TEXT NOT NULL,
              status TEXT NOT NULL,
              authority_epoch INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT,
              revoked_at TEXT,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              UNIQUE (workspace_id, device_id),
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_sync_devices_workspace ON matm_sync_devices (workspace_id, status);

            CREATE TABLE IF NOT EXISTS matm_sync_heads (
              head_record_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              logical_memory_id TEXT NOT NULL,
              head_revision_id TEXT,
              server_sequence INTEGER NOT NULL,
              indexed_through_sequence INTEGER NOT NULL,
              status TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              UNIQUE (workspace_id, logical_memory_id),
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE INDEX IF NOT EXISTS ix_sqlite_sync_heads_workspace ON matm_sync_heads (workspace_id, status);

            CREATE TABLE IF NOT EXISTS matm_sync_revisions (
              sync_revision_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              logical_memory_id TEXT NOT NULL,
              parent_revision_id TEXT,
              memory_event_id TEXT,
              actor_agent_id TEXT,
              device_id TEXT,
              device_epoch INTEGER NOT NULL DEFAULT 0,
              operation TEXT NOT NULL,
              status TEXT NOT NULL,
              conflict INTEGER NOT NULL DEFAULT 0,
              conflict_code TEXT,
              server_sequence INTEGER NOT NULL,
              body_hash TEXT NOT NULL,
              source_uri TEXT,
              title TEXT NOT NULL,
              public_safe_summary TEXT NOT NULL,
              scope_type TEXT NOT NULL,
              scope_id TEXT,
              memory_type TEXT NOT NULL,
              tombstone INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_sqlite_sync_revisions_sequence ON matm_sync_revisions (workspace_id, server_sequence);
            CREATE INDEX IF NOT EXISTS ix_sqlite_sync_revisions_logical ON matm_sync_revisions (workspace_id, logical_memory_id, server_sequence);

            CREATE TABLE IF NOT EXISTS matm_sync_receipts (
              receipt_id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              idempotency_key_hash TEXT,
              body_hash TEXT NOT NULL,
              logical_memory_id TEXT,
              sync_revision_id TEXT,
              server_sequence INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL,
              conflict INTEGER NOT NULL DEFAULT 0,
              conflict_code TEXT,
              current_head_revision_id TEXT,
              http_status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              idempotency_key_exposed INTEGER NOT NULL DEFAULT 0,
              values_redacted INTEGER NOT NULL DEFAULT 1,
              raw_credential_exposed INTEGER NOT NULL DEFAULT 0,
              raw_payload_exposed INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
              FOREIGN KEY (sync_revision_id) REFERENCES matm_sync_revisions (sync_revision_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_sqlite_sync_receipts_idem ON matm_sync_receipts (workspace_id, idempotency_key_hash);
            CREATE INDEX IF NOT EXISTS ix_sqlite_sync_receipts_workspace ON matm_sync_receipts (workspace_id, created_at);

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

    def _room_from_row(self, row):
        if not row:
            return None
        item = {
            "roomId": row["room_id"],
            "workspaceId": row["workspace_id"],
            "scope": row["scope_type"],
            "scopeId": row["scope_id"],
            "label": row["label"],
            "name": row["name"],
            "purpose": row["purpose"],
            "status": row["status"],
            "defaultRoom": self._bool(row["default_room"]),
            "alwaysAvailable": self._bool(row["always_available"]),
            "createdAt": row["created_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }
        if row["updated_at"]:
            item["updatedAt"] = row["updated_at"]
        return item

    def _meeting_message_from_row(self, row):
        if not row:
            return None
        return {
            "meetingMessageId": row["meeting_message_id"],
            "workspaceId": row["workspace_id"],
            "roomId": row["room_id"],
            "scope": row["scope_type"],
            "scopeId": row["scope_id"],
            "senderAgentId": row["sender_agent_id"],
            "safeSummary": row["safe_summary"],
            "createdAt": row["created_at"],
            "rawMessageBodyStored": self._bool(row["raw_message_body_stored"]),
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _routing_decision_from_row(self, row):
        if not row:
            return None
        return {
            "routingDecisionId": row["routing_decision_id"],
            "workspaceId": row["workspace_id"],
            "sourceRoomId": row["source_room_id"],
            "destinationRoomId": row["destination_room_id"],
            "destinationScope": row["destination_scope"],
            "destinationScopeId": row["destination_scope_id"],
            "coordinatorAgentId": row["coordinator_agent_id"],
            "routedAgentId": row["routed_agent_id"],
            "lane": row["lane"],
            "specificGoal": row["specific_goal"],
            "expectedEvidence": self._json_load(row["expected_evidence_json"], []),
            "nextAction": row["next_action"],
            "supportPlan": row["support_plan"],
            "meetingMessageId": row["meeting_message_id"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _review_from_row(self, row):
        if not row:
            return None
        return {
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

    def _meeting_read_from_row(self, row):
        if not row:
            return {}
        return {
            "meetingReadId": row["meeting_read_id"],
            "workspaceId": row["workspace_id"],
            "roomId": row["room_id"],
            "agentId": row["agent_id"],
            "lastMeetingMessageId": row["last_meeting_message_id"],
            "lastReadAt": row["last_read_at"],
            "readMessageCount": row["read_message_count"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _row_dict(self, row):
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        return dict(row)

    def _row_json_size(self, row):
        return _json_size(self._row_dict(row))

    def _sum_workspace_rows(self, connection, table, workspace_id):
        return sum(
            self._row_json_size(row)
            for row in connection.execute(
                "SELECT * FROM %s WHERE workspace_id = ?" % table,
                (workspace_id,),
            )
        )

    def _ensure_default_meeting_rooms_sql(self, connection, workspace_id):
        workspace = connection.execute(
            "SELECT * FROM matm_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if not workspace:
            return []
        company = connection.execute(
            "SELECT * FROM matm_companies WHERE company_id = ?",
            (workspace["company_id"],),
        ).fetchone()
        projects = list(
            connection.execute(
                "SELECT * FROM matm_projects WHERE workspace_id = ? ORDER BY created_at, project_id",
                (workspace_id,),
            )
        )
        specs = [
            {
                "scope": "company",
                "scopeId": workspace["company_id"],
                "label": "Company-wide meeting",
                "name": "%s welcome and routing meeting" % ((company["label"] if company else "") or "Company"),
                "purpose": "Highest-level welcome room for new agents to state who they are, why they are here, what they are working on, and which workspace, project, goal, or task room they should be routed into.",
            },
            {
                "scope": "workspace",
                "scopeId": workspace_id,
                "label": "Workspace-wide meeting",
                "name": "%s workspace meeting" % (workspace["label"] or "Workspace"),
                "purpose": "Workspace operating room for active coordination, shared context, and cross-project routing after company-level intake.",
            },
        ]
        for project in projects:
            specs.append(
                {
                    "scope": "project",
                    "scopeId": project["project_id"],
                    "label": "Project-wide meeting",
                    "name": "%s project meeting" % (project["label"] or "Project"),
                    "purpose": "Project implementation room for assigned work, decisions, blockers, and handoff after intake routing.",
                }
            )
        created = []
        now = utc_now()
        for spec in specs:
            if not spec.get("scopeId"):
                continue
            room_id = self._meeting_room_id(workspace_id, spec["scope"], spec["scopeId"])
            existing = connection.execute(
                "SELECT room_id FROM matm_meeting_rooms WHERE workspace_id = ? AND room_id = ?",
                (workspace_id, room_id),
            ).fetchone()
            if existing:
                continue
            room = {
                "roomId": room_id,
                "workspaceId": workspace_id,
                "scope": spec["scope"],
                "scopeId": spec["scopeId"],
                "label": spec["label"],
                "name": redact_text(spec["name"]),
                "purpose": redact_text(spec["purpose"]),
                "status": "active",
                "defaultRoom": True,
                "alwaysAvailable": True,
                "createdAt": now,
                "updatedAt": None,
                "valuesRedacted": True,
                "rawPayloadExposed": False,
            }
            connection.execute(
                """
                INSERT INTO matm_meeting_rooms (
                  room_id, workspace_id, scope_type, scope_id, label, name, purpose, status,
                  default_room, always_available, values_redacted, raw_payload_exposed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    room_id,
                    workspace_id,
                    room["scope"],
                    room["scopeId"],
                    room["label"],
                    room["name"],
                    room["purpose"],
                    room["status"],
                    self._int_bool(True),
                    self._int_bool(True),
                    self._int_bool(True),
                    self._int_bool(False),
                    room["createdAt"],
                    room["updatedAt"],
                ),
            )
            created.append(room)
        return created

    def _workspace_usage_bytes_sql(self, connection, workspace_id):
        workspace = connection.execute(
            "SELECT * FROM matm_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if not workspace:
            return 0
        usage = self._row_json_size(workspace)
        company_id = workspace["company_id"]
        company = connection.execute(
            "SELECT * FROM matm_companies WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        usage += self._row_json_size(company)
        memberships = list(
            connection.execute(
                "SELECT * FROM matm_account_companies WHERE company_id = ?",
                (company_id,),
            )
        )
        for membership in memberships:
            usage += self._row_json_size(membership)
            account = connection.execute(
                "SELECT * FROM matm_accounts WHERE account_id = ?",
                (membership["account_id"],),
            ).fetchone()
            usage += self._row_json_size(account)
        for table in (
            "matm_projects",
            "matm_agents",
            "matm_memory_records",
            "matm_review_queue",
            "matm_messages",
            "matm_notifications",
            "matm_receipts",
            "matm_meeting_rooms",
            "matm_meeting_messages",
            "matm_meeting_reads",
            "matm_routing_decisions",
            "matm_sync_devices",
            "matm_sync_heads",
            "matm_sync_revisions",
            "matm_sync_receipts",
            "matm_idempotency",
            "matm_outbox_events",
            "matm_storage_ledger",
            "matm_audit_log",
        ):
            usage += self._sum_workspace_rows(connection, table, workspace_id)
        return usage

    def audit_log(self, workspace_id, limit=50, action=None):
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        action_filter = (action or "").strip()
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        if action_filter:
            clauses.append("action = ?")
            params.append(action_filter)
        params.append(limit_value)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_audit_log
                        WHERE %s
                        ORDER BY created_at DESC, audit_id DESC
                        LIMIT ?
                        """ % " AND ".join(clauses),
                        tuple(params),
                    )
                )
        rows.reverse()
        items = []
        for row in rows:
            details = self._json_load(row["details_json"], {})
            items.append(
                {
                    "auditId": row["audit_id"],
                    "workspaceId": row["workspace_id"],
                    "action": row["action"],
                    "actor": redact_text(row["actor"] or ""),
                    "target": redact_text(row["target"] or ""),
                    "details": _public_value(details),
                    "detailsSummary": _audit_detail_summary(details),
                    "createdAt": row["created_at"],
                    "valuesRedacted": self._bool(row["values_redacted"]),
                    "rawCredentialExposed": self._bool(row["raw_credential_exposed"]),
                    "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                }
            )
        return items

    def workspace_status(self, workspace_id):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    workspace = connection.execute(
                        "SELECT * FROM matm_workspaces WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()
                    if not workspace:
                        return None
                    created_rooms = self._ensure_default_meeting_rooms_sql(connection, workspace_id)
                    if created_rooms:
                        self._record_audit_sql(
                            connection,
                            workspace_id,
                            "meeting_rooms.ensure_defaults",
                            "system",
                            workspace_id,
                            {"meetingRoomCount": len(created_rooms)},
                        )
                    workspace = connection.execute(
                        "SELECT * FROM matm_workspaces WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()
                    used = self._workspace_usage_bytes_sql(connection, workspace_id)
                    limit = int(workspace["storage_limit_bytes"] or PUBLIC_STORAGE_BYTES)
                    company_id = workspace["company_id"]
                    company = connection.execute(
                        "SELECT * FROM matm_companies WHERE company_id = ?",
                        (company_id,),
                    ).fetchone()
                    memberships = []
                    account_items = []
                    for membership in connection.execute(
                        """
                        SELECT * FROM matm_account_companies
                        WHERE company_id = ?
                        ORDER BY created_at, membership_id
                        """,
                        (company_id,),
                    ):
                        membership_item = {
                            "membershipId": membership["membership_id"],
                            "accountId": membership["account_id"],
                            "companyId": membership["company_id"],
                            "role": membership["role"],
                            "status": membership["status"],
                            "createdAt": membership["created_at"],
                            "valuesRedacted": True,
                        }
                        if membership["updated_at"]:
                            membership_item["updatedAt"] = membership["updated_at"]
                        memberships.append(membership_item)
                        account = connection.execute(
                            "SELECT * FROM matm_accounts WHERE account_id = ?",
                            (membership["account_id"],),
                        ).fetchone()
                        if account:
                            account_item = {
                                "accountId": account["account_id"],
                                "label": account["label"],
                                "status": account["status"],
                                "createdAt": account["created_at"],
                                "role": membership["role"],
                                "valuesRedacted": True,
                            }
                            if account["updated_at"]:
                                account_item["updatedAt"] = account["updated_at"]
                            account_items.append(account_item)
                    projects = []
                    for project in connection.execute(
                        """
                        SELECT * FROM matm_projects
                        WHERE workspace_id = ?
                        ORDER BY created_at, project_id
                        """,
                        (workspace_id,),
                    ):
                        project_item = {
                            "projectId": project["project_id"],
                            "workspaceId": project["workspace_id"],
                            "label": project["label"],
                            "status": project["status"],
                            "createdAt": project["created_at"],
                            "valuesRedacted": True,
                        }
                        if project["updated_at"]:
                            project_item["updatedAt"] = project["updated_at"]
                        projects.append(project_item)
                    return {
                        "workspaceId": workspace_id,
                        "label": workspace["label"],
                        "accountId": account_items[0]["accountId"] if account_items else None,
                        "companyId": company_id,
                        "primaryProjectId": projects[0]["projectId"] if projects else None,
                        "company": {
                            "companyId": company["company_id"] if company else company_id,
                            "label": (company["label"] if company else None) or "Free Agent Company",
                            "status": (company["status"] if company else None) or "active",
                        },
                        "meetingRooms": self._meeting_rooms_sql(connection, workspace_id),
                        "accounts": account_items,
                        "accountCompanyMemberships": memberships,
                        "projects": projects,
                        "plan": workspace["plan"],
                        "status": workspace["status"],
                        "storageLimitBytes": limit,
                        "storageUsedBytes": used,
                        "storageRemainingBytes": max(0, limit - used),
                        "quotaExceeded": used > limit,
                        "rawKeyStoredByServer": False,
                    }

    def workspace_usage_bytes(self, data, workspace_id=None):
        workspace_id = workspace_id or data
        with _LOCK:
            with self._open_connection() as connection:
                return self._workspace_usage_bytes_sql(connection, workspace_id)

    def record_audit(self, workspace_id, action, actor, target, details=None):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    self._record_audit_sql(connection, workspace_id, action, actor, target, details)

    def has_quota_for(self, workspace_id, candidate):
        for attempt in range(len(SQL_READ_AFTER_WRITE_RETRY_DELAYS) + 1):
            with _LOCK:
                with self._open_connection() as connection:
                    workspace = connection.execute(
                        "SELECT storage_limit_bytes FROM matm_workspaces WHERE workspace_id = ?",
                        (workspace_id,),
                    ).fetchone()
                    if workspace:
                        limit = int(workspace["storage_limit_bytes"] or PUBLIC_STORAGE_BYTES)
                        return self._workspace_usage_bytes_sql(connection, workspace_id) + _json_size(candidate) <= limit
            if attempt < len(SQL_READ_AFTER_WRITE_RETRY_DELAYS):
                time.sleep(SQL_READ_AFTER_WRITE_RETRY_DELAYS[attempt])
        return False

    def create_free_account(self, label, company_label=None, project_label=None):
        created_at = utc_now()
        account_id = _id("account")
        company_id = _id("company")
        membership_id = _id("membership")
        workspace_id = _id("workspace")
        project_id = _id("project")
        token = "me_live_" + secrets.token_urlsafe(32)
        key_id = _id("key")
        account_label = redact_text((company_label or label or "Free Agent Account") + " Account")
        company_label = redact_text(company_label or label or "Free Agent Company")
        workspace_label = redact_text(label or "Free Agent Workspace")
        project_label = redact_text(project_label or "MemoryEndpoints Verification Project")
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO matm_accounts (account_id, label, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (account_id, account_label, "active", created_at, None),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_companies (company_id, label, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (company_id, company_label, "active", created_at, None),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_account_companies (
                          membership_id, account_id, company_id, role, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (membership_id, account_id, company_id, "owner", "active", created_at, None),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_workspaces (
                          workspace_id, company_id, label, plan, storage_limit_bytes, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (workspace_id, company_id, workspace_label, "free_agent", PUBLIC_STORAGE_BYTES, "active", created_at, None),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_projects (project_id, workspace_id, label, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (project_id, workspace_id, project_label, "active", created_at, None),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_api_keys (
                          key_id, workspace_id, token_hash, created_at, last_used_at, revoked_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (key_id, workspace_id, _hash(token), created_at, None, None),
                    )
                    created_rooms = self._ensure_default_meeting_rooms_sql(connection, workspace_id)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "workspace.create_free_account",
                        "system",
                        workspace_id,
                        {
                            "accountId": account_id,
                            "companyId": company_id,
                            "accountCompanyMembershipId": membership_id,
                            "projectId": project_id,
                            "meetingRoomCount": len(created_rooms),
                        },
                    )
        return workspace_id, key_id, token, account_id, company_id, project_id

    def register_agent(self, workspace_id, agent_id, display_name):
        now = utc_now()
        record = {
            "workspaceId": workspace_id,
            "agentId": agent_id,
            "displayName": redact_text(display_name or agent_id),
            "registeredAt": now,
            "status": "active",
        }
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO matm_agents (
                          agent_record_id, workspace_id, agent_id, display_name, status, registered_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self._agent_record_id(workspace_id, agent_id),
                            workspace_id,
                            agent_id,
                            record["displayName"],
                            record["status"],
                            record["registeredAt"],
                            now,
                        ),
                    )
                    self._record_audit_sql(connection, workspace_id, "agent.register", agent_id, workspace_id)
        return record

    def _record_audit_sql(self, connection, workspace_id, action, actor, target, details=None):
        connection.execute(
            """
            INSERT INTO matm_audit_log (
              audit_id, workspace_id, action, actor, target, details_json, created_at,
              raw_credential_exposed, raw_payload_exposed, values_redacted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _id("audit"),
                workspace_id,
                action,
                actor or "system",
                target or workspace_id,
                self._json_dump(details or {}),
                utc_now(),
                self._int_bool(False),
                self._int_bool(False),
                self._int_bool(True),
            ),
        )

    def _insert_outbox_sql(self, connection, workspace_id, event_type, aggregate_type, aggregate_id, payload=None):
        connection.execute(
            """
            INSERT INTO matm_outbox_events (
              outbox_event_id, workspace_id, event_type, aggregate_type, aggregate_id,
              payload_hash, status, created_at, values_redacted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _id("outbox"),
                workspace_id,
                event_type,
                aggregate_type,
                aggregate_id,
                _canonical_hash(payload or {}),
                "pending",
                utc_now(),
                self._int_bool(True),
            ),
        )

    def _insert_storage_ledger_sql(self, connection, workspace_id, object_type, object_id, value):
        connection.execute(
            """
            INSERT INTO matm_storage_ledger (
              ledger_id, workspace_id, object_type, object_id, bytes_delta, created_at, values_redacted
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _id("ledger"),
                workspace_id,
                object_type,
                object_id,
                _json_size(value),
                utc_now(),
                self._int_bool(True),
            ),
        )

    def authenticate(self, token, workspace_id=None):
        if not token:
            return None
        token_hash = _hash(token)
        for attempt in range(len(SQL_READ_AFTER_WRITE_RETRY_DELAYS) + 1):
            with _LOCK:
                with self._open_connection() as connection:
                    with connection:
                        row = connection.execute(
                            """
                            SELECT * FROM matm_api_keys
                            WHERE token_hash = ? AND revoked_at IS NULL
                            """,
                            (token_hash,),
                        ).fetchone()
                        if row:
                            if workspace_id and row["workspace_id"] != workspace_id:
                                return None
                            connection.execute(
                                "UPDATE matm_api_keys SET last_used_at = ? WHERE key_id = ?",
                                (utc_now(), row["key_id"]),
                            )
                            return {"workspaceId": row["workspace_id"], "keyId": row["key_id"]}
            if attempt < len(SQL_READ_AFTER_WRITE_RETRY_DELAYS):
                time.sleep(SQL_READ_AFTER_WRITE_RETRY_DELAYS[attempt])
        return None

    def check_idempotency(self, workspace_id, key, operation, body):
        if not key:
            return None
        record_key = "%s:%s:%s" % (workspace_id, operation, key)
        with _LOCK:
            with self._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_idempotency WHERE record_key = ?",
                    (record_key,),
                ).fetchone()
        if not row:
            return None
        if not isinstance(row, dict) and hasattr(row, "keys"):
            row = {key: row[key] for key in row.keys()}
        if row.get("body_hash") != _canonical_hash(body):
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
        replay = dict(self._json_load(row.get("response_json"), {}) or {})
        replay["idempotentReplay"] = True
        replay["idempotencyKeyExposed"] = False
        replay["_httpStatus"] = row.get("http_status") or "200 OK"
        return replay

    def record_idempotency(self, workspace_id, key, operation, body, response, http_status="200 OK"):
        if not key:
            return
        record_key = "%s:%s:%s" % (workspace_id, operation, key)
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO matm_idempotency (
                          record_key, workspace_id, operation, body_hash, response_json,
                          http_status, created_at, idempotency_key_exposed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_key,
                            workspace_id,
                            operation,
                            _canonical_hash(body),
                            json.dumps(response, sort_keys=True, separators=(",", ":")),
                            http_status,
                            utc_now(),
                            self._int_bool(False),
                        ),
                    )

    def submit_memory(self, workspace_id, actor_agent_id, scope, title, summary, tags, source, memory_type=None, subject=None, confidence=None, scope_id=None):
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
        now = utc_now()
        memory_id = _id("mem")
        review_id = _id("review")
        event = {
            "eventId": memory_id,
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
                "redactionApplied": firewall["valuesRedacted"],
                "valuesRedacted": True,
            },
            "createdAt": now,
            "status": event_status,
            "rawPrivatePayloadStored": False,
            "valuesRedacted": True,
            "reviewId": review_id,
        }
        review = {
            "reviewId": review_id,
            "workspaceId": workspace_id,
            "memoryEventId": memory_id,
            "proposedByAgentId": actor_agent_id,
            "reviewType": "memory_promotion",
            "status": review_status,
            "publicSafeSummary": event["summary"][:1000],
            "firewallDecision": firewall["decision"],
            "riskScore": firewall["riskScore"],
            "detectedThreats": firewall["detectedThreats"],
            "createdAt": now,
            "decidedAt": None,
            "reviewerAgentId": None,
            "reviewerNoteHash": None,
            "valuesRedacted": True,
        }
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
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
                            workspace_id,
                            actor_agent_id,
                            event["scope"],
                            event["scopeId"],
                            memory_type,
                            event["subject"],
                            event["title"],
                            event["summary"],
                            event["source"],
                            confidence_value,
                            promotion_state,
                            review_status,
                            event["bodyHash"],
                            1,
                            self._json_dump(event["firewall"]),
                            event_status,
                            self._int_bool(False),
                            self._int_bool(True),
                            now,
                            None,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_memory_revisions (
                          revision_id, memory_id, revision_number, public_safe_summary,
                          change_summary, body_hash, created_by_agent_id, created_at, values_redacted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self._memory_revision_id(memory_id, 1),
                            memory_id,
                            1,
                            event["summary"],
                            "initial memory submission",
                            event["bodyHash"],
                            actor_agent_id,
                            now,
                            self._int_bool(True),
                        ),
                    )
                    for tag in event["tags"]:
                        connection.execute(
                            "INSERT OR IGNORE INTO matm_memory_tags (memory_id, tag) VALUES (?, ?)",
                            (memory_id, tag),
                        )
                    connection.execute(
                        """
                        INSERT INTO matm_review_queue (
                          review_id, workspace_id, memory_id, proposed_by_agent_id, review_type, status,
                          public_safe_summary, firewall_decision, risk_score, detected_threats_json,
                          created_at, decided_at, reviewer_agent_id, reviewer_note_hash, values_redacted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            review_id,
                            workspace_id,
                            memory_id,
                            actor_agent_id,
                            "memory_promotion",
                            review_status,
                            event["summary"][:1000],
                            firewall["decision"],
                            firewall["riskScore"],
                            self._json_dump(firewall["detectedThreats"]),
                            now,
                            None,
                            None,
                            None,
                            self._int_bool(True),
                        ),
                    )
                    self._insert_outbox_sql(connection, workspace_id, "matm.memory_event.submitted", "memory_event", memory_id, event)
                    self._insert_storage_ledger_sql(connection, workspace_id, "memory_event", memory_id, event)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "memory.submit",
                        actor_agent_id,
                        memory_id,
                        {"reviewId": review_id, "firewallDecision": firewall["decision"]},
                    )
        return event

    def search_memory(self, workspace_id, query, filters=None):
        q = (query or "").lower().strip()
        filters = filters or {}
        scope_filter = (filters.get("scope") or "").strip().lower()
        scope_id_filter = (filters.get("scopeId") or filters.get("scope_id") or "").strip()
        memory_type_filter = (filters.get("memoryType") or filters.get("memory_type") or "").strip().lower()
        review_status_filter = (filters.get("reviewStatus") or filters.get("review_status") or "").strip().lower()
        promotion_state_filter = (filters.get("promotionState") or filters.get("promotion_state") or "").strip().lower()
        source_prefix_filter = (filters.get("sourcePrefix") or filters.get("source_prefix") or "").strip()
        tag_filter = (filters.get("tag") or "").strip().lower()
        actor_agent_filter = (filters.get("actorAgentId") or filters.get("actor_agent_id") or "").strip().lower()
        event_id_filter = (
            filters.get("eventId")
            or filters.get("event_id")
            or filters.get("memoryEventId")
            or filters.get("memory_event_id")
            or ""
        ).strip()
        clauses = ["workspace_id = ?", "status NOT IN ('rejected', 'quarantined')"]
        params = [workspace_id]
        if event_id_filter:
            clauses.append("memory_id = ?")
            params.append(event_id_filter)
        if scope_filter:
            clauses.append("LOWER(scope_type) = ?")
            params.append(scope_filter)
        if scope_id_filter:
            clauses.append("scope_id = ?")
            params.append(scope_id_filter)
        if memory_type_filter:
            clauses.append("LOWER(memory_type) = ?")
            params.append(memory_type_filter)
        if review_status_filter:
            clauses.append("LOWER(review_status) = ?")
            params.append(review_status_filter)
        if promotion_state_filter:
            clauses.append("LOWER(promotion_state) = ?")
            params.append(promotion_state_filter)
        if source_prefix_filter:
            clauses.append("source_uri LIKE ?")
            params.append(source_prefix_filter + "%")
        if actor_agent_filter:
            clauses.append("LOWER(actor_agent_id) = ?")
            params.append(actor_agent_filter)
        if tag_filter:
            clauses.append(
                """
                EXISTS (
                  SELECT 1 FROM matm_memory_tags t
                  WHERE t.memory_id = matm_memory_records.memory_id AND LOWER(t.tag) = ?
                )
                """
            )
            params.append(tag_filter)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_memory_records
                        WHERE %s
                        ORDER BY created_at, memory_id
                        """ % " AND ".join(clauses),
                        tuple(params),
                    )
                )
                memory_ids = [row["memory_id"] for row in rows]
                tag_rows = {}
                review_rows = {}
                if memory_ids:
                    for memory_id in memory_ids:
                        tag_rows[memory_id] = [
                            row["tag"]
                            for row in connection.execute(
                                "SELECT tag FROM matm_memory_tags WHERE memory_id = ? ORDER BY tag",
                                (memory_id,),
                            )
                        ]
                        review = connection.execute(
                            """
                            SELECT review_id FROM matm_review_queue
                            WHERE workspace_id = ? AND memory_id = ?
                            ORDER BY created_at DESC, review_id DESC
                            LIMIT 1
                            """,
                            (workspace_id, memory_id),
                        ).fetchone()
                        if review:
                            review_rows[memory_id] = review["review_id"]
        items = []
        for row in rows:
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
            if review_rows.get(row["memory_id"]):
                event["reviewId"] = review_rows[row["memory_id"]]
            haystack = " ".join(
                [
                    event.get("eventId", ""),
                    event.get("reviewId", ""),
                    event.get("actorAgentId", ""),
                    event.get("subject", ""),
                    event.get("title", ""),
                    event.get("summary", ""),
                    " ".join(event.get("tags", [])),
                    event.get("source", ""),
                    event.get("memoryType", ""),
                    event.get("scope", ""),
                    event.get("scopeId", ""),
                ]
            ).lower()
            if _memory_query_matches(q, haystack):
                items.append(_public_memory_event(event))
        return items

    def review_queue(self, workspace_id, status=None):
        wanted = (status or "").strip().lower()
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        if wanted:
            clauses.append("LOWER(status) = ?")
            params.append(wanted)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_review_queue
                        WHERE %s
                        ORDER BY created_at, review_id
                        """ % " AND ".join(clauses),
                        tuple(params),
                    )
                )
                return [self._review_from_row(row) for row in rows]

    def decide_review(self, workspace_id, review_id, reviewer_agent_id, decision, review_note=None):
        normalized = (decision or "").strip().lower()
        target_status = {
            "promote": "promoted",
            "approve": "promoted",
            "reject": "rejected",
            "quarantine": "quarantined",
        }.get(normalized)
        if not target_status:
            return None, "invalid_decision"
        now = utc_now()
        review_note_hash = _canonical_hash({"reviewNote": review_note or ""}) if review_note else None
        event_status = "active" if target_status == "promoted" else target_status
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    existing = connection.execute(
                        """
                        SELECT * FROM matm_review_queue
                        WHERE workspace_id = ? AND review_id = ?
                        """,
                        (workspace_id, review_id),
                    ).fetchone()
                    if not existing:
                        return None, "not_found"
                    connection.execute(
                        """
                        UPDATE matm_review_queue
                        SET status = ?, decided_at = ?, reviewer_agent_id = ?, reviewer_note_hash = ?
                        WHERE workspace_id = ? AND review_id = ?
                        """,
                        (target_status, now, reviewer_agent_id, review_note_hash, workspace_id, review_id),
                    )
                    memory_id = existing["memory_id"]
                    connection.execute(
                        """
                        UPDATE matm_memory_records
                        SET review_status = ?, promotion_state = ?, status = ?, updated_at = ?
                        WHERE workspace_id = ? AND memory_id = ?
                        """,
                        (target_status, target_status, event_status, now, workspace_id, memory_id),
                    )
                    updated = connection.execute(
                        """
                        SELECT * FROM matm_review_queue
                        WHERE workspace_id = ? AND review_id = ?
                        """,
                        (workspace_id, review_id),
                    ).fetchone()
                    review = self._review_from_row(updated)
                    self._insert_outbox_sql(connection, workspace_id, "matm.review.decision", "review_queue", review_id, review)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "review.decide",
                        reviewer_agent_id,
                        review_id,
                        {"decision": target_status},
                    )
                    return review, None

    def _meeting_rooms_sql(self, connection, workspace_id, agent_id=None):
        rows = list(
            connection.execute(
                """
                SELECT * FROM matm_meeting_rooms
                WHERE workspace_id = ? AND status = 'active'
                ORDER BY
                  CASE scope_type WHEN 'company' THEN 0 WHEN 'workspace' THEN 1 WHEN 'project' THEN 2 WHEN 'goal' THEN 3 WHEN 'task' THEN 4 ELSE 99 END,
                  name, room_id
                """,
                (workspace_id,),
            )
        )
        rooms = []
        for row in rows:
            room = self._room_from_row(row)
            message_rows = list(
                connection.execute(
                    """
                    SELECT * FROM matm_meeting_messages
                    WHERE workspace_id = ? AND room_id = ?
                    ORDER BY created_at, meeting_message_id
                    """,
                    (workspace_id, room["roomId"]),
                )
            )
            read_state = {}
            if agent_id:
                read_state = self._meeting_read_from_row(
                    connection.execute(
                        """
                        SELECT * FROM matm_meeting_reads
                        WHERE workspace_id = ? AND room_id = ? AND agent_id = ?
                        """,
                        (workspace_id, room["roomId"], agent_id),
                    ).fetchone()
                )
            room["messageCount"] = len(message_rows)
            room["lastMessageAt"] = message_rows[-1]["created_at"] if message_rows else None
            room["readState"] = read_state
            last_read_id = read_state.get("lastMeetingMessageId") or ""
            if not agent_id or not last_read_id:
                room["unreadCount"] = len(message_rows) if agent_id else 0
            else:
                seen = False
                unread = 0
                for message in message_rows:
                    if seen:
                        unread += 1
                    if message["meeting_message_id"] == last_read_id:
                        seen = True
                room["unreadCount"] = unread
            rooms.append(room)
        return rooms

    def meeting_rooms(self, workspace_id, agent_id=None):
        with _LOCK:
            with self._open_connection() as connection:
                return self._meeting_rooms_sql(connection, workspace_id, agent_id)

    def create_meeting_room(self, workspace_id, scope, scope_id, label=None, name=None, purpose=None, creator_agent_id=None):
        scope = (scope or "").strip().lower()
        scope_id = str(scope_id or "").strip()
        room_id = self._meeting_room_id(workspace_id, scope, scope_id)
        now = utc_now()
        default_label = "%s coordination room" % scope.title()
        default_name = "%s %s meeting" % (scope.title(), scope_id)
        default_purpose = "%s-level coordination room for assigned agents, blockers, evidence, and handoff." % scope.title()
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    existing = connection.execute(
                        """
                        SELECT * FROM matm_meeting_rooms
                        WHERE workspace_id = ? AND room_id = ?
                        """,
                        (workspace_id, room_id),
                    ).fetchone()
                    created = existing is None
                    existing_room = self._room_from_row(existing) if existing else {}
                    room = {
                        "roomId": room_id,
                        "workspaceId": workspace_id,
                        "scope": scope,
                        "scopeId": scope_id,
                        "label": redact_text(label or existing_room.get("label") or default_label),
                        "name": redact_text(name or existing_room.get("name") or default_name),
                        "purpose": redact_text(purpose or existing_room.get("purpose") or default_purpose),
                        "status": "active",
                        "defaultRoom": False,
                        "alwaysAvailable": True,
                        "createdAt": existing_room.get("createdAt") or now,
                        "updatedAt": now,
                        "valuesRedacted": True,
                        "rawPayloadExposed": False,
                    }
                    if created:
                        connection.execute(
                            """
                            INSERT INTO matm_meeting_rooms (
                              room_id, workspace_id, scope_type, scope_id, label, name, purpose, status,
                              default_room, always_available, values_redacted, raw_payload_exposed, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                room_id,
                                workspace_id,
                                scope,
                                scope_id,
                                room["label"],
                                room["name"],
                                room["purpose"],
                                room["status"],
                                self._int_bool(False),
                                self._int_bool(True),
                                self._int_bool(True),
                                self._int_bool(False),
                                room["createdAt"],
                                room["updatedAt"],
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE matm_meeting_rooms
                            SET label = ?, name = ?, purpose = ?, status = ?, default_room = ?,
                                always_available = ?, values_redacted = ?, raw_payload_exposed = ?, updated_at = ?
                            WHERE workspace_id = ? AND room_id = ?
                            """,
                            (
                                room["label"],
                                room["name"],
                                room["purpose"],
                                room["status"],
                                self._int_bool(False),
                                self._int_bool(True),
                                self._int_bool(True),
                                self._int_bool(False),
                                room["updatedAt"],
                                workspace_id,
                                room_id,
                            ),
                        )
                    self._insert_storage_ledger_sql(connection, workspace_id, "meeting_room", room_id, room)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "meeting_room.create" if created else "meeting_room.update",
                        creator_agent_id or "system",
                        room_id,
                        {"roomScope": scope, "scopeId": scope_id, "created": created},
                    )
                    return room, created

    def meeting_messages(self, workspace_id, room_id, agent_id=None, limit=50):
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        with _LOCK:
            with self._open_connection() as connection:
                room = self._room_from_row(
                    connection.execute(
                        """
                        SELECT * FROM matm_meeting_rooms
                        WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                        """,
                        (workspace_id, room_id),
                    ).fetchone()
                )
                if not room:
                    return None, [], None
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_meeting_messages
                        WHERE workspace_id = ? AND room_id = ?
                        ORDER BY created_at DESC, meeting_message_id DESC
                        LIMIT ?
                        """,
                        (workspace_id, room_id, limit_value),
                    )
                )
                rows.reverse()
                messages = [self._meeting_message_from_row(row) for row in rows]
                read_state = {}
                if agent_id:
                    read_state = self._meeting_read_from_row(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_reads
                            WHERE workspace_id = ? AND room_id = ? AND agent_id = ?
                            """,
                            (workspace_id, room_id, agent_id),
                        ).fetchone()
                    )
                return room, messages, read_state

    def meeting_message(self, workspace_id, meeting_message_id):
        meeting_message_id = str(meeting_message_id or "").strip()
        if not meeting_message_id:
            return None, None
        with _LOCK:
            with self._open_connection() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM matm_meeting_messages
                    WHERE workspace_id = ? AND meeting_message_id = ?
                    """,
                    (workspace_id, meeting_message_id),
                ).fetchone()
                message = self._meeting_message_from_row(row)
                if not message:
                    return None, None
                room = self._room_from_row(
                    connection.execute(
                        """
                        SELECT * FROM matm_meeting_rooms
                        WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                        """,
                        (workspace_id, message["roomId"]),
                    ).fetchone()
                )
                return message, room or {}

    def routing_decisions(self, workspace_id, filters=None, limit=50):
        filters = filters or {}
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 50
        limit_value = max(1, min(limit_value, 200))
        filter_columns = {
            "roomId": "source_room_id",
            "sourceRoomId": "source_room_id",
            "destinationRoomId": "destination_room_id",
            "routedAgentId": "routed_agent_id",
            "coordinatorAgentId": "coordinator_agent_id",
            "lane": "lane",
            "destinationScope": "destination_scope",
            "destinationScopeId": "destination_scope_id",
            "status": "status",
        }
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        for key, column in filter_columns.items():
            value = filters.get(key)
            if value:
                clauses.append("%s = ?" % column)
                params.append(value)
        params.append(limit_value)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_routing_decisions
                        WHERE %s
                        ORDER BY created_at DESC, routing_decision_id DESC
                        LIMIT ?
                        """ % " AND ".join(clauses),
                        tuple(params),
                    )
                )
                rows.reverse()
                return [self._routing_decision_from_row(row) for row in rows]

    def submit_routing_decision(
        self,
        workspace_id,
        source_room_id,
        coordinator_agent_id,
        routed_agent_id,
        lane,
        destination_room_id,
        specific_goal,
        expected_evidence,
        next_action,
        support_plan,
        safe_summary,
    ):
        safe_expected = [redact_text(str(item)) for item in (expected_evidence or [])]
        safe_summary = redact_text(safe_summary)
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    source_room = self._room_from_row(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_rooms
                            WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                            """,
                            (workspace_id, source_room_id),
                        ).fetchone()
                    )
                    destination_room = self._room_from_row(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_rooms
                            WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                            """,
                            (workspace_id, destination_room_id),
                        ).fetchone()
                    )
                    if not source_room or not destination_room:
                        return None, None, None, None
                    now = utc_now()
                    message = {
                        "meetingMessageId": _time_ordered_id("meetmsg"),
                        "workspaceId": workspace_id,
                        "roomId": source_room_id,
                        "scope": source_room.get("scope"),
                        "scopeId": source_room.get("scopeId"),
                        "senderAgentId": coordinator_agent_id,
                        "safeSummary": safe_summary,
                        "createdAt": now,
                        "rawMessageBodyStored": False,
                        "valuesRedacted": True,
                        "rawPayloadExposed": False,
                    }
                    decision = {
                        "routingDecisionId": _time_ordered_id("route"),
                        "workspaceId": workspace_id,
                        "sourceRoomId": source_room_id,
                        "destinationRoomId": destination_room_id,
                        "destinationScope": destination_room.get("scope"),
                        "destinationScopeId": destination_room.get("scopeId"),
                        "coordinatorAgentId": redact_text(coordinator_agent_id),
                        "routedAgentId": redact_text(routed_agent_id),
                        "lane": redact_text(lane),
                        "specificGoal": redact_text(specific_goal),
                        "expectedEvidence": safe_expected,
                        "nextAction": redact_text(next_action),
                        "supportPlan": redact_text(support_plan),
                        "meetingMessageId": message["meetingMessageId"],
                        "status": "active",
                        "createdAt": now,
                        "valuesRedacted": True,
                        "rawPayloadExposed": False,
                    }
                    connection.execute(
                        """
                        INSERT INTO matm_meeting_messages (
                          meeting_message_id, workspace_id, room_id, scope_type, scope_id, sender_agent_id,
                          safe_summary, raw_message_body_stored, values_redacted, raw_payload_exposed, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message["meetingMessageId"],
                            workspace_id,
                            source_room_id,
                            message["scope"] or "workspace",
                            message["scopeId"] or workspace_id,
                            coordinator_agent_id,
                            safe_summary,
                            self._int_bool(False),
                            self._int_bool(True),
                            self._int_bool(False),
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_routing_decisions (
                          routing_decision_id, workspace_id, source_room_id, destination_room_id,
                          destination_scope, destination_scope_id, coordinator_agent_id, routed_agent_id,
                          lane, specific_goal, expected_evidence_json, next_action, support_plan,
                          meeting_message_id, status, values_redacted, raw_payload_exposed, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            decision["routingDecisionId"],
                            workspace_id,
                            source_room_id,
                            destination_room_id,
                            decision["destinationScope"] or "workspace",
                            decision["destinationScopeId"] or workspace_id,
                            decision["coordinatorAgentId"],
                            decision["routedAgentId"],
                            decision["lane"],
                            decision["specificGoal"],
                            self._json_dump(safe_expected),
                            decision["nextAction"],
                            decision["supportPlan"],
                            message["meetingMessageId"],
                            decision["status"],
                            self._int_bool(True),
                            self._int_bool(False),
                            now,
                        ),
                    )
                    self._insert_outbox_sql(connection, workspace_id, "matm.meeting_message.submitted", "meeting_message", message["meetingMessageId"], message)
                    self._insert_outbox_sql(connection, workspace_id, "matm.routing_decision.submitted", "routing_decision", decision["routingDecisionId"], decision)
                    self._insert_storage_ledger_sql(connection, workspace_id, "meeting_message", message["meetingMessageId"], message)
                    self._insert_storage_ledger_sql(connection, workspace_id, "routing_decision", decision["routingDecisionId"], decision)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "routing_decision.submit",
                        coordinator_agent_id,
                        decision["routingDecisionId"],
                        {
                            "roomScope": source_room.get("scope"),
                            "routingDecisionCount": 1,
                            "routedAgentId": routed_agent_id,
                            "routingLane": lane,
                        },
                    )
                    return decision, message, source_room, destination_room

    def submit_meeting_message(self, workspace_id, room_id, sender_agent_id, safe_summary):
        safe_summary = redact_text(safe_summary)
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    room = self._room_from_row(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_rooms
                            WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                            """,
                            (workspace_id, room_id),
                        ).fetchone()
                    )
                    if not room:
                        return None, None
                    message = {
                        "meetingMessageId": _time_ordered_id("meetmsg"),
                        "workspaceId": workspace_id,
                        "roomId": room_id,
                        "scope": room.get("scope"),
                        "scopeId": room.get("scopeId"),
                        "senderAgentId": sender_agent_id,
                        "safeSummary": safe_summary,
                        "createdAt": utc_now(),
                        "rawMessageBodyStored": False,
                        "valuesRedacted": True,
                        "rawPayloadExposed": False,
                    }
                    connection.execute(
                        """
                        INSERT INTO matm_meeting_messages (
                          meeting_message_id, workspace_id, room_id, scope_type, scope_id, sender_agent_id,
                          safe_summary, raw_message_body_stored, values_redacted, raw_payload_exposed, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message["meetingMessageId"],
                            workspace_id,
                            room_id,
                            message["scope"] or "workspace",
                            message["scopeId"] or workspace_id,
                            sender_agent_id,
                            safe_summary,
                            self._int_bool(False),
                            self._int_bool(True),
                            self._int_bool(False),
                            message["createdAt"],
                        ),
                    )
                    self._insert_outbox_sql(connection, workspace_id, "matm.meeting_message.submitted", "meeting_message", message["meetingMessageId"], message)
                    self._insert_storage_ledger_sql(connection, workspace_id, "meeting_message", message["meetingMessageId"], message)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "meeting_message.submit",
                        sender_agent_id,
                        message["meetingMessageId"],
                        {"roomScope": room.get("scope"), "meetingMessageCount": 1},
                    )
                    return message, room

    def mark_meeting_room_read(self, workspace_id, room_id, agent_id, last_meeting_message_id=None):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    room = self._room_from_row(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_rooms
                            WHERE workspace_id = ? AND room_id = ? AND status = 'active'
                            """,
                            (workspace_id, room_id),
                        ).fetchone()
                    )
                    if not room:
                        return None, None
                    message_rows = list(
                        connection.execute(
                            """
                            SELECT * FROM matm_meeting_messages
                            WHERE workspace_id = ? AND room_id = ?
                            ORDER BY created_at, meeting_message_id
                            """,
                            (workspace_id, room_id),
                        )
                    )
                    selected = None
                    if last_meeting_message_id:
                        for row in message_rows:
                            if row["meeting_message_id"] == last_meeting_message_id:
                                selected = row
                                break
                        if not selected:
                            return None, "message_not_found"
                    elif message_rows:
                        selected = message_rows[-1]
                        last_meeting_message_id = selected["meeting_message_id"]
                    read_id = self._meeting_read_id(workspace_id, room_id, agent_id)
                    existing = connection.execute(
                        "SELECT * FROM matm_meeting_reads WHERE meeting_read_id = ?",
                        (read_id,),
                    ).fetchone()
                    created_at = existing["created_at"] if existing else utc_now()
                    updated_at = utc_now()
                    read_state = {
                        "meetingReadId": read_id,
                        "workspaceId": workspace_id,
                        "roomId": room_id,
                        "agentId": agent_id,
                        "lastMeetingMessageId": last_meeting_message_id or "",
                        "lastReadAt": selected["created_at"] if selected else updated_at,
                        "readMessageCount": len(message_rows),
                        "status": "read",
                        "createdAt": created_at,
                        "updatedAt": updated_at,
                        "rawPayloadExposed": False,
                        "valuesRedacted": True,
                    }
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO matm_meeting_reads (
                          meeting_read_id, workspace_id, room_id, agent_id, last_meeting_message_id,
                          last_read_at, read_message_count, status, values_redacted, raw_payload_exposed,
                          created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            read_id,
                            workspace_id,
                            room_id,
                            agent_id,
                            read_state["lastMeetingMessageId"],
                            read_state["lastReadAt"],
                            read_state["readMessageCount"],
                            read_state["status"],
                            self._int_bool(True),
                            self._int_bool(False),
                            created_at,
                            updated_at,
                        ),
                    )
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "meeting_room.read",
                        agent_id,
                        room_id,
                        {"roomScope": room.get("scope"), "meetingMessageCount": len(message_rows), "unreadMeetingCount": 0},
                    )
                    return read_state, None

    def _active_agent_ids_sql(self, connection, workspace_id, fallback_agent_id=None):
        rows = list(
            connection.execute(
                """
                SELECT agent_id FROM matm_agents
                WHERE workspace_id = ? AND status = 'active'
                ORDER BY agent_id
                """,
                (workspace_id,),
            )
        )
        ids = []
        for row in rows:
            agent_id = row["agent_id"]
            if agent_id and agent_id not in ids:
                ids.append(agent_id)
        if fallback_agent_id and fallback_agent_id not in ids:
            ids.append(fallback_agent_id)
        ids.sort()
        return ids

    def submit_message(self, workspace_id, sender_agent_id, target_agent_id, safe_summary, response_required):
        safe_summary = redact_text(safe_summary)
        target_agent_id = (target_agent_id or "").strip()
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    recipient_agent_ids = (
                        [target_agent_id]
                        if target_agent_id
                        else self._active_agent_ids_sql(connection, workspace_id, sender_agent_id)
                    )
                    now = utc_now()
                    message = {
                        "messageId": _id("msg"),
                        "workspaceId": workspace_id,
                        "senderAgentId": sender_agent_id,
                        "targetAgentId": target_agent_id,
                        "safeSummary": safe_summary,
                        "responseRequired": bool(response_required),
                        "createdAt": now,
                        "rawMessageBodyStored": False,
                        "valuesRedacted": True,
                    }
                    connection.execute(
                        """
                        INSERT INTO matm_messages (
                          message_id, workspace_id, sender_agent_id, target_agent_id, safe_summary,
                          response_required, raw_message_body_stored, values_redacted, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message["messageId"],
                            workspace_id,
                            sender_agent_id,
                            target_agent_id,
                            safe_summary,
                            self._int_bool(response_required),
                            self._int_bool(False),
                            self._int_bool(True),
                            now,
                        ),
                    )
                    notes = []
                    for recipient_agent_id in recipient_agent_ids:
                        note = {
                            "notificationId": _id("note"),
                            "workspaceId": workspace_id,
                            "messageId": message["messageId"],
                            "targetAgentId": recipient_agent_id,
                            "status": "unread",
                            "responseDisposition": "required_response" if response_required else "viewed_acknowledgement",
                            "createdAt": now,
                            "readAt": None,
                        }
                        notes.append(note)
                        connection.execute(
                            """
                            INSERT INTO matm_notifications (
                              notification_id, workspace_id, message_id, target_agent_id, status,
                              response_disposition, created_at, read_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                note["notificationId"],
                                workspace_id,
                                message["messageId"],
                                recipient_agent_id,
                                note["status"],
                                note["responseDisposition"],
                                note["createdAt"],
                                note["readAt"],
                            ),
                        )
                    self._insert_outbox_sql(connection, workspace_id, "matm.agent_message.submitted", "message", message["messageId"], message)
                    self._insert_storage_ledger_sql(connection, workspace_id, "message", message["messageId"], message)
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "message.submit",
                        sender_agent_id,
                        message["messageId"],
                        {
                            "deliveryCounts": {"broadcast": 1 if not target_agent_id else 0, "targeted": 1 if target_agent_id else 0},
                            "recipientCount": len(notes),
                        },
                    )
                    return message, notes

    def inbox(self, workspace_id, agent_id, message_id=None, notification_id=None, limit=None):
        agent_id = (agent_id or "").strip()
        clauses = ["n.workspace_id = ?", "n.status = 'unread'"]
        params = [workspace_id]
        try:
            limit_value = int(limit or 0)
        except (TypeError, ValueError):
            limit_value = 0
        limit_value = max(0, min(limit_value, 200))
        if agent_id:
            clauses.append("(n.target_agent_id = ? OR n.target_agent_id IS NULL OR n.target_agent_id = '')")
            params.append(agent_id)
        else:
            clauses.append("(n.target_agent_id IS NULL OR n.target_agent_id = '')")
        message_id = str(message_id or "").strip()
        notification_id = str(notification_id or "").strip()
        if message_id:
            clauses.append("n.message_id = ?")
            params.append(message_id)
        if notification_id:
            clauses.append("n.notification_id = ?")
            params.append(notification_id)
        limit_sql = ""
        if limit_value:
            limit_sql = " LIMIT ?"
            params.append(limit_value)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT
                          n.notification_id, n.workspace_id AS notification_workspace_id, n.message_id,
                          n.target_agent_id AS notification_target_agent_id, n.status AS notification_status,
                          n.response_disposition, n.created_at AS notification_created_at, n.read_at,
                          m.sender_agent_id, m.target_agent_id AS message_target_agent_id, m.safe_summary,
                          m.response_required, m.created_at AS message_created_at,
                          m.raw_message_body_stored, m.values_redacted AS message_values_redacted
                        FROM matm_notifications n
                        JOIN matm_messages m ON m.message_id = n.message_id
                        WHERE %s
                        ORDER BY n.created_at DESC, n.notification_id DESC
                        %s
                        """ % (" AND ".join(clauses), limit_sql),
                        tuple(params),
                    )
                )
        items = []
        for row in rows:
            items.append(
                {
                    "notification": {
                        "notificationId": row["notification_id"],
                        "workspaceId": row["notification_workspace_id"],
                        "messageId": row["message_id"],
                        "targetAgentId": row["notification_target_agent_id"],
                        "status": row["notification_status"],
                        "responseDisposition": row["response_disposition"],
                        "createdAt": row["notification_created_at"],
                        "readAt": row["read_at"],
                    },
                    "message": {
                        "messageId": row["message_id"],
                        "workspaceId": workspace_id,
                        "senderAgentId": row["sender_agent_id"],
                        "targetAgentId": row["message_target_agent_id"],
                        "safeSummary": row["safe_summary"],
                        "responseRequired": self._bool(row["response_required"]),
                        "createdAt": row["message_created_at"],
                        "rawMessageBodyStored": self._bool(row["raw_message_body_stored"]),
                        "valuesRedacted": self._bool(row["message_values_redacted"]),
                    },
                }
            )
        return items

    def receipts(self, workspace_id, consumer_agent_id=None):
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        if consumer_agent_id:
            clauses.append("consumer_agent_id = ?")
            params.append(consumer_agent_id)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        """
                        SELECT * FROM matm_receipts
                        WHERE %s
                        ORDER BY created_at, receipt_id
                        """ % " AND ".join(clauses),
                        tuple(params),
                    )
                )
        return [
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
            for row in rows
        ]

    def ack(self, workspace_id, notification_id, consumer_agent_id, status):
        notification_id = str(notification_id or "").strip()
        if not notification_id:
            return None
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    note = connection.execute(
                        """
                        SELECT * FROM matm_notifications
                        WHERE workspace_id = ? AND notification_id = ?
                        """,
                        (workspace_id, notification_id),
                    ).fetchone()
                    if not note:
                        return None
                    now = utc_now()
                    receipt = {
                        "receiptId": _id("receipt"),
                        "workspaceId": workspace_id,
                        "notificationId": notification_id,
                        "consumerAgentId": consumer_agent_id,
                        "status": status or "read",
                        "createdAt": now,
                        "rawPayloadExposed": False,
                        "valuesRedacted": True,
                    }
                    connection.execute(
                        """
                        UPDATE matm_notifications
                        SET status = ?, read_at = ?
                        WHERE workspace_id = ? AND notification_id = ?
                        """,
                        (receipt["status"], now, workspace_id, notification_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO matm_receipts (
                          receipt_id, workspace_id, notification_id, consumer_agent_id, status,
                          raw_payload_exposed, values_redacted, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            receipt["receiptId"],
                            workspace_id,
                            notification_id,
                            consumer_agent_id,
                            receipt["status"],
                            self._int_bool(False),
                            self._int_bool(True),
                            now,
                        ),
                    )
                    self._record_audit_sql(
                        connection,
                        workspace_id,
                        "notification.ack",
                        consumer_agent_id,
                        notification_id,
                        {"status": receipt["status"]},
                    )
                    return receipt

    def _sync_device_record_id(self, workspace_id, device_id):
        return "syncdevice-" + _hash("%s:%s" % (workspace_id, device_id))[:20]

    def _sync_head_record_id(self, workspace_id, logical_memory_id):
        return "synchead-" + _hash("%s:%s" % (workspace_id, logical_memory_id))[:20]

    def sync_device(self, workspace_id, device_id):
        if not device_id:
            return None
        with _LOCK:
            with self._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_sync_devices WHERE workspace_id = ? AND device_id = ?",
                    (workspace_id, device_id),
                ).fetchone()
        if not row:
            return None
        return {
            "deviceId": row["device_id"],
            "workspaceId": row["workspace_id"],
            "agentId": row["agent_id"],
            "label": row["label"],
            "status": row["status"],
            "authorityEpoch": row["authority_epoch"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "revokedAt": row["revoked_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def register_sync_device(self, workspace_id, agent_id, device_id=None, label=None):
        now = utc_now()
        device_id = (device_id or _id("device")).strip()
        record_id = self._sync_device_record_id(workspace_id, device_id)
        safe_label = redact_text(label or device_id)
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    existing = connection.execute(
                        "SELECT * FROM matm_sync_devices WHERE workspace_id = ? AND device_id = ?",
                        (workspace_id, device_id),
                    ).fetchone()
                    if existing:
                        connection.execute(
                            """
                            UPDATE matm_sync_devices
                            SET agent_id = ?, label = ?, status = 'active', updated_at = ?
                            WHERE workspace_id = ? AND device_id = ?
                            """,
                            (agent_id or existing["agent_id"], safe_label, now, workspace_id, device_id),
                        )
                    else:
                        connection.execute(
                            """
                            INSERT INTO matm_sync_devices (
                              device_record_id, workspace_id, device_id, agent_id, label, status,
                              authority_epoch, created_at, updated_at, revoked_at, values_redacted,
                              raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_id,
                                workspace_id,
                                device_id,
                                agent_id or "",
                                safe_label,
                                "active",
                                1,
                                now,
                                now,
                                None,
                                self._int_bool(True),
                                self._int_bool(False),
                            ),
                        )
                    self._record_audit_sql(connection, workspace_id, "sync.device.register", agent_id, device_id, {"deviceIdHash": _hash(device_id), "valuesRedacted": True})
        return self.sync_device(workspace_id, device_id)

    def rotate_sync_device(self, workspace_id, device_id, agent_id):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    row = connection.execute(
                        "SELECT * FROM matm_sync_devices WHERE workspace_id = ? AND device_id = ?",
                        (workspace_id, device_id),
                    ).fetchone()
                    if not row:
                        return None, "device_not_found"
                    if row["status"] == "revoked":
                        return None, "device_revoked"
                    epoch = int(row["authority_epoch"] or 1) + 1
                    now = utc_now()
                    connection.execute(
                        """
                        UPDATE matm_sync_devices
                        SET authority_epoch = ?, updated_at = ?
                        WHERE workspace_id = ? AND device_id = ?
                        """,
                        (epoch, now, workspace_id, device_id),
                    )
                    self._record_audit_sql(connection, workspace_id, "sync.device.rotate", agent_id, device_id, {"authorityEpoch": epoch})
        return self.sync_device(workspace_id, device_id), None

    def revoke_sync_device(self, workspace_id, device_id, agent_id):
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    row = connection.execute(
                        "SELECT * FROM matm_sync_devices WHERE workspace_id = ? AND device_id = ?",
                        (workspace_id, device_id),
                    ).fetchone()
                    if not row:
                        return None, "device_not_found"
                    now = utc_now()
                    connection.execute(
                        """
                        UPDATE matm_sync_devices
                        SET status = 'revoked', revoked_at = ?, updated_at = ?
                        WHERE workspace_id = ? AND device_id = ?
                        """,
                        (now, now, workspace_id, device_id),
                    )
                    self._record_audit_sql(connection, workspace_id, "sync.device.revoke", agent_id, device_id, {"authorityEpoch": row["authority_epoch"]})
        return self.sync_device(workspace_id, device_id), None

    def _sync_head_from_row(self, row):
        if not row:
            return None
        return {
            "logicalMemoryId": row["logical_memory_id"],
            "workspaceId": row["workspace_id"],
            "headRevisionId": row["head_revision_id"],
            "serverSequence": row["server_sequence"],
            "indexedThroughSequence": row["indexed_through_sequence"],
            "status": row["status"],
            "updatedAt": row["updated_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _sync_revision_from_row(self, row):
        return {
            "syncRevisionId": row["sync_revision_id"],
            "workspaceId": row["workspace_id"],
            "logicalMemoryId": row["logical_memory_id"],
            "parentRevisionId": row["parent_revision_id"],
            "memoryEventId": row["memory_event_id"],
            "actorAgentId": row["actor_agent_id"],
            "deviceId": row["device_id"],
            "deviceEpoch": row["device_epoch"],
            "operation": row["operation"],
            "status": row["status"],
            "conflict": self._bool(row["conflict"]),
            "conflictCode": row["conflict_code"],
            "serverSequence": row["server_sequence"],
            "bodyHash": row["body_hash"],
            "source": row["source_uri"],
            "title": row["title"],
            "summary": row["public_safe_summary"],
            "scope": row["scope_type"],
            "scopeId": row["scope_id"],
            "memoryType": row["memory_type"],
            "tombstone": self._bool(row["tombstone"]),
            "createdAt": row["created_at"],
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _sync_receipt_from_row(self, row):
        return {
            "receiptId": row["receipt_id"],
            "workspaceId": row["workspace_id"],
            "idempotencyKeyHash": row["idempotency_key_hash"],
            "bodyHash": row["body_hash"],
            "logicalMemoryId": row["logical_memory_id"],
            "syncRevisionId": row["sync_revision_id"],
            "serverSequence": row["server_sequence"],
            "status": row["status"],
            "conflict": self._bool(row["conflict"]),
            "conflictCode": row["conflict_code"],
            "currentHeadRevisionId": row["current_head_revision_id"],
            "httpStatus": row["http_status"],
            "createdAt": row["created_at"],
            "idempotencyKeyExposed": self._bool(row["idempotency_key_exposed"]),
            "valuesRedacted": self._bool(row["values_redacted"]),
            "rawCredentialExposed": self._bool(row["raw_credential_exposed"]),
            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
        }

    def _sql_value(self, row, key, default=None):
        if not row:
            return default
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default

    def _sync_next_sequence_sql(self, connection, workspace_id):
        row = connection.execute(
            "SELECT COALESCE(MAX(server_sequence), 0) AS max_sequence FROM matm_sync_revisions WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        return int(self._sql_value(row, "max_sequence", 0) or 0) + 1

    def submit_sync_mutation(self, workspace_id, actor_agent_id, body, idempotency_key=""):
        body = body or {}
        operation = (body.get("operation") or "upsert").strip().lower()
        if operation not in ("upsert", "delete", "hard_forget"):
            operation = "upsert"
        logical_memory_id = (body.get("logicalMemoryId") or body.get("logical_memory_id") or "").strip()
        if not logical_memory_id and operation == "upsert":
            logical_memory_id = _id("lm")
        parent_revision_id = (body.get("parentRevisionId") or body.get("parent_revision_id") or "").strip()
        device_id = (body.get("deviceId") or body.get("device_id") or "").strip()
        device_epoch = int(body.get("deviceEpoch") or body.get("device_epoch") or 0)
        body_hash = (body.get("bodyHash") or body.get("body_hash") or "").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{64}", body_hash or ""):
            body_hash = _canonical_hash({"operation": operation, "logicalMemoryId": logical_memory_id, "parentRevisionId": parent_revision_id, "summary": body.get("summary") or "", "title": body.get("title") or "", "source": body.get("source") or body.get("sourceRef") or ""})
        idempotency_hash = ("sha256:" + _hash(idempotency_key)) if idempotency_key else ""
        now = utc_now()
        revision = None
        head = None
        with _LOCK:
            with self._open_connection() as connection:
                with connection:
                    device = None
                    if device_id:
                        device = connection.execute(
                            "SELECT * FROM matm_sync_devices WHERE workspace_id = ? AND device_id = ?",
                            (workspace_id, device_id),
                        ).fetchone()
                    reject_code = ""
                    if device_id and not device:
                        reject_code = "device_not_registered"
                    elif device and device["status"] == "revoked":
                        reject_code = "device_revoked"
                    elif device and device_epoch and int(device["authority_epoch"] or 1) != device_epoch:
                        reject_code = "device_epoch_mismatch"
                    elif operation == "hard_forget":
                        reject_code = "hard_forget_not_supported"
                    elif not logical_memory_id:
                        reject_code = "logical_memory_id_required"
                    head_row = connection.execute(
                        "SELECT * FROM matm_sync_heads WHERE workspace_id = ? AND logical_memory_id = ?",
                        (workspace_id, logical_memory_id),
                    ).fetchone() if logical_memory_id else None
                    current_head_revision = self._sql_value(head_row, "head_revision_id", "") or ""
                    current_status = self._sql_value(head_row, "status", "") or ""
                    conflict_code = ""
                    if not reject_code:
                        if operation in ("upsert", "delete") and head_row and parent_revision_id != current_head_revision:
                            conflict_code = "parent_revision_mismatch"
                        if operation == "upsert" and current_status == "tombstoned":
                            conflict_code = "tombstone_resurrection_blocked"
                        if operation == "delete" and not head_row:
                            conflict_code = "head_not_found"
                    server_sequence = self._sync_next_sequence_sql(connection, workspace_id)
                    revision_id = _id("syncrev")
                    receipt_id = _id("syncreceipt")
                    status = "rejected" if reject_code else ("conflict" if conflict_code else "applied")
                    http_status = "409 Conflict" if status in ("rejected", "conflict") else "202 Accepted"
                    if status != "rejected":
                        revision = {
                            "syncRevisionId": revision_id,
                            "workspaceId": workspace_id,
                            "logicalMemoryId": logical_memory_id,
                            "parentRevisionId": parent_revision_id,
                            "memoryEventId": "",
                            "actorAgentId": actor_agent_id,
                            "deviceId": device_id,
                            "deviceEpoch": device_epoch or (int(device["authority_epoch"] or 0) if device else 0),
                            "operation": operation,
                            "status": status,
                            "conflict": bool(conflict_code),
                            "conflictCode": conflict_code,
                            "serverSequence": server_sequence,
                            "bodyHash": body_hash,
                            "source": redact_text(body.get("sourceRef") or body.get("source") or "api"),
                            "title": redact_text(body.get("title") or logical_memory_id),
                            "summary": redact_text(body.get("summary") or ""),
                            "scope": (body.get("scope") or "workspace").strip().lower(),
                            "scopeId": body.get("scopeId") or body.get("scope_id") or workspace_id,
                            "memoryType": (body.get("memoryType") or body.get("memory_type") or "note").strip().lower(),
                            "tombstone": operation == "delete",
                            "createdAt": now,
                            "valuesRedacted": True,
                            "rawPayloadExposed": False,
                        }
                        connection.execute(
                            """
                            INSERT INTO matm_sync_revisions (
                              sync_revision_id, workspace_id, logical_memory_id, parent_revision_id,
                              memory_event_id, actor_agent_id, device_id, device_epoch, operation,
                              status, conflict, conflict_code, server_sequence, body_hash, source_uri,
                              title, public_safe_summary, scope_type, scope_id, memory_type, tombstone,
                              created_at, values_redacted, raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                revision_id,
                                workspace_id,
                                logical_memory_id,
                                parent_revision_id,
                                "",
                                actor_agent_id,
                                device_id,
                                revision["deviceEpoch"],
                                operation,
                                status,
                                self._int_bool(bool(conflict_code)),
                                conflict_code,
                                server_sequence,
                                body_hash,
                                revision["source"],
                                revision["title"],
                                revision["summary"],
                                revision["scope"],
                                revision["scopeId"],
                                revision["memoryType"],
                                self._int_bool(operation == "delete"),
                                now,
                                self._int_bool(True),
                                self._int_bool(False),
                            ),
                        )
                        if status == "applied":
                            connection.execute(
                                """
                                INSERT OR REPLACE INTO matm_sync_heads (
                                  head_record_id, logical_memory_id, workspace_id, head_revision_id, server_sequence,
                                  indexed_through_sequence, status, updated_at, values_redacted,
                                  raw_payload_exposed
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    self._sync_head_record_id(workspace_id, logical_memory_id),
                                    logical_memory_id,
                                    workspace_id,
                                    revision_id,
                                    server_sequence,
                                    server_sequence,
                                    "tombstoned" if operation == "delete" else "active",
                                    now,
                                    self._int_bool(True),
                                    self._int_bool(False),
                                ),
                            )
                        self._insert_outbox_sql(connection, workspace_id, "matm.sync.revision.%s" % status, "sync_revision", revision_id, revision)
                        self._insert_storage_ledger_sql(connection, workspace_id, "sync_revision", revision_id, revision)
                    receipt = {
                        "receiptId": receipt_id,
                        "workspaceId": workspace_id,
                        "idempotencyKeyHash": idempotency_hash,
                        "bodyHash": body_hash,
                        "logicalMemoryId": logical_memory_id,
                        "syncRevisionId": revision_id if revision else "",
                        "serverSequence": server_sequence if revision else 0,
                        "status": status,
                        "conflict": bool(conflict_code),
                        "conflictCode": conflict_code or reject_code,
                        "currentHeadRevisionId": current_head_revision,
                        "httpStatus": http_status,
                        "createdAt": now,
                        "idempotencyKeyExposed": False,
                        "valuesRedacted": True,
                        "rawCredentialExposed": False,
                        "rawPayloadExposed": False,
                    }
                    connection.execute(
                        """
                        INSERT INTO matm_sync_receipts (
                          receipt_id, workspace_id, idempotency_key_hash, body_hash,
                          logical_memory_id, sync_revision_id, server_sequence, status, conflict,
                          conflict_code, current_head_revision_id, http_status, created_at,
                          idempotency_key_exposed, values_redacted, raw_credential_exposed,
                          raw_payload_exposed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            receipt_id,
                            workspace_id,
                            idempotency_hash,
                            body_hash,
                            logical_memory_id,
                            receipt["syncRevisionId"] or None,
                            receipt["serverSequence"],
                            status,
                            self._int_bool(bool(conflict_code)),
                            receipt["conflictCode"],
                            current_head_revision,
                            http_status,
                            now,
                            self._int_bool(False),
                            self._int_bool(True),
                            self._int_bool(False),
                            self._int_bool(False),
                        ),
                    )
                    self._record_audit_sql(connection, workspace_id, "sync.mutation.%s" % status, actor_agent_id, receipt_id, {"logicalMemoryId": logical_memory_id, "serverSequence": receipt["serverSequence"], "conflictCode": receipt["conflictCode"]})
                    head = connection.execute(
                        "SELECT * FROM matm_sync_heads WHERE workspace_id = ? AND logical_memory_id = ?",
                        (workspace_id, logical_memory_id),
                    ).fetchone() if logical_memory_id else None
        return {
            "ok": status == "applied",
            "persisted": True,
            "receipt": self._public_sync_receipt(receipt),
            "revision": self._public_sync_revision(revision) if revision else None,
            "head": self._sync_head_from_row(head),
            "serverSequence": receipt["serverSequence"],
            "indexedThroughSequence": self._sql_value(head, "indexed_through_sequence", 0) or 0,
            "conflict": status == "conflict",
            "status": status,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }, http_status

    def sync_receipt(self, workspace_id, idempotency_key=None, receipt_id=None):
        idempotency_hash = "sha256:" + _hash(idempotency_key) if idempotency_key else ""
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        if receipt_id:
            clauses.append("receipt_id = ?")
            params.append(receipt_id)
        elif idempotency_hash:
            clauses.append("idempotency_key_hash = ?")
            params.append(idempotency_hash)
        else:
            return None
        with _LOCK:
            with self._open_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM matm_sync_receipts WHERE %s ORDER BY created_at DESC, receipt_id DESC" % " AND ".join(clauses),
                    tuple(params),
                ).fetchone()
        return self._public_sync_receipt(self._sync_receipt_from_row(row)) if row else None

    def sync_changes(self, workspace_id, after_sequence=0, limit=50, logical_memory_id=None):
        try:
            after_value = int(after_sequence or 0)
        except (TypeError, ValueError):
            after_value = 0
        limit_value = max(1, min(int(limit or 50), 200))
        clauses = ["workspace_id = ?", "server_sequence > ?"]
        params = [workspace_id, after_value]
        if logical_memory_id:
            clauses.append("logical_memory_id = ?")
            params.append(logical_memory_id)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        "SELECT * FROM matm_sync_revisions WHERE %s ORDER BY server_sequence ASC LIMIT ?" % " AND ".join(clauses),
                        tuple(params + [limit_value + 1]),
                    )
                )
                latest_row = connection.execute(
                    "SELECT COALESCE(MAX(server_sequence), 0) AS max_sequence FROM matm_sync_revisions WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
        page_rows = rows[:limit_value]
        page = [self._public_sync_revision(self._sync_revision_from_row(row)) for row in page_rows]
        next_after = int(page[-1].get("serverSequence") or after_value) if page else after_value
        return {
            "items": page,
            "count": len(page),
            "hasMore": len(rows) > len(page_rows),
            "nextAfterSequence": next_after,
            "indexedThroughSequence": int(self._sql_value(latest_row, "max_sequence", 0) or 0),
            "checkpoint": {
                "workspaceIdHash": "sha256:" + _hash(workspace_id),
                "afterSequence": after_value,
                "nextAfterSequence": next_after,
                "valuesRedacted": True,
            },
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
        }

    def sync_heads(self, workspace_id, logical_memory_id=None):
        clauses = ["workspace_id = ?"]
        params = [workspace_id]
        if logical_memory_id:
            clauses.append("logical_memory_id = ?")
            params.append(logical_memory_id)
        with _LOCK:
            with self._open_connection() as connection:
                rows = list(
                    connection.execute(
                        "SELECT * FROM matm_sync_heads WHERE %s ORDER BY logical_memory_id" % " AND ".join(clauses),
                        tuple(params),
                    )
                )
        return [self._sync_head_from_row(row) for row in rows]

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

                for row in connection.execute("SELECT * FROM matm_meeting_rooms ORDER BY created_at, room_id"):
                    data["meetingRooms"][row["room_id"]] = {
                        "roomId": row["room_id"],
                        "workspaceId": row["workspace_id"],
                        "scope": row["scope_type"],
                        "scopeId": row["scope_id"],
                        "label": row["label"],
                        "name": row["name"],
                        "purpose": row["purpose"],
                        "status": row["status"],
                        "defaultRoom": self._bool(row["default_room"]),
                        "alwaysAvailable": self._bool(row["always_available"]),
                        "createdAt": row["created_at"],
                        "valuesRedacted": self._bool(row["values_redacted"]),
                        "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                    }
                    if row["updated_at"]:
                        data["meetingRooms"][row["room_id"]]["updatedAt"] = row["updated_at"]

                for row in connection.execute("SELECT * FROM matm_meeting_messages ORDER BY created_at, meeting_message_id"):
                    data["meetingMessages"].append(
                        {
                            "meetingMessageId": row["meeting_message_id"],
                            "workspaceId": row["workspace_id"],
                            "roomId": row["room_id"],
                            "scope": row["scope_type"],
                            "scopeId": row["scope_id"],
                            "senderAgentId": row["sender_agent_id"],
                            "safeSummary": row["safe_summary"],
                            "createdAt": row["created_at"],
                            "rawMessageBodyStored": self._bool(row["raw_message_body_stored"]),
                            "valuesRedacted": self._bool(row["values_redacted"]),
                            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_routing_decisions ORDER BY created_at, routing_decision_id"):
                    data["routingDecisions"].append(self._routing_decision_from_row(row))

                for row in connection.execute("SELECT * FROM matm_meeting_reads ORDER BY updated_at, meeting_read_id"):
                    data["meetingReads"].append(
                        {
                            "meetingReadId": row["meeting_read_id"],
                            "workspaceId": row["workspace_id"],
                            "roomId": row["room_id"],
                            "agentId": row["agent_id"],
                            "lastMeetingMessageId": row["last_meeting_message_id"],
                            "lastReadAt": row["last_read_at"],
                            "readMessageCount": row["read_message_count"],
                            "status": row["status"],
                            "createdAt": row["created_at"],
                            "updatedAt": row["updated_at"],
                            "valuesRedacted": self._bool(row["values_redacted"]),
                            "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                        }
                    )

                for row in connection.execute("SELECT * FROM matm_sync_devices ORDER BY created_at, device_id"):
                    key = "%s:%s" % (row["workspace_id"], row["device_id"])
                    data["syncDevices"][key] = {
                        "deviceId": row["device_id"],
                        "workspaceId": row["workspace_id"],
                        "agentId": row["agent_id"],
                        "label": row["label"],
                        "status": row["status"],
                        "authorityEpoch": row["authority_epoch"],
                        "createdAt": row["created_at"],
                        "updatedAt": row["updated_at"],
                        "revokedAt": row["revoked_at"],
                        "valuesRedacted": self._bool(row["values_redacted"]),
                        "rawPayloadExposed": self._bool(row["raw_payload_exposed"]),
                    }

                for row in connection.execute("SELECT * FROM matm_sync_heads ORDER BY updated_at, logical_memory_id"):
                    key = "%s:%s" % (row["workspace_id"], row["logical_memory_id"])
                    data["syncHeads"][key] = self._sync_head_from_row(row)

                for row in connection.execute("SELECT * FROM matm_sync_revisions ORDER BY server_sequence, sync_revision_id"):
                    data["syncRevisions"].append(self._sync_revision_from_row(row))

                for row in connection.execute("SELECT * FROM matm_sync_receipts ORDER BY created_at, receipt_id"):
                    data["syncReceipts"].append(self._sync_receipt_from_row(row))

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

                    for room in data.get("meetingRooms", {}).values():
                        connection.execute(
                            """
                            INSERT INTO matm_meeting_rooms (
                              room_id, workspace_id, scope_type, scope_id, label, name, purpose, status,
                              default_room, always_available, values_redacted, raw_payload_exposed, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                room.get("roomId"),
                                room.get("workspaceId"),
                                room.get("scope") or "workspace",
                                room.get("scopeId") or room.get("workspaceId"),
                                room.get("label") or "Meeting room",
                                room.get("name") or "Meeting room",
                                room.get("purpose") or "Agent coordination meeting room.",
                                room.get("status") or "active",
                                self._int_bool(room.get("defaultRoom", True)),
                                self._int_bool(room.get("alwaysAvailable", True)),
                                self._int_bool(room.get("valuesRedacted", True)),
                                self._int_bool(room.get("rawPayloadExposed")),
                                room.get("createdAt") or utc_now(),
                                room.get("updatedAt"),
                            ),
                        )

                    for message in data.get("meetingMessages", []):
                        connection.execute(
                            """
                            INSERT INTO matm_meeting_messages (
                              meeting_message_id, workspace_id, room_id, scope_type, scope_id, sender_agent_id,
                              safe_summary, raw_message_body_stored, values_redacted, raw_payload_exposed, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                message.get("meetingMessageId"),
                                message.get("workspaceId"),
                                message.get("roomId"),
                                message.get("scope") or "workspace",
                                message.get("scopeId") or message.get("workspaceId"),
                                message.get("senderAgentId"),
                                message.get("safeSummary") or "",
                                self._int_bool(message.get("rawMessageBodyStored")),
                                self._int_bool(message.get("valuesRedacted", True)),
                                self._int_bool(message.get("rawPayloadExposed")),
                                message.get("createdAt") or utc_now(),
                            ),
                        )

                    for decision in data.get("routingDecisions", []):
                        connection.execute(
                            """
                            INSERT INTO matm_routing_decisions (
                              routing_decision_id, workspace_id, source_room_id, destination_room_id,
                              destination_scope, destination_scope_id, coordinator_agent_id, routed_agent_id,
                              lane, specific_goal, expected_evidence_json, next_action, support_plan,
                              meeting_message_id, status, values_redacted, raw_payload_exposed, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                decision.get("routingDecisionId"),
                                decision.get("workspaceId"),
                                decision.get("sourceRoomId"),
                                decision.get("destinationRoomId"),
                                decision.get("destinationScope") or "workspace",
                                decision.get("destinationScopeId") or decision.get("workspaceId"),
                                decision.get("coordinatorAgentId"),
                                decision.get("routedAgentId"),
                                decision.get("lane") or "coordination",
                                decision.get("specificGoal") or "",
                                self._json_dump(decision.get("expectedEvidence") or []),
                                decision.get("nextAction") or "",
                                decision.get("supportPlan") or "",
                                decision.get("meetingMessageId"),
                                decision.get("status") or "active",
                                self._int_bool(decision.get("valuesRedacted", True)),
                                self._int_bool(decision.get("rawPayloadExposed")),
                                decision.get("createdAt") or utc_now(),
                            ),
                        )

                    for read_state in data.get("meetingReads", []):
                        connection.execute(
                            """
                            INSERT INTO matm_meeting_reads (
                              meeting_read_id, workspace_id, room_id, agent_id, last_meeting_message_id,
                              last_read_at, read_message_count, status, values_redacted, raw_payload_exposed,
                              created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                read_state.get("meetingReadId"),
                                read_state.get("workspaceId"),
                                read_state.get("roomId"),
                                read_state.get("agentId"),
                                read_state.get("lastMeetingMessageId"),
                                read_state.get("lastReadAt"),
                                int(read_state.get("readMessageCount") or 0),
                                read_state.get("status") or "read",
                                self._int_bool(read_state.get("valuesRedacted", True)),
                                self._int_bool(read_state.get("rawPayloadExposed")),
                                read_state.get("createdAt") or utc_now(),
                                read_state.get("updatedAt"),
                            ),
                        )

                    for device in data.get("syncDevices", {}).values():
                        device_id = device.get("deviceId")
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO matm_sync_devices (
                              device_record_id, workspace_id, device_id, agent_id, label, status,
                              authority_epoch, created_at, updated_at, revoked_at, values_redacted,
                              raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                self._sync_device_record_id(device.get("workspaceId"), device_id),
                                device.get("workspaceId"),
                                device_id,
                                device.get("agentId"),
                                device.get("label") or device_id,
                                device.get("status") or "active",
                                int(device.get("authorityEpoch") or 1),
                                device.get("createdAt") or utc_now(),
                                device.get("updatedAt"),
                                device.get("revokedAt"),
                                self._int_bool(device.get("valuesRedacted", True)),
                                self._int_bool(device.get("rawPayloadExposed")),
                            ),
                        )

                    for head in data.get("syncHeads", {}).values():
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO matm_sync_heads (
                              head_record_id, logical_memory_id, workspace_id, head_revision_id, server_sequence,
                              indexed_through_sequence, status, updated_at, values_redacted,
                              raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                self._sync_head_record_id(head.get("workspaceId"), head.get("logicalMemoryId")),
                                head.get("logicalMemoryId"),
                                head.get("workspaceId"),
                                head.get("headRevisionId"),
                                int(head.get("serverSequence") or 0),
                                int(head.get("indexedThroughSequence") or head.get("serverSequence") or 0),
                                head.get("status") or "active",
                                head.get("updatedAt") or utc_now(),
                                self._int_bool(head.get("valuesRedacted", True)),
                                self._int_bool(head.get("rawPayloadExposed")),
                            ),
                        )

                    for revision in data.get("syncRevisions", []):
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO matm_sync_revisions (
                              sync_revision_id, workspace_id, logical_memory_id, parent_revision_id,
                              memory_event_id, actor_agent_id, device_id, device_epoch, operation,
                              status, conflict, conflict_code, server_sequence, body_hash, source_uri,
                              title, public_safe_summary, scope_type, scope_id, memory_type, tombstone,
                              created_at, values_redacted, raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                revision.get("syncRevisionId"),
                                revision.get("workspaceId"),
                                revision.get("logicalMemoryId"),
                                revision.get("parentRevisionId"),
                                revision.get("memoryEventId"),
                                revision.get("actorAgentId"),
                                revision.get("deviceId"),
                                int(revision.get("deviceEpoch") or 0),
                                revision.get("operation") or "upsert",
                                revision.get("status") or "applied",
                                self._int_bool(revision.get("conflict")),
                                revision.get("conflictCode"),
                                int(revision.get("serverSequence") or 0),
                                revision.get("bodyHash") or _canonical_hash(revision),
                                revision.get("source") or "api",
                                revision.get("title") or revision.get("logicalMemoryId"),
                                revision.get("summary") or "",
                                revision.get("scope") or "workspace",
                                revision.get("scopeId") or revision.get("workspaceId"),
                                revision.get("memoryType") or "note",
                                self._int_bool(revision.get("tombstone")),
                                revision.get("createdAt") or utc_now(),
                                self._int_bool(revision.get("valuesRedacted", True)),
                                self._int_bool(revision.get("rawPayloadExposed")),
                            ),
                        )

                    for receipt in data.get("syncReceipts", []):
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO matm_sync_receipts (
                              receipt_id, workspace_id, idempotency_key_hash, body_hash,
                              logical_memory_id, sync_revision_id, server_sequence, status, conflict,
                              conflict_code, current_head_revision_id, http_status, created_at,
                              idempotency_key_exposed, values_redacted, raw_credential_exposed,
                              raw_payload_exposed
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                receipt.get("receiptId"),
                                receipt.get("workspaceId"),
                                receipt.get("idempotencyKeyHash"),
                                receipt.get("bodyHash") or _canonical_hash(receipt),
                                receipt.get("logicalMemoryId"),
                                receipt.get("syncRevisionId") or None,
                                int(receipt.get("serverSequence") or 0),
                                receipt.get("status") or "applied",
                                self._int_bool(receipt.get("conflict")),
                                receipt.get("conflictCode"),
                                receipt.get("currentHeadRevisionId"),
                                receipt.get("httpStatus") or "200 OK",
                                receipt.get("createdAt") or utc_now(),
                                self._int_bool(receipt.get("idempotencyKeyExposed")),
                                self._int_bool(receipt.get("valuesRedacted", True)),
                                self._int_bool(receipt.get("rawCredentialExposed")),
                                self._int_bool(receipt.get("rawPayloadExposed")),
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

    def _normalize_value(self, value):
        if isinstance(value, (datetime.datetime, datetime.date)):
            text = value.isoformat()
            if isinstance(value, datetime.datetime) and value.tzinfo is None:
                text += "Z"
            return text
        return value

    def _normalize_row(self, row):
        if isinstance(row, dict):
            return {key: self._normalize_value(value) for key, value in row.items()}
        if hasattr(row, "keys"):
            return {key: self._normalize_value(row[key]) for key in row.keys()}
        return row

    def __iter__(self):
        return iter(self.fetchall())

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return self._normalize_row(row)

    def fetchall(self):
        return [self._normalize_row(row) for row in self.cursor.fetchall()]


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


def _mysql_secret_config_path():
    configured = os.environ.get("MEMORYENDPOINTS_MYSQL_CONFIG_PATH")
    return Path(configured) if configured else ROOT / ".local-secrets" / "mysql.json"


def _diagnostic_fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _mysql_diagnostic_error(exc):
    args = getattr(exc, "args", ()) or ()
    mysql_error_number = args[0] if args and isinstance(args[0], int) else None
    message = str(exc).lower()
    if "required database settings are missing" in message:
        error_code = "mysql_missing_settings"
    elif mysql_error_number == 1045 or "access denied" in message or "authentication" in message:
        error_code = "mysql_auth_failed"
    elif mysql_error_number == 1044:
        error_code = "mysql_database_access_denied"
    elif mysql_error_number == 1049 or "unknown database" in message:
        error_code = "mysql_database_missing"
    elif "connect" in message:
        error_code = "mysql_connection_failed"
    else:
        error_code = "mysql_unavailable"
    return {
        "errorCode": error_code,
        "errorType": exc.__class__.__name__,
        "mysqlErrorNumber": mysql_error_number,
        "sqlState": getattr(exc, "sqlstate", None),
        "messageFingerprint": _diagnostic_fingerprint(str(exc)),
        "valuesRedacted": True,
    }


def _mysql_config_from_secret_file():
    path = _mysql_secret_config_path()
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
        "unix_socket": payload.get("unix_socket") or payload.get("unixSocket") or "",
    }


def mysql_config_diagnostics():
    path = _mysql_secret_config_path()
    env_keys = [
        "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
        "MEMORYENDPOINTS_MYSQL_URL",
        "DATABASE_URL",
        "MEMORYENDPOINTS_MYSQL_HOST",
        "MYSQL_HOST",
        "MEMORYENDPOINTS_MYSQL_PORT",
        "MYSQL_PORT",
        "MEMORYENDPOINTS_MYSQL_USER",
        "MYSQL_USER",
        "MEMORYENDPOINTS_MYSQL_PASSWORD",
        "MYSQL_PASSWORD",
        "MEMORYENDPOINTS_MYSQL_DATABASE",
        "MYSQL_DATABASE",
        "MEMORYENDPOINTS_MYSQL_UNIX_SOCKET",
        "MYSQL_UNIX_SOCKET",
    ]
    report = {
        "schemaVersion": "memoryendpoints.mysql_config_diagnostics.v1",
        "secretConfigPathFingerprint": _diagnostic_fingerprint(str(path)),
        "secretConfigPathExists": path.exists(),
        "secretConfigPathConfigured": bool(os.environ.get("MEMORYENDPOINTS_MYSQL_CONFIG_PATH")),
        "environmentPresence": {key: bool(os.environ.get(key)) for key in env_keys},
        "socketCandidates": [
            {
                "candidateId": "var_lib_mysql",
                "pathFingerprint": _diagnostic_fingerprint("/var/lib/mysql/mysql.sock"),
                "exists": Path("/var/lib/mysql/mysql.sock").exists(),
            },
            {
                "candidateId": "tmp_mysql",
                "pathFingerprint": _diagnostic_fingerprint("/tmp/mysql.sock"),
                "exists": Path("/tmp/mysql.sock").exists(),
            },
            {
                "candidateId": "run_mysqld",
                "pathFingerprint": _diagnostic_fingerprint("/var/run/mysqld/mysqld.sock"),
                "exists": Path("/var/run/mysqld/mysqld.sock").exists(),
            },
        ],
        "valuesRedacted": True,
    }
    url = os.environ.get("MEMORYENDPOINTS_MYSQL_URL") or os.environ.get("DATABASE_URL")
    if path.exists():
        source = "secret_file"
    elif url:
        source = "url"
    elif any(os.environ.get(key) for key in env_keys if not key.endswith("_URL") and key != "DATABASE_URL"):
        source = "individual_environment"
    else:
        source = "default_missing_settings"
    report["selectedCredentialSource"] = source
    try:
        config = _mysql_config_from_env()
        host = config.get("host") or ""
        report["selectedConfig"] = {
            "hostCategory": "localhost" if host in ("localhost", "127.0.0.1", "::1") else "remote",
            "hostFingerprint": _diagnostic_fingerprint(host),
            "port": int(config.get("port") or 0),
            "databaseFingerprint": _diagnostic_fingerprint(config.get("database")),
            "databaseLength": len(str(config.get("database") or "")),
            "userFingerprint": _diagnostic_fingerprint(config.get("user")),
            "userLength": len(str(config.get("user") or "")),
            "passwordFingerprint": _diagnostic_fingerprint(config.get("password")),
            "passwordLength": len(str(config.get("password") or "")),
            "unixSocketConfigured": bool(config.get("unix_socket")),
            "unixSocketFingerprint": _diagnostic_fingerprint(config.get("unix_socket")),
            "unixSocketExists": Path(config.get("unix_socket")).exists() if config.get("unix_socket") else False,
        }
    except Exception as exc:
        report["configLoadError"] = {
            "errorType": exc.__class__.__name__,
            "errorFingerprint": _diagnostic_fingerprint(str(exc)),
            "valuesRedacted": True,
        }
    return report


def mysql_connection_stage_diagnostics():
    report = {
        "schemaVersion": "memoryendpoints.mysql_connection_stage_diagnostics.v1",
        "credentialConnect": {"ok": False, "valuesRedacted": True},
        "databaseSelect": {"ok": False, "valuesRedacted": True},
        "valuesRedacted": True,
    }
    try:
        config = _mysql_config_from_env()
        missing = [key for key in ("user", "password", "database") if not config.get(key)]
        if missing:
            raise RuntimeError("MySQL backend is selected but required database settings are missing.")
        try:
            import pymysql

            report["driver"] = "pymysql"
            connection = pymysql.connect(
                host=config["host"],
                port=int(config["port"]),
                user=config["user"],
                password=config["password"],
                unix_socket=config.get("unix_socket") or None,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            cursor_factory = lambda conn: conn.cursor()
        except ImportError:
            import mysql.connector

            report["driver"] = "mysql.connector"
            connection = mysql.connector.connect(
                host=config["host"],
                port=int(config["port"]),
                user=config["user"],
                password=config["password"],
                unix_socket=config.get("unix_socket") or None,
            )
            cursor_factory = lambda conn: conn.cursor()
        try:
            report["credentialConnect"]["ok"] = True
            database = "`%s`" % str(config["database"]).replace("`", "``")
            try:
                cursor = cursor_factory(connection)
                try:
                    cursor.execute("USE " + database)
                finally:
                    cursor.close()
                report["databaseSelect"]["ok"] = True
            except Exception as exc:
                report["databaseSelect"].update(_mysql_diagnostic_error(exc))
        finally:
            connection.close()
    except Exception as exc:
        report["credentialConnect"].update(_mysql_diagnostic_error(exc))
    return report


def _mysql_config_from_env():
    file_config = _mysql_config_from_secret_file()
    if file_config:
        return file_config
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
            "unix_socket": os.environ.get("MEMORYENDPOINTS_MYSQL_UNIX_SOCKET") or os.environ.get("MYSQL_UNIX_SOCKET") or "",
        }
    config = {
        "host": os.environ.get("MEMORYENDPOINTS_MYSQL_HOST") or os.environ.get("MYSQL_HOST") or "localhost",
        "port": int(os.environ.get("MEMORYENDPOINTS_MYSQL_PORT") or os.environ.get("MYSQL_PORT") or "3306"),
        "user": os.environ.get("MEMORYENDPOINTS_MYSQL_USER") or os.environ.get("MYSQL_USER") or "",
        "password": os.environ.get("MEMORYENDPOINTS_MYSQL_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or "",
        "database": os.environ.get("MEMORYENDPOINTS_MYSQL_DATABASE") or os.environ.get("MYSQL_DATABASE") or "",
        "unix_socket": os.environ.get("MEMORYENDPOINTS_MYSQL_UNIX_SOCKET") or os.environ.get("MYSQL_UNIX_SOCKET") or "",
    }
    return config


class MySQLStore(SQLiteStore):
    def _open_connection(self):
        return self._connect()

    def _schema_cache_key(self, config):
        return (
            config.get("host") or "",
            str(config.get("port") or ""),
            config.get("database") or "",
            config.get("user") or "",
            config.get("unix_socket") or "",
        )

    def _ensure_schema_once(self, connection, config):
        schema_key = self._schema_cache_key(config)
        with _LOCK:
            if schema_key not in _MYSQL_SCHEMA_READY:
                self._ensure_schema(connection)
                _MYSQL_SCHEMA_READY.add(schema_key)

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
                unix_socket=config.get("unix_socket") or None,
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
                unix_socket=config.get("unix_socket") or None,
            )
        cursor_options = {}
        if connection.__class__.__module__.startswith("mysql.connector"):
            cursor_options = {"dictionary": True}
        wrapped = _DbConnection(connection, "mysql", cursor_options)
        self._ensure_schema_once(wrapped, config)
        return wrapped

    def _ensure_schema(self, connection):
        schema = (Path(__file__).resolve().parents[1] / "docs" / "database-schema-canonical.sql").read_text(encoding="utf-8")
        connection.executescript(schema)
        connection.commit()
