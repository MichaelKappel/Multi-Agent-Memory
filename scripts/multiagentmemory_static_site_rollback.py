from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .multiagentmemory_release_identity import (
        SITE_NAME,
        canonical_json_bytes,
        validate_release_identity,
    )
except ImportError:
    from multiagentmemory_release_identity import (
        SITE_NAME,
        canonical_json_bytes,
        validate_release_identity,
    )


ROLLBACK_SCHEMA_VERSION = "multiagentmemory.static_site_rollback_identity.v1"
TARGET_BINDING_SCHEMA_VERSION = "multiagentmemory.static_site_target_binding.v1"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644
TARGET_BINDING_FIELDS = {
    "schemaVersion",
    "targetDomain",
    "protocol",
    "credentialSource",
    "profileSelectorFingerprint",
    "remoteDirFingerprint",
    "targetBindingSha256",
    "valuesRedacted",
}
FORWARD_RELEASE_FIELDS = {
    "websiteVersion",
    "activationDate",
    "sourceCommitSha",
    "releaseIdentitySha256",
    "packageManifestSha256",
    "packageSha256",
    "rollbackPolicySha256",
}
ROLLBACK_ARCHIVE_FIELDS = {
    "fileName",
    "manifestFileName",
    "format",
    "compression",
    "entryCount",
    "entryOrder",
    "entryTimestampUtc",
    "entryMode",
    "bytes",
    "sha256",
}
ROLLBACK_MANIFEST_FIELDS = {
    "schemaVersion",
    "site",
    "targetBinding",
    "forwardRelease",
    "managedPaths",
    "priorState",
    "priorStateAggregateSha256",
    "archive",
    "valuesRedacted",
}


