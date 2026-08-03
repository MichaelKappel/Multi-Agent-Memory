"""Closed release identity and Git provenance controller for MultiAgentMemory.com."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


PUBLIC_REPOSITORY_URL = "https://github.com/MichaelKappel/Multi-Agent-Memory"
PUBLIC_REPOSITORY_GIT_URL = PUBLIC_REPOSITORY_URL + ".git"
REMOTE_NAME = "origin"
SITE_NAME = "MultiAgentMemory.com"
SITE_REPOSITORY_PATH = PurePosixPath("sites/multiagentmemory.com")
PREACTIVATION_PHASE = "preactivation"
FINAL_PHASE = "final"
RELEASE_PHASES = {PREACTIVATION_PHASE, FINAL_PHASE}
FINAL_RELEASE_CLAIM_PATHS = ("releases/index.html", "releases.json")
RELEASE_CLAIM_PATHS = (
    "ai-manifest.json",
    "ai.txt",
    "llms.txt",
    "README.md",
    *FINAL_RELEASE_CLAIM_PATHS,
)
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
ANNOTATED_TAGGER = re.compile(
    rb"[^\x00\r\n<> \t](?:[^\x00\r\n<>]*[^\x00\r\n<> \t])? "
    rb"<[^\x00\r\n<> \t]+> (?:0|[1-9][0-9]*) "
    rb"[+-](?:0[0-9]|1[0-4])[0-5][0-9]"
)

SOURCE_FIELDS = {
    "repositoryUrl",
    "commitSha",
    "requiredTagName",
    "requiredTagRef",
    "requiredTagUrl",
    "requiredTagTargetCommitSha",
    "remoteName",
    "preactivationRemoteMainCommitSha",
}
SOURCE_QUALIFICATION_FIELDS = {
    "phase",
    "localTagPresent",
    "remoteTagPresent",
    "localTagObjectSha",
    "remoteTagObjectSha",
    "localTagTargetCommitSha",
    "remoteTagTargetCommitSha",
    "localTagDeclaredName",
    "annotatedTagNameVerified",
    "remoteMainObservedCommitSha",
    "remoteMainLeaseVerified",
    "commitSiteBytesVerified",
    "tagSiteBytesVerified",
    "valuesRedacted",
}
RELEASE_IDENTITY_FIELDS = {
    "schemaVersion",
    "site",
    "websiteVersion",
    "activationDate",
    "activationTimezone",
    "source",
    "releaseLedger",
    "siteManifest",
    "packageManifest",
    "packageManifestSha256",
    "cutoverPolicy",
    "valuesRedacted",
}
RELEASE_LEDGER_IDENTITY_FIELDS = {
    "sha256",
    "releaseCount",
    "currentProductionWebsiteVersion",
}
PACKAGE_MANIFEST_FIELDS = {"schemaVersion", "archive", "allowlist"}
CUTOVER_POLICY_FIELDS = {
    "schemaVersion",
    "packageQualificationPhase",
    "preactivationStagePhase",
    "preactivationUploadPaths",
    "preactivationReadbackPaths",
    "preactivationLiveVerificationPaths",
    "tagPublicationAfterPreactivationLiveVerificationRequired",
    "finalQualificationPhase",
    "finalStagedNonClaimReadbackPaths",
    "finalClaimActivationPhase",
    "finalClaimUploadOrder",
    "finalClaimReadbackOrder",
    "finalLiveVerificationPaths",
    "mainPublicationAfterFinalLiveVerificationRequired",
}


class ReleaseIdentityError(ValueError):
    """Fail-closed public-safe release identity error."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(condition, code):
    if not condition:
        raise ReleaseIdentityError(code)


def _require_exact_fields(value, expected, code):
    _require(isinstance(value, dict) and set(value) == expected, code)


def canonical_json_bytes(value):
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def tag_name_for_version(version):
    _require(
        isinstance(version, str) and SEMVER.fullmatch(version),
        "release_version_invalid",
    )
    return f"multiagentmemory-site-v{version}"


