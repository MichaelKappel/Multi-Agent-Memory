"""Deterministic, in-memory assembly of a human-authorized company export.

Storage is responsible for authorization and for supplying a normalized snapshot
belonging to exactly one company.  This module deliberately has no storage or
clock access: callers must provide the export timestamp, and all output is
assembled in memory.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile

from memoryendpoints.security import redact_text


EXPORT_SCHEMA_VERSION = "memoryendpoints.company_export.v1"
_JSON_MEDIA_TYPE = "application/json"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_DROP = object()

# These are authentication material stores, not portable company business data.
# Matching uses punctuation/case-insensitive keys.
_CREDENTIAL_COLLECTION_KEYS = {
    "apikeys",
    "agenttokens",
    "authenticationcredentials",
    "companymasterkeys",
    "credentialrecords",
    "credentials",
    "csrftokens",
    "loginsessions",
    "refreshtokens",
    "sessions",
}

_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "bearer",
    "credential",
    "csrf",
    "hash",
    "passwd",
    "password",
    "pepper",
    "privatekey",
    "secret",
    "session",
    "verifier",
)


class CompanyExportError(ValueError):
    """The supplied snapshot cannot be safely represented as an export."""


def _compact_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_credential_collection(key):
    compact = _compact_key(key)
    return compact in _CREDENTIAL_COLLECTION_KEYS or compact.endswith("credentialtable")


def _is_sensitive_field(key):
    compact = _compact_key(key)
    if not compact:
        return False
    if any(marker in compact for marker in _SENSITIVE_KEY_MARKERS):
        return True
    # Public identifiers/counts/budgets are harmless, while a field actually
    # containing a token is never portable export data.
    if "token" in compact and not compact.endswith(("tokenid", "tokencount", "tokenbudget")):
        return True
    return False


def _sanitize(value, stats, *, key=None):
    if key is not None and _is_credential_collection(key):
        stats["removedCollectionCount"] += 1
        return _DROP
    if key is not None and _is_sensitive_field(key):
        stats["removedFieldCount"] += 1
        return _DROP

    if isinstance(value, dict):
        output = {}
        if any(not isinstance(child_key, str) for child_key in value):
            raise CompanyExportError("Company export object keys must be strings.")
        for child_key in sorted(value):
            if child_key in {"__proto__", "prototype", "constructor"}:
                stats["removedFieldCount"] += 1
                continue
            child = _sanitize(value[child_key], stats, key=child_key)
            if child is not _DROP:
                output[child_key] = child
        return output
    if isinstance(value, list):
        output = []
        for item in value:
            child = _sanitize(item, stats)
            if child is not _DROP:
                output.append(child)
        return output
    if isinstance(value, str):
        redacted = redact_text(value)
        if redacted != value:
            stats["redactedStringCount"] += 1
        return redacted
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CompanyExportError("Company export numbers must be finite.")
        return value
    raise CompanyExportError("Company export snapshots must contain only normalized JSON values.")


def _canonical_json_bytes(value):
    try:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompanyExportError("Company export data is not valid normalized JSON.") from exc


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _derive_identity(snapshot, company_id, company_label):
    company = snapshot.get("company") if isinstance(snapshot.get("company"), dict) else {}
    companies = snapshot.get("companies")
    if not company and isinstance(companies, list) and len(companies) == 1 and isinstance(companies[0], dict):
        company = companies[0]

    resolved_id = company_id or snapshot.get("companyId") or company.get("companyId") or company.get("id")
    resolved_label = (
        company_label
        or snapshot.get("companyLabel")
        or company.get("companyLabel")
        or company.get("label")
        or company.get("name")
    )
    if not isinstance(resolved_id, str) or not resolved_id.strip():
        raise CompanyExportError("A non-empty company_id is required for a company export.")
    if not isinstance(resolved_label, str) or not resolved_label.strip():
        raise CompanyExportError("A non-empty company_label is required for a company export.")

    safe_id = redact_text(resolved_id.strip())
    safe_label = redact_text(resolved_label.strip())
    if safe_id != resolved_id.strip() or safe_label != resolved_label.strip():
        raise CompanyExportError("Company identity fields may not contain credential material.")
    return safe_id, safe_label


def _record_count(value):
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1
    if value is None:
        return 0
    return 1


def _zip_info(path):
    info = zipfile.ZipInfo(path, _FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def _safe_filename_component(value):
    component = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return (component[:80] or "company")


def assemble_company_export(
    snapshot,
    *,
    generated_at,
    company_id=None,
    company_label=None,
    schema_version=EXPORT_SCHEMA_VERSION,
):
    """Return a deterministic ZIP and response metadata for one company.

    ``snapshot`` must already be authorized and narrowed to a single company.
    Raw credential stores and sensitive authentication fields are omitted at
    every nesting level.  The returned ``body`` is never written to disk.
    """

    if not isinstance(snapshot, dict):
        raise CompanyExportError("Company export snapshot must be an object.")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise CompanyExportError("A caller-supplied generated_at timestamp is required.")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise CompanyExportError("A non-empty schema_version is required.")

    resolved_id, resolved_label = _derive_identity(snapshot, company_id, company_label)
    stats = {"removedCollectionCount": 0, "removedFieldCount": 0, "redactedStringCount": 0}
    sanitized = _sanitize(snapshot, stats)

    record_counts = {key: _record_count(value) for key, value in sorted(sanitized.items())}
    total_records = sum(record_counts.values())
    index = {
        "schemaVersion": schema_version,
        "companyId": resolved_id,
        "completeCompanyExport": True,
        "includesPortableMemory": True,
        "includesHumanForensicHistory": True,
        "collections": [
            {"name": key, "recordCount": record_counts[key]}
            for key in sorted(record_counts)
        ],
        "totalRecords": total_records,
    }

    company_raw = _canonical_json_bytes(sanitized)
    index_raw = _canonical_json_bytes(index)
    payload_files = {
        "company.json": company_raw,
        "index.json": index_raw,
    }
    file_entries = [
        {
            "path": path,
            "mediaType": _JSON_MEDIA_TYPE,
            "byteLength": len(payload_files[path]),
            "sha256": _sha256(payload_files[path]),
        }
        for path in sorted(payload_files)
    ]
    receipt_basis = {
        "schemaVersion": schema_version,
        "companyId": resolved_id,
        "companyLabel": resolved_label,
        "generatedAt": generated_at.strip(),
        "files": file_entries,
        "recordCounts": record_counts,
        "totalRecords": total_records,
    }
    receipt_digest = _sha256(_canonical_json_bytes(receipt_basis))
    manifest = dict(receipt_basis)
    manifest.update(
        {
            "archiveFormat": "zip+json",
            "completeCompanyExport": True,
            "includesPortableMemory": True,
            "includesHumanForensicHistory": True,
            "exportReceiptDigest": receipt_digest,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "credentialVerifiersExposed": False,
            "checksums": {
                path: "sha256:" + _sha256(raw)
                for path, raw in sorted(payload_files.items())
            },
            "redaction": {
                "accessMaterialIncluded": False,
                "mode": "remove-sensitive-fields-and-redact-sensitive-strings",
                **stats,
            },
        }
    )
    if isinstance(sanitized.get("auditActor"), dict):
        manifest["auditActor"] = sanitized["auditActor"]
    manifest_raw = _canonical_json_bytes(manifest)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, raw in sorted({**payload_files, "manifest.json": manifest_raw}.items()):
            archive.writestr(_zip_info(path), raw)
    body = buffer.getvalue()
    filename = "memoryendpoints-%s-company-export.zip" % _safe_filename_component(resolved_id)
    archive_digest = _sha256(body)

    return {
        "filename": filename,
        "contentType": "application/zip",
        "contentDisposition": 'attachment; filename="%s"' % filename,
        "body": body,
        "digest": archive_digest,
        "exportReceiptDigest": receipt_digest,
        "manifestSha256": _sha256(manifest_raw),
        "fileDigests": {
            **{entry["path"]: entry["sha256"] for entry in file_entries},
            "manifest.json": _sha256(manifest_raw),
        },
        "recordCounts": record_counts,
        "totalRecords": total_records,
        "schemaVersion": schema_version,
        "companyId": resolved_id,
        "companyLabel": resolved_label,
        "generatedAt": generated_at.strip(),
    }
