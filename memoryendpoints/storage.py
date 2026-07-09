import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid

from .config import PUBLIC_STORAGE_BYTES, utc_now


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


def _blank_store():
    return {
        "schemaVersion": "memoryendpoints.file_store.v1",
        "createdAt": utc_now(),
        "workspaces": {},
        "apiKeys": {},
        "agents": {},
        "memoryEvents": [],
        "messages": [],
        "notifications": [],
        "receipts": [],
        "auditLog": [],
        "idempotency": {},
    }


class FileStore(object):
    def __init__(self, path=None):
        self.path = path or os.environ.get("MEMORYENDPOINTS_STORE_PATH")
        if not self.path:
            from .config import STORE_PATH

            self.path = STORE_PATH
        if not hasattr(self.path, "exists"):
            from pathlib import Path

            self.path = Path(self.path)

    def _load(self):
        with _LOCK:
            if not self.path.exists():
                return _blank_store()
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

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

    def audit(self, data, action, actor, target):
        data["auditLog"].append(
            {
                "auditId": _id("audit"),
                "action": action,
                "actor": actor,
                "target": target,
                "createdAt": utc_now(),
                "valuesRedacted": True,
            }
        )

    def workspace_usage_bytes(self, data, workspace_id):
        usage = _json_size(data.get("workspaces", {}).get(workspace_id))
        for key in ("agents",):
            for item in data.get(key, {}).values():
                if item.get("workspaceId") == workspace_id:
                    usage += _json_size(item)
        for key in ("memoryEvents", "messages", "notifications", "receipts"):
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
        return {
            "workspaceId": workspace_id,
            "label": workspace.get("label"),
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
                "idempotencyKeyExposed": False,
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

    def create_free_account(self, label):
        data = self._load()
        workspace_id = _id("workspace")
        token = "me_live_" + secrets.token_urlsafe(32)
        key_id = _id("key")
        data["workspaces"][workspace_id] = {
            "workspaceId": workspace_id,
            "label": label or "Free Agent Workspace",
            "plan": "free_agent",
            "storageLimitBytes": PUBLIC_STORAGE_BYTES,
            "createdAt": utc_now(),
            "status": "active",
        }
        data["apiKeys"][key_id] = {
            "keyId": key_id,
            "workspaceId": workspace_id,
            "tokenHash": _hash(token),
            "createdAt": utc_now(),
            "lastUsedAt": None,
            "revokedAt": None,
        }
        self.audit(data, "workspace.create_free_account", "system", workspace_id)
        self._save(data)
        return workspace_id, key_id, token

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
        self.audit(data, "agent.register", agent_id, workspace_id)
        self._save(data)
        return data["agents"][agent_key]

    def submit_memory(self, workspace_id, actor_agent_id, scope, title, summary, tags, source):
        data = self._load()
        event = {
            "eventId": _id("mem"),
            "workspaceId": workspace_id,
            "actorAgentId": actor_agent_id,
            "scope": scope or "workspace",
            "title": title,
            "summary": summary,
            "tags": tags or [],
            "source": source or "api",
            "createdAt": utc_now(),
            "status": "active",
            "rawPrivatePayloadStored": False,
            "valuesRedacted": True,
        }
        data["memoryEvents"].append(event)
        self.audit(data, "memory.submit", actor_agent_id, event["eventId"])
        self._save(data)
        return event

    def search_memory(self, workspace_id, query):
        data = self._load()
        q = (query or "").lower().strip()
        items = []
        for event in data["memoryEvents"]:
            if event.get("workspaceId") != workspace_id:
                continue
            haystack = " ".join(
                [
                    event.get("title", ""),
                    event.get("summary", ""),
                    " ".join(event.get("tags", [])),
                    event.get("scope", ""),
                ]
            ).lower()
            if not q or q in haystack:
                items.append(event)
        return items

    def submit_message(self, workspace_id, sender_agent_id, target_agent_id, safe_summary, response_required):
        data = self._load()
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
        self.audit(data, "message.submit", sender_agent_id, message["messageId"])
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
                self.audit(data, "notification.ack", consumer_agent_id, notification_id)
                self._save(data)
                return receipt
        return None


class SQLiteStore(FileStore):
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
        connection.execute("PRAGMA journal_mode=TRUNCATE")
        connection.execute("PRAGMA busy_timeout=20000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS matm_json_store (store_key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        return connection

    def _load(self):
        with _LOCK:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM matm_json_store WHERE store_key = ?",
                    ("main",),
                ).fetchone()
                if not row:
                    return _blank_store()
                return json.loads(row[0])

    def _save(self, data):
        with _LOCK:
            payload = json.dumps(data, indent=2, sort_keys=True)
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO matm_json_store (store_key, payload, updated_at) VALUES (?, ?, ?)",
                    ("main", payload, utc_now()),
                )