def tag_ref_for_version(version):
    return "refs/tags/" + tag_name_for_version(version)


def tag_url_for_version(version):
    return PUBLIC_REPOSITORY_URL + "/tree/" + tag_name_for_version(version)


def current_release_record(ledger):
    _require(isinstance(ledger, dict), "release_ledger_invalid")
    version = ledger.get("currentProductionWebsiteVersion")
    releases = ledger.get("releases")
    _require(
        isinstance(version, str) and SEMVER.fullmatch(version),
        "release_version_invalid",
    )
    _require(isinstance(releases, list), "release_ledger_invalid")
    matches = [
        item
        for item in releases
        if isinstance(item, dict) and item.get("version") == version
    ]
    _require(len(matches) == 1, "current_release_record_invalid")
    release = matches[0]
    _require(release.get("status") == "deployed", "current_release_not_deployed")
    _require(
        release.get("activationTimezone") == "UTC",
        "release_activation_timezone_invalid",
    )
    activation_date = release.get("activationDate")
    _require(
        isinstance(activation_date, str)
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", activation_date),
        "release_activation_date_invalid",
    )
    expected_evidence = {
        "type": "source_tag",
        "label": "Source tag " + tag_name_for_version(version),
        "url": tag_url_for_version(version),
    }
    _require(
        release.get("evidence") == [expected_evidence],
        "release_source_tag_evidence_invalid",
    )
    return release


def build_content_manifest(files):
    """Build the content-only identity shared by source, tag, ZIP, and live bytes."""
    normalized = []
    for relative, data in files:
        relative = PurePosixPath(str(relative).replace("\\", "/"))
        path = relative.as_posix()
        _require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and path not in {"", "."},
            "site_path_invalid",
        )
        _require(isinstance(data, bytes), "site_bytes_invalid")
        normalized.append((path, data))
    normalized.sort(key=lambda item: item[0])
    _require(
        len({path for path, _data in normalized}) == len(normalized),
        "site_path_duplicate",
    )
    aggregate = hashlib.sha256()
    entries = []
    total_bytes = 0
    for path, data in normalized:
        digest = hashlib.sha256(data).hexdigest()
        size = len(data)
        aggregate.update(f"{digest}  {size}  {path}\n".encode("utf-8"))
        entries.append({"path": path, "bytes": size, "sha256": digest})
        total_bytes += size
    return {
        "algorithm": "sha256 over UTF-8 no-BOM LF lines: <file-sha256><two spaces><bytes><two spaces><forward-slash-path><LF>",
        "fileCount": len(entries),
        "totalBytes": total_bytes,
        "aggregateSha256": aggregate.hexdigest(),
        "files": entries,
    }


def site_content_identity(site_manifest):
    _require(isinstance(site_manifest, dict), "site_manifest_invalid")
    expected = {"algorithm", "fileCount", "totalBytes", "aggregateSha256", "files"}
    _require(expected.issubset(site_manifest), "site_manifest_invalid")
    content = {
        key: site_manifest[key]
        for key in ("algorithm", "fileCount", "totalBytes", "aggregateSha256", "files")
    }
    _require(
        content["algorithm"]
        == "sha256 over UTF-8 no-BOM LF lines: <file-sha256><two spaces><bytes><two spaces><forward-slash-path><LF>",
        "site_manifest_invalid",
    )
    _require(
        isinstance(content["fileCount"], int) and content["fileCount"] >= 0,
        "site_manifest_invalid",
    )
    _require(
        isinstance(content["totalBytes"], int) and content["totalBytes"] >= 0,
        "site_manifest_invalid",
    )
    _require(
        isinstance(content["aggregateSha256"], str)
        and SHA256.fullmatch(content["aggregateSha256"]),
        "site_manifest_invalid",
    )
    _require(
        isinstance(content["files"], list)
        and len(content["files"]) == content["fileCount"],
        "site_manifest_invalid",
    )
    previous = None
    total = 0
    aggregate = hashlib.sha256()
    for item in content["files"]:
        _require(
            isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"},
            "site_manifest_invalid",
        )
        path = item["path"]
        _require(
            isinstance(path, str) and path and (previous is None or previous < path),
            "site_manifest_invalid",
        )
        _require(
            isinstance(item["bytes"], int) and item["bytes"] >= 0,
            "site_manifest_invalid",
        )
        _require(
            isinstance(item["sha256"], str) and SHA256.fullmatch(item["sha256"]),
            "site_manifest_invalid",
        )
        previous = path
        total += item["bytes"]
        aggregate.update(f"{item['sha256']}  {item['bytes']}  {path}\n".encode("utf-8"))
    _require(total == content["totalBytes"], "site_manifest_invalid")
    _require(
        aggregate.hexdigest() == content["aggregateSha256"], "site_manifest_invalid"
    )
    return content