class RollbackArtifactError(ValueError):
    """Fail-closed public-safe rollback artifact error."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(condition, code):
    if not condition:
        raise RollbackArtifactError(code)


def _require_exact_fields(value, expected, code):
    _require(isinstance(value, dict) and set(value) == expected, code)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _canonical_remote_path(value):
    value = str(value or "")
    _require(
        value
        and value == value.strip()
        and "\\" not in value
        and "\x00" not in value
        and all(
            ord(character) >= 0x20 and ord(character) != 0x7F for character in value
        ),
        "target_remote_dir_invalid",
    )
    if value == ".":
        return value
    parts = value.split("/")
    _require(
        not value.startswith("/")
        and not value.endswith("/")
        and all(part not in {"", ".", ".."} for part in parts),
        "target_remote_dir_invalid",
    )
    return value


def _normalized_managed_path(value):
    path = PurePosixPath(str(value).replace("\\", "/"))
    text = path.as_posix()
    _require(
        text not in {"", "."}
        and not path.is_absolute()
        and ".." not in path.parts
        and "\x00" not in text,
        "rollback_path_invalid",
    )
    return text


def build_target_binding(
    *,
    target_domain,
    protocol,
    credential_source,
    profile_selector,
    host,
    port,
    user,
    remote_dir,
):
    """Return a secret-free digest that binds artifacts to one FTPS target."""
    target_domain = str(target_domain or "").strip().lower().rstrip(".")
    protocol = str(protocol or "").strip().lower()
    credential_source = str(credential_source or "").strip()
    profile_selector = str(profile_selector or "").strip().lower()
    host = str(host or "").strip().lower().rstrip(".")
    user = str(user or "").strip()
    remote_dir = _canonical_remote_path(remote_dir)
    _require(target_domain == "multiagentmemory.com", "rollback_target_invalid")
    _require(protocol == "ftps", "rollback_transport_invalid")
    _require(
        credential_source
        and profile_selector
        and host
        and user
        and isinstance(port, int)
        and 0 < port <= 65535,
        "rollback_target_binding_incomplete",
    )
    private_identity = {
        "schemaVersion": TARGET_BINDING_SCHEMA_VERSION,
        "targetDomain": target_domain,
        "protocol": protocol,
        "credentialSource": credential_source,
        "profileSelector": profile_selector,
        "host": host,
        "port": port,
        "user": user,
        "remoteDir": remote_dir,
    }
    return {
        "schemaVersion": TARGET_BINDING_SCHEMA_VERSION,
        "targetDomain": target_domain,
        "protocol": protocol,
        "credentialSource": credential_source,
        "profileSelectorFingerprint": _sha256(profile_selector.encode("utf-8")),
        "remoteDirFingerprint": _sha256(remote_dir.encode("utf-8")),
        "targetBindingSha256": _sha256(canonical_json_bytes(private_identity)),
        "valuesRedacted": True,
    }


def validate_target_binding(binding):
    _require_exact_fields(
        binding, TARGET_BINDING_FIELDS, "rollback_target_binding_fields_changed"
    )
    _require(
        binding.get("schemaVersion") == TARGET_BINDING_SCHEMA_VERSION
        and binding.get("targetDomain") == "multiagentmemory.com"
        and binding.get("protocol") == "ftps"
        and isinstance(binding.get("credentialSource"), str)
        and bool(binding["credentialSource"])
        and all(
            isinstance(binding.get(field), str)
            and len(binding[field]) == 64
            and all(character in "0123456789abcdef" for character in binding[field])
            for field in (
                "profileSelectorFingerprint",
                "remoteDirFingerprint",
                "targetBindingSha256",
            )
        )
        and binding.get("valuesRedacted") is True,
        "rollback_target_binding_invalid",
    )
    return binding


def forward_release_binding(release_identity):
    validate_release_identity(release_identity)
    rollback_policy = release_identity["rollbackPolicy"]
    return {
        "websiteVersion": release_identity["websiteVersion"],
        "activationDate": release_identity["activationDate"],
        "sourceCommitSha": release_identity["source"]["commitSha"],
        "releaseIdentitySha256": _sha256(canonical_json_bytes(release_identity)),
        "packageManifestSha256": release_identity["packageManifestSha256"],
        "packageSha256": release_identity["packageManifest"]["archive"]["sha256"],
        "rollbackPolicySha256": _sha256(canonical_json_bytes(rollback_policy)),
    }


def _normalize_prior_state(prior_state, managed_paths):
    _require(isinstance(prior_state, dict), "rollback_prior_state_invalid")
    managed_paths = [_normalized_managed_path(path) for path in managed_paths]
    _require(
        managed_paths == sorted(set(managed_paths)),
        "rollback_managed_paths_invalid",
    )
    normalized_input = {
        _normalized_managed_path(path): value for path, value in prior_state.items()
    }
    _require(
        len(normalized_input) == len(prior_state)
        and set(normalized_input) == set(managed_paths),
        "rollback_prior_state_incomplete",
    )
    normalized = {}
    for path in managed_paths:
        value = normalized_input[path]
        _require(
            value is None or isinstance(value, bytes), "rollback_prior_bytes_invalid"
        )
        normalized[path] = value
    return normalized


def _prior_state_records(prior_state):
    records = []
    aggregate = hashlib.sha256()
    for path, data in sorted(prior_state.items()):
        if data is None:
            records.append({"path": path, "state": "absent"})
            aggregate.update(f"absent  -  0  {path}\n".encode("utf-8"))
        else:
            digest = _sha256(data)
            records.append(
                {
                    "path": path,
                    "state": "present",
                    "bytes": len(data),
                    "sha256": digest,
                }
            )
            aggregate.update(
                f"present  {digest}  {len(data)}  {path}\n".encode("utf-8")
            )
    return records, aggregate.hexdigest()


def build_rollback_zip(prior_state):
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for path, data in sorted(prior_state.items()):
            if data is None:
                continue
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = ZIP_FILE_MODE << 16
            archive.writestr(
                info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return output.getvalue()


def build_rollback_manifest(
    prior_state,
    release_identity,
    target_binding,
    archive_bytes,
    archive_name,
    manifest_name,
):
    validate_release_identity(release_identity)
    validate_target_binding(target_binding)
    managed_paths = release_identity["rollbackPolicy"]["managedPaths"]
    prior_state = _normalize_prior_state(prior_state, managed_paths)
    records, aggregate = _prior_state_records(prior_state)
    return {
        "schemaVersion": ROLLBACK_SCHEMA_VERSION,
        "site": SITE_NAME,
        "targetBinding": target_binding,
        "forwardRelease": forward_release_binding(release_identity),
        "managedPaths": list(managed_paths),
        "priorState": records,
        "priorStateAggregateSha256": aggregate,
        "archive": {
            "fileName": archive_name,
            "manifestFileName": manifest_name,
            "format": "zip",
            "compression": "deflate-9",
            "entryCount": sum(data is not None for data in prior_state.values()),
            "entryOrder": "forward-slash path ascending",
            "entryTimestampUtc": "1980-01-01T00:00:00Z",
            "entryMode": "0100644",
            "bytes": len(archive_bytes),
            "sha256": _sha256(archive_bytes),
        },
        "valuesRedacted": True,
    }


def _exclusive_write(path, data):
    path = Path(path)
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def write_rollback_pair(
    package_path,
    manifest_path,
    prior_state,
    release_identity,
    target_binding,
):
    package_path = Path(package_path)
    manifest_path = Path(manifest_path)
    _require(package_path != manifest_path, "rollback_artifact_paths_collide")
    _require(
        not package_path.exists() and not manifest_path.exists(),
        "rollback_artifact_already_exists",
    )
    _require(
        package_path.parent.is_dir() and manifest_path.parent.is_dir(),
        "rollback_artifact_parent_missing",
    )
    normalized = _normalize_prior_state(
        prior_state, release_identity["rollbackPolicy"]["managedPaths"]
    )
    archive_bytes = build_rollback_zip(normalized)
    manifest = build_rollback_manifest(
        normalized,
        release_identity,
        target_binding,
        archive_bytes,
        package_path.name,
        manifest_path.name,
    )
    manifest_bytes = canonical_json_bytes(manifest)
    wrote_package = False
    try:
        _exclusive_write(package_path, archive_bytes)
        wrote_package = True
        _exclusive_write(manifest_path, manifest_bytes)
    except Exception:
        if wrote_package:
            try:
                package_path.unlink()
            except OSError:
                pass
        raise
    return verify_rollback_pair(
        package_path,
        manifest_path,
        release_identity,
        target_binding,
    )


def _validate_manifest(manifest, release_identity, target_binding):
    _require_exact_fields(
        manifest, ROLLBACK_MANIFEST_FIELDS, "rollback_manifest_fields_changed"
    )
    _require(
        manifest.get("schemaVersion") == ROLLBACK_SCHEMA_VERSION
        and manifest.get("site") == SITE_NAME
        and manifest.get("valuesRedacted") is True,
        "rollback_manifest_invalid",
    )
    validate_target_binding(manifest.get("targetBinding"))
    _require(
        manifest["targetBinding"] == target_binding,
        "rollback_target_binding_mismatch",
    )
    forward = manifest.get("forwardRelease")
    _require_exact_fields(
        forward, FORWARD_RELEASE_FIELDS, "rollback_forward_release_fields_changed"
    )
    _require(
        forward == forward_release_binding(release_identity),
        "rollback_forward_release_mismatch",
    )
    managed_paths = release_identity["rollbackPolicy"]["managedPaths"]
    _require(
        manifest.get("managedPaths") == managed_paths,
        "rollback_managed_paths_mismatch",
    )
    records = manifest.get("priorState")
    _require(
        isinstance(records, list) and len(records) == len(managed_paths),
        "rollback_prior_state_invalid",
    )
    prior_state = {}
    for record, expected_path in zip(records, managed_paths, strict=True):
        _require(isinstance(record, dict), "rollback_prior_state_invalid")
        _require(
            record.get("path") == expected_path, "rollback_prior_state_order_invalid"
        )
        state = record.get("state")
        if state == "absent":
            _require(
                set(record) == {"path", "state"},
                "rollback_absent_record_invalid",
            )
            prior_state[expected_path] = None
        elif state == "present":
            _require(
                set(record) == {"path", "state", "bytes", "sha256"}
                and isinstance(record.get("bytes"), int)
                and record["bytes"] >= 0
                and isinstance(record.get("sha256"), str)
                and len(record["sha256"]) == 64,
                "rollback_present_record_invalid",
            )
            prior_state[expected_path] = record
        else:
            raise RollbackArtifactError("rollback_prior_state_invalid")
    aggregate = hashlib.sha256()
    for path in managed_paths:
        record = prior_state[path]
        if record is None:
            aggregate.update(f"absent  -  0  {path}\n".encode("utf-8"))
        else:
            aggregate.update(
                f"present  {record['sha256']}  {record['bytes']}  {path}\n".encode(
                    "utf-8"
                )
            )
    _require(
        manifest.get("priorStateAggregateSha256") == aggregate.hexdigest(),
        "rollback_prior_state_aggregate_mismatch",
    )
    archive = manifest.get("archive")
    _require_exact_fields(
        archive, ROLLBACK_ARCHIVE_FIELDS, "rollback_archive_fields_changed"
    )
    _require(
        archive.get("format") == "zip"
        and archive.get("compression") == "deflate-9"
        and archive.get("entryOrder") == "forward-slash path ascending"
        and archive.get("entryTimestampUtc") == "1980-01-01T00:00:00Z"
        and archive.get("entryMode") == "0100644",
        "rollback_archive_policy_invalid",
    )
    return prior_state


def verify_rollback_pair(
    package_path,
    manifest_path,
    release_identity,
    target_binding,
):
    package_path = Path(package_path)
    manifest_path = Path(manifest_path)
    validate_release_identity(release_identity)
    validate_target_binding(target_binding)
    archive_bytes = package_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollbackArtifactError("rollback_manifest_invalid") from exc
    _require(
        manifest_bytes == canonical_json_bytes(manifest),
        "rollback_manifest_not_canonical",
    )
    prior_records = _validate_manifest(manifest, release_identity, target_binding)
    archive = manifest["archive"]
    _require(
        archive.get("fileName") == package_path.name
        and archive.get("manifestFileName") == manifest_path.name
        and archive.get("bytes") == len(archive_bytes)
        and archive.get("sha256") == _sha256(archive_bytes),
        "rollback_archive_identity_mismatch",
    )
    expected_present = [
        path for path, record in prior_records.items() if record is not None
    ]
    extracted = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as bundle:
            _require(bundle.comment == b"", "rollback_archive_comment_invalid")
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            _require(
                names == sorted(expected_present)
                and len(names) == len(set(names))
                and archive.get("entryCount") == len(names),
                "rollback_archive_entries_invalid",
            )
            for info in infos:
                path = _normalized_managed_path(info.filename)
                _require(
                    path == info.filename
                    and not info.is_dir()
                    and not (info.flag_bits & 0x1)
                    and info.date_time == FIXED_ZIP_TIMESTAMP
                    and info.create_system == 3
                    and (info.external_attr >> 16) == ZIP_FILE_MODE
                    and info.compress_type == zipfile.ZIP_DEFLATED
                    and info.extra == b""
                    and info.comment == b"",
                    "rollback_archive_entry_policy_invalid",
                )
                data = bundle.read(info)
                record = prior_records[path]
                _require(
                    record is not None
                    and len(data) == record["bytes"]
                    and _sha256(data) == record["sha256"],
                    "rollback_archive_entry_mismatch",
                )
                extracted[path] = data
    except zipfile.BadZipFile as exc:
        raise RollbackArtifactError("rollback_archive_invalid") from exc
    prior_state = {
        path: extracted.get(path) if record is not None else None
        for path, record in prior_records.items()
    }
    _require(
        build_rollback_zip(prior_state) == archive_bytes,
        "rollback_archive_not_canonical",
    )
    return {
        "manifest": manifest,
        "manifestSha256": _sha256(manifest_bytes),
        "packageSha256": _sha256(archive_bytes),
        "priorState": prior_state,
        "summary": {
            "schemaVersion": ROLLBACK_SCHEMA_VERSION,
            "managedPathCount": len(prior_state),
            "priorPresentCount": sum(data is not None for data in prior_state.values()),
            "priorAbsentCount": sum(data is None for data in prior_state.values()),
            "priorStateAggregateSha256": manifest["priorStateAggregateSha256"],
            "rollbackPackageSha256": _sha256(archive_bytes),
            "rollbackManifestSha256": _sha256(manifest_bytes),
            "targetBindingSha256": target_binding["targetBindingSha256"],
            "targetBindingVerified": True,
            "valuesRedacted": True,
        },
    }