def _git(repo_root, *arguments, code):
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise ReleaseIdentityError(code) from exc
    if completed.returncode != 0:
        raise ReleaseIdentityError(code)
    return completed.stdout


def _git_text(repo_root, *arguments, code):
    try:
        return (
            _git(repo_root, *arguments, code=code)
            .decode("utf-8", errors="strict")
            .strip()
        )
    except UnicodeError as exc:
        raise ReleaseIdentityError(code) from exc


def _annotated_tag_header(repo_root, object_sha):
    raw = _git(
        repo_root,
        "cat-file",
        "tag",
        object_sha,
        code="source_local_tag_object_invalid",
    )
    header, separator, _message = raw.partition(b"\n\n")
    _require(bool(separator), "source_local_tag_object_invalid")
    fields = {}
    for line in header.splitlines():
        key, space, value = line.partition(b" ")
        _require(
            bool(space)
            and key in {b"object", b"type", b"tag", b"tagger"}
            and key not in fields
            and bool(value),
            "source_local_tag_object_invalid",
        )
        fields[key] = value
    _require(
        set(fields) == {b"object", b"type", b"tag", b"tagger"},
        "source_local_tag_object_invalid",
    )
    try:
        target = fields[b"object"].decode("ascii", errors="strict")
        object_type = fields[b"type"].decode("ascii", errors="strict")
        declared_name = fields[b"tag"].decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ReleaseIdentityError("source_local_tag_object_invalid") from exc
    _require(
        GIT_OBJECT_ID.fullmatch(target)
        and object_type == "commit"
        and declared_name
        and ANNOTATED_TAGGER.fullmatch(fields[b"tagger"]),
        "source_local_tag_object_invalid",
    )
    return {
        "declaredTagName": declared_name,
        "declaredTargetCommitSha": target,
    }


def _resolve_local_tag(repo_root, tag_ref):
    listed = _git_text(
        repo_root,
        "for-each-ref",
        "--format=%(refname)%00%(objecttype)%00%(objectname)",
        tag_ref,
        code="source_local_tag_query_failed",
    )
    if not listed:
        return None
    pieces = listed.split("\x00")
    _require(
        len(pieces) == 3
        and pieces[0] == tag_ref
        and pieces[1] in {"tag", "commit"}
        and GIT_OBJECT_ID.fullmatch(pieces[2]),
        "source_local_tag_query_invalid",
    )
    tag_header = (
        _annotated_tag_header(repo_root, pieces[2]) if pieces[1] == "tag" else None
    )
    peeled = None
    if tag_header is not None:
        peeled = _git_text(
            repo_root,
            "rev-parse",
            "--verify",
            tag_header["declaredTargetCommitSha"] + "^{commit}",
            code="source_local_tag_object_invalid",
        )
        _require(
            GIT_OBJECT_ID.fullmatch(peeled)
            and peeled == tag_header["declaredTargetCommitSha"],
            "source_local_tag_object_invalid",
        )
    return {
        "objectType": pieces[1],
        "tagObjectSha": pieces[2],
        "peeledTargetCommitSha": peeled,
        "declaredTagName": (
            tag_header["declaredTagName"] if tag_header is not None else None
        ),
    }


def _resolve_remote_tag(repo_root, remote_name, tag_ref):
    output = _git_text(
        repo_root,
        "ls-remote",
        "--tags",
        remote_name,
        tag_ref,
        tag_ref + "^{}",
        code="source_remote_tag_query_failed",
    )
    if not output:
        return None
    records = {}
    for line in output.splitlines():
        pieces = line.split("\t")
        _require(
            len(pieces) == 2 and GIT_OBJECT_ID.fullmatch(pieces[0]),
            "source_remote_tag_invalid",
        )
        _require(pieces[1] in {tag_ref, tag_ref + "^{}"}, "source_remote_tag_invalid")
        _require(pieces[1] not in records, "source_remote_tag_invalid")
        records[pieces[1]] = pieces[0]
    _require(tag_ref in records, "source_remote_tag_invalid")
    return {
        "tagObjectSha": records[tag_ref],
        "peeledTargetCommitSha": records.get(tag_ref + "^{}"),
    }


def _resolve_remote_main(repo_root, remote_name):
    ref = "refs/heads/main"
    output = _git_text(
        repo_root,
        "ls-remote",
        "--heads",
        remote_name,
        ref,
        code="source_remote_main_query_failed",
    )
    pieces = output.split("\t") if output else []
    _require(
        len(pieces) == 2 and GIT_OBJECT_ID.fullmatch(pieces[0]) and pieces[1] == ref,
        "source_remote_main_query_invalid",
    )
    return pieces[0]


def _tagged_site_content(repo_root, commit_sha, allowed_paths):
    prefix = SITE_REPOSITORY_PATH.as_posix()
    listed = _git_text(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        commit_sha,
        "--",
        prefix,
        code="source_tag_site_unavailable",
    )
    expected = tuple(sorted(prefix + "/" + path for path in allowed_paths))
    actual = tuple(sorted(line for line in listed.splitlines() if line))
    _require(actual == expected, "source_tag_site_allowlist_drift")
    files = []
    for relative in sorted(allowed_paths):
        repository_path = prefix + "/" + relative
        data = _git(
            repo_root,
            "show",
            f"{commit_sha}:{repository_path}",
            code="source_tag_site_unavailable",
        )
        files.append((relative, data))
    return build_content_manifest(files)


def qualify_release_source(
    repo_root,
    site_root,
    ledger,
    allowed_paths,
    current_site_manifest,
    *,
    phase,
    expected_commit_sha=None,
    expected_repository_git_url=PUBLIC_REPOSITORY_GIT_URL,
    remote_name=REMOTE_NAME,
    expected_remote_main_commit_sha=None,
):
    """Prove one explicit preactivation or final source-identity phase."""
    _require(phase in RELEASE_PHASES, "release_qualification_phase_invalid")
    release = current_release_record(ledger)
    version = release["version"]
    tag_name = tag_name_for_version(version)
    tag_ref = tag_ref_for_version(version)
    repo_root = Path(repo_root).resolve(strict=True)
    site_root = Path(site_root).resolve(strict=True)
    top_level = Path(
        _git_text(
            repo_root, "rev-parse", "--show-toplevel", code="source_repository_invalid"
        )
    ).resolve(strict=True)
    _require(
        os.path.normcase(str(top_level)) == os.path.normcase(str(repo_root)),
        "source_repository_invalid",
    )
    expected_site_root = (repo_root / Path(SITE_REPOSITORY_PATH)).resolve(strict=True)
    _require(
        os.path.normcase(str(site_root)) == os.path.normcase(str(expected_site_root)),
        "source_site_root_invalid",
    )
    _require(
        not _git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            code="source_status_unavailable",
        ),
        "source_worktree_dirty",
    )
    commit_sha = _git_text(
        repo_root, "rev-parse", "HEAD^{commit}", code="source_commit_unavailable"
    )
    _require(bool(GIT_OBJECT_ID.fullmatch(commit_sha)), "source_commit_invalid")
    if expected_commit_sha is not None:
        _require(commit_sha == expected_commit_sha, "source_commit_mismatch")
    remote_url = _git_text(
        repo_root, "remote", "get-url", remote_name, code="source_remote_unavailable"
    )
    _require(remote_url == expected_repository_git_url, "source_remote_url_mismatch")
    observed_remote_main = None
    if phase == PREACTIVATION_PHASE or expected_remote_main_commit_sha is None:
        observed_remote_main = _resolve_remote_main(repo_root, remote_name)
    remote_main_lease = expected_remote_main_commit_sha or observed_remote_main
    _require(
        isinstance(remote_main_lease, str)
        and GIT_OBJECT_ID.fullmatch(remote_main_lease),
        "source_remote_main_lease_invalid",
    )
    if phase == PREACTIVATION_PHASE:
        _require(
            observed_remote_main == remote_main_lease,
            "source_remote_main_lease_changed",
        )
    local_tag = _resolve_local_tag(repo_root, tag_ref)
    remote_tag = _resolve_remote_tag(repo_root, remote_name, tag_ref)
    if phase == PREACTIVATION_PHASE:
        _require(
            local_tag is None,
            "source_local_tag_exists_during_preactivation",
        )
        _require(
            remote_tag is None,
            "source_remote_tag_exists_during_preactivation",
        )
    else:
        _require(local_tag is not None, "source_local_tag_missing_at_final")
        _require(
            local_tag["objectType"] == "tag"
            and local_tag["peeledTargetCommitSha"] is not None,
            "source_local_tag_not_annotated",
        )
        _require(
            local_tag["peeledTargetCommitSha"] == commit_sha,
            "source_tag_target_mismatch",
        )
        _require(
            local_tag["declaredTagName"] == tag_name,
            "source_tag_internal_name_mismatch",
        )
        _require(remote_tag is not None, "source_remote_tag_missing_at_final")
        _require(
            remote_tag["peeledTargetCommitSha"] is not None,
            "source_remote_tag_not_annotated",
        )
        _require(
            remote_tag["peeledTargetCommitSha"] == commit_sha,
            "source_remote_tag_target_mismatch",
        )
        _require(
            local_tag["tagObjectSha"] == remote_tag["tagObjectSha"],
            "source_tag_object_mismatch",
        )
    commit_content = _tagged_site_content(repo_root, commit_sha, tuple(allowed_paths))
    _require(
        commit_content == site_content_identity(current_site_manifest),
        "source_commit_site_drift",
    )
    source_identity = {
        "repositoryUrl": PUBLIC_REPOSITORY_URL,
        "commitSha": commit_sha,
        "requiredTagName": tag_name,
        "requiredTagRef": tag_ref,
        "requiredTagUrl": tag_url_for_version(version),
        "requiredTagTargetCommitSha": commit_sha,
        "remoteName": remote_name,
        "preactivationRemoteMainCommitSha": remote_main_lease,
    }
    qualification = {
        "phase": phase,
        "localTagPresent": local_tag is not None,
        "remoteTagPresent": remote_tag is not None,
        "localTagObjectSha": local_tag["tagObjectSha"] if local_tag else None,
        "remoteTagObjectSha": remote_tag["tagObjectSha"] if remote_tag else None,
        "localTagTargetCommitSha": (
            local_tag["peeledTargetCommitSha"] if local_tag else None
        ),
        "remoteTagTargetCommitSha": (
            remote_tag["peeledTargetCommitSha"] if remote_tag else None
        ),
        "localTagDeclaredName": (local_tag["declaredTagName"] if local_tag else None),
        "annotatedTagNameVerified": phase == FINAL_PHASE,
        "remoteMainObservedCommitSha": (
            observed_remote_main if phase == PREACTIVATION_PHASE else None
        ),
        "remoteMainLeaseVerified": phase == PREACTIVATION_PHASE,
        "commitSiteBytesVerified": True,
        "tagSiteBytesVerified": phase == FINAL_PHASE,
        "valuesRedacted": True,
    }
    validate_source_identity(source_identity, version)
    validate_source_qualification(qualification, source_identity)
    return {"sourceIdentity": source_identity, "qualification": qualification}


def validate_source_identity(source, version):
    _require_exact_fields(source, SOURCE_FIELDS, "source_identity_fields_changed")
    commit = source.get("commitSha")
    _require(
        isinstance(commit, str) and GIT_OBJECT_ID.fullmatch(commit),
        "source_commit_invalid",
    )
    _require(
        source.get("repositoryUrl") == PUBLIC_REPOSITORY_URL,
        "source_repository_url_invalid",
    )
    _require(
        source.get("requiredTagName") == tag_name_for_version(version),
        "source_tag_name_invalid",
    )
    _require(
        source.get("requiredTagRef") == tag_ref_for_version(version),
        "source_tag_ref_invalid",
    )
    _require(
        source.get("requiredTagUrl") == tag_url_for_version(version),
        "source_tag_url_invalid",
    )
    _require(
        source.get("requiredTagTargetCommitSha") == commit,
        "source_tag_target_mismatch",
    )
    _require(source.get("remoteName") == REMOTE_NAME, "source_remote_name_invalid")
    _require(
        isinstance(source.get("preactivationRemoteMainCommitSha"), str)
        and GIT_OBJECT_ID.fullmatch(source["preactivationRemoteMainCommitSha"]),
        "source_remote_main_lease_invalid",
    )


def validate_source_qualification(qualification, source):
    _require_exact_fields(
        qualification,
        SOURCE_QUALIFICATION_FIELDS,
        "source_qualification_fields_changed",
    )
    phase = qualification.get("phase")
    _require(phase in RELEASE_PHASES, "release_qualification_phase_invalid")
    _require(
        qualification.get("valuesRedacted") is True,
        "source_qualification_not_redacted",
    )
    _require(
        qualification.get("commitSiteBytesVerified") is True,
        "source_commit_site_not_verified",
    )
    commit = source["commitSha"]
    if phase == PREACTIVATION_PHASE:
        _require(
            qualification.get("localTagPresent") is False
            and qualification.get("remoteTagPresent") is False
            and qualification.get("localTagObjectSha") is None
            and qualification.get("remoteTagObjectSha") is None
            and qualification.get("localTagTargetCommitSha") is None
            and qualification.get("remoteTagTargetCommitSha") is None
            and qualification.get("localTagDeclaredName") is None
            and qualification.get("annotatedTagNameVerified") is False
            and qualification.get("remoteMainObservedCommitSha")
            == source["preactivationRemoteMainCommitSha"]
            and qualification.get("remoteMainLeaseVerified") is True
            and qualification.get("tagSiteBytesVerified") is False,
            "preactivation_tag_state_invalid",
        )
    else:
        _require(
            qualification.get("localTagPresent") is True
            and qualification.get("remoteTagPresent") is True
            and isinstance(qualification.get("localTagObjectSha"), str)
            and GIT_OBJECT_ID.fullmatch(qualification["localTagObjectSha"])
            and qualification.get("remoteTagObjectSha")
            == qualification.get("localTagObjectSha")
            and qualification.get("localTagTargetCommitSha") == commit
            and qualification.get("remoteTagTargetCommitSha") == commit
            and qualification.get("localTagDeclaredName") == source["requiredTagName"]
            and qualification.get("annotatedTagNameVerified") is True
            and qualification.get("remoteMainObservedCommitSha") is None
            and qualification.get("remoteMainLeaseVerified") is False
            and qualification.get("tagSiteBytesVerified") is True,
            "final_tag_state_invalid",
        )


def build_release_identity(
    source, ledger, ledger_sha256, site_manifest, package_manifest
):
    release = current_release_record(ledger)
    version = release["version"]
    validate_source_identity(source, version)
    _require(
        isinstance(ledger_sha256, str) and SHA256.fullmatch(ledger_sha256),
        "release_ledger_hash_invalid",
    )
    package_manifest_sha256 = hashlib.sha256(
        canonical_json_bytes(package_manifest)
    ).hexdigest()
    site_paths = [item["path"] for item in site_manifest["files"]]
    _require(
        all(path in site_paths for path in RELEASE_CLAIM_PATHS),
        "release_claim_path_missing",
    )
    non_claim_paths = sorted(
        path for path in site_paths if path not in RELEASE_CLAIM_PATHS
    )
    final_live_paths = sorted(site_paths)
    identity = {
        "schemaVersion": "multiagentmemory.static_site_release_identity.v3",
        "site": SITE_NAME,
        "websiteVersion": version,
        "activationDate": release["activationDate"],
        "activationTimezone": release["activationTimezone"],
        "source": source,
        "releaseLedger": {
            "sha256": ledger_sha256,
            "releaseCount": ledger["releaseCount"],
            "currentProductionWebsiteVersion": ledger[
                "currentProductionWebsiteVersion"
            ],
        },
        "siteManifest": site_manifest,
        "packageManifest": package_manifest,
        "packageManifestSha256": package_manifest_sha256,
        "cutoverPolicy": {
            "schemaVersion": "multiagentmemory.truth_ordered_cutover.v2",
            "packageQualificationPhase": PREACTIVATION_PHASE,
            "preactivationStagePhase": PREACTIVATION_PHASE,
            "preactivationUploadPaths": non_claim_paths,
            "preactivationReadbackPaths": non_claim_paths,
            "preactivationLiveVerificationPaths": non_claim_paths,
            "tagPublicationAfterPreactivationLiveVerificationRequired": True,
            "finalQualificationPhase": FINAL_PHASE,
            "finalStagedNonClaimReadbackPaths": non_claim_paths,
            "finalClaimActivationPhase": FINAL_PHASE,
            "finalClaimUploadOrder": list(RELEASE_CLAIM_PATHS),
            "finalClaimReadbackOrder": list(RELEASE_CLAIM_PATHS),
            "finalLiveVerificationPaths": final_live_paths,
            "mainPublicationAfterFinalLiveVerificationRequired": True,
        },
        "valuesRedacted": True,
    }
    validate_release_identity(identity)
    return identity


def validate_release_identity(identity, zip_bytes=None):
    _require_exact_fields(
        identity, RELEASE_IDENTITY_FIELDS, "release_identity_fields_changed"
    )
    _require(
        identity.get("schemaVersion")
        == "multiagentmemory.static_site_release_identity.v3",
        "release_identity_schema_invalid",
    )
    _require(identity.get("site") == SITE_NAME, "release_identity_site_invalid")
    version = identity.get("websiteVersion")
    _require(
        isinstance(version, str) and SEMVER.fullmatch(version),
        "release_version_invalid",
    )
    _require(
        identity.get("activationTimezone") == "UTC",
        "release_activation_timezone_invalid",
    )
    _require(
        isinstance(identity.get("activationDate"), str)
        and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", identity["activationDate"]),
        "release_activation_date_invalid",
    )
    _require(identity.get("valuesRedacted") is True, "release_identity_not_redacted")
    validate_source_identity(identity.get("source"), version)
    ledger = identity.get("releaseLedger")
    _require_exact_fields(
        ledger, RELEASE_LEDGER_IDENTITY_FIELDS, "release_ledger_identity_fields_changed"
    )
    _require(
        isinstance(ledger.get("sha256"), str) and SHA256.fullmatch(ledger["sha256"]),
        "release_ledger_hash_invalid",
    )
    _require(
        ledger.get("currentProductionWebsiteVersion") == version,
        "release_ledger_version_mismatch",
    )
    _require(
        isinstance(ledger.get("releaseCount"), int) and ledger["releaseCount"] > 0,
        "release_count_invalid",
    )
    site_content_identity(identity.get("siteManifest"))
    package_manifest = identity.get("packageManifest")
    _require_exact_fields(
        package_manifest, PACKAGE_MANIFEST_FIELDS, "package_manifest_fields_changed"
    )
    _require(
        package_manifest.get("schemaVersion")
        == "multiagentmemory.static_site_package_manifest.v2",
        "package_manifest_schema_invalid",
    )
    expected_package_manifest_hash = hashlib.sha256(
        canonical_json_bytes(package_manifest)
    ).hexdigest()
    _require(
        identity.get("packageManifestSha256") == expected_package_manifest_hash,
        "package_manifest_hash_mismatch",
    )
    cutover = identity.get("cutoverPolicy")
    _require_exact_fields(
        cutover, CUTOVER_POLICY_FIELDS, "cutover_policy_fields_changed"
    )
    site_paths = sorted(item["path"] for item in identity["siteManifest"]["files"])
    non_claim_paths = sorted(
        path for path in site_paths if path not in RELEASE_CLAIM_PATHS
    )
    _require(
        all(path in site_paths for path in RELEASE_CLAIM_PATHS)
        and cutover.get("schemaVersion") == "multiagentmemory.truth_ordered_cutover.v2"
        and cutover.get("packageQualificationPhase") == PREACTIVATION_PHASE
        and cutover.get("preactivationStagePhase") == PREACTIVATION_PHASE
        and cutover.get("preactivationUploadPaths") == non_claim_paths
        and cutover.get("preactivationReadbackPaths") == non_claim_paths
        and cutover.get("preactivationLiveVerificationPaths") == non_claim_paths
        and cutover.get("tagPublicationAfterPreactivationLiveVerificationRequired")
        is True
        and cutover.get("finalQualificationPhase") == FINAL_PHASE
        and cutover.get("finalStagedNonClaimReadbackPaths") == non_claim_paths
        and cutover.get("finalClaimActivationPhase") == FINAL_PHASE
        and cutover.get("finalClaimUploadOrder") == list(RELEASE_CLAIM_PATHS)
        and cutover.get("finalClaimReadbackOrder") == list(RELEASE_CLAIM_PATHS)
        and cutover.get("finalLiveVerificationPaths") == site_paths
        and cutover.get("mainPublicationAfterFinalLiveVerificationRequired") is True,
        "cutover_policy_invalid",
    )
    archive = package_manifest.get("archive")
    _require(isinstance(archive, dict), "archive_manifest_invalid")
    if zip_bytes is not None:
        _require(archive.get("bytes") == len(zip_bytes), "package_bytes_mismatch")
        _require(
            archive.get("sha256") == hashlib.sha256(zip_bytes).hexdigest(),
            "package_hash_mismatch",
        )
    return identity


def identity_summary(identity, identity_bytes=None):
    validate_release_identity(identity)
    source = identity["source"]
    archive = identity["packageManifest"]["archive"]
    summary = {
        "schemaVersion": identity["schemaVersion"],
        "websiteVersion": identity["websiteVersion"],
        "activationDate": identity["activationDate"],
        "sourceCommitSha": source["commitSha"],
        "requiredSourceTagRef": source["requiredTagRef"],
        "requiredTagTargetCommitSha": source["requiredTagTargetCommitSha"],
        "releaseLedgerSha256": identity["releaseLedger"]["sha256"],
        "staticSiteAggregateSha256": identity["siteManifest"]["aggregateSha256"],
        "packageManifestSha256": identity["packageManifestSha256"],
        "zipSha256": archive["sha256"],
        "valuesRedacted": True,
    }
    if identity_bytes is not None:
        summary["releaseIdentitySha256"] = hashlib.sha256(identity_bytes).hexdigest()
    return summary
