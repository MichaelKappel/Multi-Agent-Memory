import argparse
import base64
import ftplib
import hashlib
import io
import json
import re
import ssl
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from .multiagentmemory_release_identity import (
        FINAL_PHASE,
        PREACTIVATION_PHASE,
        RELEASE_PHASES,
        RELEASE_CLAIM_PATHS,
        ReleaseIdentityError,
    )
    from .package_multiagentmemory_static_site import (
        SitePackageError,
        capture_site_snapshot,
        site_snapshot_matches,
        snapshot_projection_drift,
        verify_package,
    )
except ImportError:
    from multiagentmemory_release_identity import (
        FINAL_PHASE,
        PREACTIVATION_PHASE,
        RELEASE_PHASES,
        RELEASE_CLAIM_PATHS,
        ReleaseIdentityError,
    )
    from package_multiagentmemory_static_site import (
        SitePackageError,
        capture_site_snapshot,
        site_snapshot_matches,
        snapshot_projection_drift,
        verify_package,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
DEFAULT_FILEZILLA_SITEMANAGER = (
    Path.home() / "AppData" / "Roaming" / "FileZilla" / "sitemanager.xml"
)
TARGET_DOMAIN = "multiagentmemory.com"
EXCLUDE_NAMES = {".gitkeep"}
EXCLUDE_SUFFIXES = {".bak", ".tmp", ".log"}


def release_activation_gate(release_identity, utc_date=None):
    """Bind a qualified release identity to its exact UTC activation date."""
    if utc_date is None:
        utc_date = datetime.now(timezone.utc).date().isoformat()
    result = {
        "requiredForUpload": True,
        "checked": False,
        "ok": False,
        "deploymentUtcDate": utc_date,
        "valuesRedacted": True,
    }
    if not isinstance(release_identity, dict):
        return result
    version = release_identity.get("websiteVersion")
    activation_date = release_identity.get("activationDate")
    if not isinstance(version, str) or not isinstance(activation_date, str):
        return result
    result.update(
        {
            "checked": True,
            "ok": activation_date == utc_date,
            "releaseVersion": version,
            "releaseActivationDate": activation_date,
        }
    )
    return result


def emit_report(report, args):
    if getattr(args, "json_out", None):
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_sections(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    sections = []
    current = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            sections.append(current)
            current = []
    if current:
        sections.append(current)
    return text, sections


def fields_from_lines(lines):
    fields = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
        elif "=" in line:
            key, value = line.split("=", 1)
        else:
            continue
        fields[key.strip().lower()] = value.strip()
    return fields


TARGET_IDENTITY_FIELD_KEYS = {
    "site",
    "site name",
    "target",
    "target site",
    "target domain",
    "domain",
}


def section_mentions_target(lines, target_domain):
    """Bind identity only from a section label or explicit target metadata."""
    target_domain = target_domain.strip().lower().rstrip(".")
    target_label = target_domain.split(".", 1)[0]
    aliases = (target_domain, target_label)
    headings = [line.strip() for line in lines if ":" not in line and "=" not in line]
    for heading in headings:
        for alias in aliases:
            if re.search(
                r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", heading, re.I
            ):
                return True
    fields = fields_from_lines(lines)
    target_identities = {
        canonical_site_identity(target_domain),
        canonical_site_identity(target_label),
    }
    return any(
        key in TARGET_IDENTITY_FIELD_KEYS
        and canonical_site_identity(value) in target_identities
        for key, value in fields.items()
    )


def decode_filezilla_password(node):
    if node is None or node.text is None:
        return ""
    value = node.text.strip()
    if (node.get("encoding") or "").lower() == "base64":
        return base64.b64decode(value).decode("utf-8")
    return value


def canonical_site_identity(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def load_filezilla_site(path, site_match, target_domain=None):
    site_match = (site_match or "").strip().lower()
    target_domain = (target_domain or site_match).strip().lower().rstrip(".")
    target_label = target_domain.split(".", 1)[0]
    target_aliases = {
        canonical_site_identity(target_domain),
        canonical_site_identity(target_label),
    }
    selector_identity = canonical_site_identity(site_match)
    if not selector_identity or selector_identity not in target_aliases:
        return None, {
            "status": "filezilla_selector_not_target_bound",
            "targetIdentityConfirmed": False,
            "valuesRedacted": True,
        }
    if not Path(path).exists():
        return None, {
            "status": "filezilla_site_manager_missing",
            "targetIdentityConfirmed": False,
            "valuesRedacted": True,
        }
    root = ET.parse(path).getroot()
    candidates = []
    for index, server in enumerate(root.findall(".//Server"), 1):

        def text(name):
            node = server.find(name)
            return (
                (node.text or "").strip()
                if node is not None and node.text is not None
                else ""
            )

        name = text("Name")
        host = text("Host")
        user = text("User")
        remote_dir = text("RemoteDir")
        host_identity = host.lower().rstrip(".")
        name_target_bound = canonical_site_identity(name) in target_aliases
        host_target_bound = host_identity == target_domain or host_identity.endswith(
            "." + target_domain
        )
        if not (name_target_bound or host_target_bound):
            continue
        candidates.append(
            {
                "index": index,
                "server": server,
                "name": name,
                "host": host,
                "user": user,
                "port": text("Port"),
                "remoteDir": remote_dir,
                "targetBinding": "profile_name" if name_target_bound else "host_domain",
            }
        )
    if len(candidates) > 1:
        return None, {
            "status": "filezilla_site_ambiguous",
            "candidateCount": len(candidates),
            "siteMatch": site_match,
            "targetIdentityConfirmed": False,
            "valuesRedacted": True,
        }
    if candidates:
        candidate = candidates[0]
        fields = {
            "ftp server": candidate["host"],
            "ftp username": candidate["user"],
            "password": decode_filezilla_password(candidate["server"].find("Pass")),
        }
        if candidate["port"]:
            fields["ftp & explicit ftps port"] = candidate["port"]
        if candidate["remoteDir"]:
            fields["remote_dir"] = candidate["remoteDir"]
        return fields, {
            "status": "filezilla_site_matched",
            "siteIndex": candidate["index"],
            "siteNameFingerprint": fingerprint(candidate["name"]),
            "siteMatch": site_match,
            "targetBinding": candidate["targetBinding"],
            "targetIdentityConfirmed": True,
            "hasRemoteDir": bool(candidate["remoteDir"]),
            "valuesRedacted": True,
        }
    return None, {
        "status": "filezilla_site_not_found",
        "siteMatch": site_match,
        "targetIdentityConfirmed": False,
        "valuesRedacted": True,
    }


def parse_handoff(path, target_domain):
    text, sections = parse_sections(path)
    parsed_sections = []
    for index, lines in enumerate(sections, 1):
        section_text = "\n".join(lines)
        score = 0
        target_confirmed = section_mentions_target(lines, target_domain)
        if target_confirmed:
            score += 100
        if re.search(r"ftp|ftps|sftp", section_text, re.I):
            score += 10
        if re.search(r"pass|password", section_text, re.I):
            score += 5
        if re.search(r"user|username", section_text, re.I):
            score += 3
        if re.search(r"host|server", section_text, re.I):
            score += 3
        parsed_sections.append(
            {
                "index": index,
                "fields": fields_from_lines(lines),
                "score": score,
                "targetConfirmed": target_confirmed,
            }
        )
    best = (
        max(parsed_sections, key=lambda item: item["score"])
        if parsed_sections
        else {"fields": {}, "score": 0, "text": ""}
    )
    return {
        "raw": best["fields"],
        "signals": {
            "hasFtp": bool(re.search(r"ftp|ftps|sftp", text, re.I)),
            "hasHost": bool(re.search(r"host|server", text, re.I)),
            "hasUser": bool(re.search(r"user|username", text, re.I)),
            "hasPassword": bool(re.search(r"pass|password", text, re.I)),
            "mentionsTarget": any(item["targetConfirmed"] for item in parsed_sections),
            "selectedSectionMentionsTarget": bool(best.get("targetConfirmed")),
            "selectedSectionIndex": best.get("index"),
            "sectionIndexValid": best.get("index") is not None,
            "selectedSectionScore": best.get("score", 0),
            "sectionCount": len(parsed_sections),
            "valuesRedacted": True,
        },
    }


def parse_handoff_section(path, target_domain, section_index):
    text, sections = parse_sections(path)
    if section_index < 1 or section_index > len(sections):
        return {
            "raw": {},
            "signals": {
                "sectionCount": len(sections),
                "selectedSectionIndex": section_index,
                "sectionIndexValid": False,
                "selectedSectionMentionsTarget": False,
                "valuesRedacted": True,
            },
        }
    selected = sections[section_index - 1]
    section_text = "\n".join(selected)
    score = 0
    target_confirmed = section_mentions_target(selected, target_domain)
    if target_confirmed:
        score += 100
    if re.search(r"ftp|ftps|sftp", section_text, re.I):
        score += 10
    if re.search(r"pass|password", section_text, re.I):
        score += 5
    if re.search(r"user|username", section_text, re.I):
        score += 3
    if re.search(r"host|server", section_text, re.I):
        score += 3
    return {
        "raw": fields_from_lines(selected),
        "signals": {
            "hasFtp": bool(re.search(r"ftp|ftps|sftp", text, re.I)),
            "hasHost": bool(re.search(r"host|server", text, re.I)),
            "hasUser": bool(re.search(r"user|username", text, re.I)),
            "hasPassword": bool(re.search(r"pass|password", text, re.I)),
            "mentionsTarget": any(
                section_mentions_target(lines, target_domain) for lines in sections
            ),
            "selectedSectionMentionsTarget": target_confirmed,
            "selectedSectionIndex": section_index,
            "sectionIndexValid": True,
            "selectedSectionScore": score,
            "sectionCount": len(sections),
            "valuesRedacted": True,
        },
    }


def redacted_section_probe(path, target_domain, protocol="ftps"):
    if protocol not in {"ftps", "ftp"}:
        raise ValueError("unsupported probe protocol")
    _text, sections = parse_sections(path)
    results = []
    for index, lines in enumerate(sections, 1):
        parsed = parse_handoff_section(path, target_domain, index)
        fields = parsed["raw"]
        host = pick(fields, ["ftp server", "ftp host", "server", "host"])
        user = pick(fields, ["ftp username", "ftp user", "username", "user"])
        password = pick(fields, ["ftp password", "ftp pass", "password", "pass"])
        port = pick_port(fields)
        row = {
            "section": index,
            "fieldKeys": sorted(fields.keys()),
            "mentionsTarget": parsed["signals"].get(
                "selectedSectionMentionsTarget", False
            ),
            "sectionScore": parsed["signals"].get("selectedSectionScore", 0),
            "hasHost": bool(host),
            "hasUser": bool(user),
            "hasPassword": bool(password),
            "hasResolvedPort": bool(port),
            "valuesRedacted": True,
        }
        for selected_protocol in (protocol,):
            if not (host and user and password):
                row[selected_protocol] = {
                    "status": "not_attempted",
                    "valuesRedacted": True,
                }
                continue
            phase = "login"
            try:
                with connect_ftp(host, user, password, port, selected_protocol) as ftp:
                    pwd_fingerprint = None
                    try:
                        pwd_fingerprint = fingerprint(ftp.pwd())
                    except Exception:
                        pwd_fingerprint = None
                    row[selected_protocol] = {
                        "status": "login_passed",
                        "pwdFingerprint": pwd_fingerprint,
                        "transportSecurity": transport_security(selected_protocol),
                        "serverCertificateVerification": selected_protocol == "ftps",
                        "uploadedCount": 0,
                        "safeNoOp": True,
                        "valuesRedacted": True,
                    }
            except Exception as exc:
                row[selected_protocol] = {
                    "status": "login_failed",
                    "errorType": exc.__class__.__name__,
                    "failedPhase": phase,
                    "transportSecurity": transport_security(selected_protocol),
                    "serverCertificateVerification": selected_protocol == "ftps",
                    "uploadedCount": 0,
                    "safeNoOp": True,
                    "valuesRedacted": True,
                }
        results.append(row)
    target_sections = [item for item in results if item["mentionsTarget"]]
    target_login_passed = any(
        item.get(selected_protocol, {}).get("status") == "login_passed"
        for item in target_sections
        for selected_protocol in (protocol,)
    )
    any_login_passed = any(
        item.get(selected_protocol, {}).get("status") == "login_passed"
        for item in results
        for selected_protocol in (protocol,)
    )
    return {
        "schemaVersion": "static_site.ftp_section_probe.v1",
        "targetDomain": target_domain,
        "protocol": protocol,
        "sectionCount": len(results),
        "targetSectionLoginPassed": target_login_passed,
        "anySectionLoginPassed": any_login_passed,
        "safeNoOp": True,
        "uploadedCount": 0,
        "sections": results,
        "valuesRedacted": True,
    }


def pick(fields, names):
    for name in names:
        if name in fields and fields[name]:
            return fields[name]
    return None


def pick_port(fields):
    value = pick(fields, ["port", "ftp port", "ftps port", "ftp & explicit ftps port"])
    if not value:
        return 21
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else 21


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def connect_ftp(host, user, password, port, protocol):
    if protocol == "ftp":
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=20)
        ftp.login(user, password)
        return ftp
    context = ssl.create_default_context()
    ftp = ftplib.FTP_TLS(context=context)
    ftp.connect(host, port, timeout=20)
    ftp.login(user, password)
    ftp.prot_p()
    return ftp


def transport_security(protocol):
    return "plain_ftp" if protocol == "ftp" else "explicit_ftps"


class StaticSiteReadbackError(ValueError):
    """Raised when held FTPS bytes cannot be read back exactly."""


def split_truth_ordered_files(files):
    """Return non-claim bytes first and exact release-claim bytes last."""
    by_path = {entry["relativePath"].as_posix(): entry for entry in files}
    if len(by_path) != len(files):
        raise SitePackageError("upload snapshot contains duplicate paths")
    if any(path not in by_path for path in RELEASE_CLAIM_PATHS):
        raise SitePackageError("upload snapshot is missing a release claim path")
    non_claims = [
        entry
        for path, entry in sorted(by_path.items())
        if path not in RELEASE_CLAIM_PATHS
    ]
    claims = [by_path[path] for path in RELEASE_CLAIM_PATHS]
    return non_claims, claims


def readback_exact(ftp, remote_name, expected_bytes):
    held = io.BytesIO()
    ftp.retrbinary("RETR " + remote_name, held.write)
    if held.getvalue() != expected_bytes:
        raise StaticSiteReadbackError("remote bytes differ from held package bytes")


def empty_handoff_parse():
    return {
        "raw": {},
        "signals": {
            "hasFtp": False,
            "hasHost": False,
            "hasUser": False,
            "hasPassword": False,
            "mentionsTarget": False,
            "selectedSectionMentionsTarget": False,
            "selectedSectionIndex": None,
            "sectionIndexValid": None,
            "selectedSectionScore": 0,
            "sectionCount": 0,
            "valuesRedacted": True,
        },
    }


def candidate_remote_dirs(fields, target_domain):
    explicit = pick(
        fields,
        [
            "remote_dir",
            "remote dir",
            "path",
            "directory",
            "application root",
            "app root",
            "document root",
            "public root",
        ],
    )
    candidates = []
    if explicit:
        candidates.append(("handoff_field", explicit))
    for label, path in [
        ("login_root", "."),
        ("domain_root", target_domain),
        ("public_html_domain", "public_html/" + target_domain),
        ("public_html_root", "public_html"),
        ("www_domain", "www/" + target_domain),
        ("domains_public_html", "domains/" + target_domain + "/public_html"),
    ]:
        candidates.append((label, path))
    unique = []
    seen = set()
    for label, path in candidates:
        normalized = path.strip().strip("/") or "."
        if normalized not in seen:
            unique.append((label, normalized))
            seen.add(normalized)
    return unique


def discover_remote_dir(host, user, password, port, fields, target_domain, protocol):
    report = {
        "attempted": False,
        "candidateCount": 0,
        "found": False,
        "foundSource": None,
        "foundFingerprint": None,
        "valuesRedacted": True,
    }
    if not (host and user and password):
        report["status"] = "missing_ftp_fields"
        return None, report
    candidates = candidate_remote_dirs(fields, target_domain)
    report["candidateCount"] = len(candidates)
    report["attempted"] = True
    phase = "connect"
    try:
        phase = "login"
        with connect_ftp(host, user, password, port, protocol) as ftp:
            home = ftp.pwd()
            for label, path in candidates:
                try:
                    phase = "candidate_cwd_home"
                    ftp.cwd(home)
                    phase = "candidate_cwd_remote"
                    ftp.cwd(path)
                    ftp.nlst()
                except Exception:
                    continue
                report["found"] = True
                report["foundSource"] = label
                report["foundFingerprint"] = fingerprint(path)
                report["status"] = "found"
                return path, report
    except Exception as exc:
        report["status"] = "connection_or_login_failed"
        report["errorType"] = exc.__class__.__name__
        report["failedPhase"] = phase
        return None, report
    report["status"] = "not_found"
    return None, report


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", default=r"E:\ftp_Deploy.txt")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--target-domain", default=TARGET_DOMAIN)
    parser.add_argument("--remote-dir")
    parser.add_argument("--json-out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--discover-remote-dir", action="store_true")
    parser.add_argument("--allow-discovered-live-upload", action="store_true")
    parser.add_argument("--protocol", choices=["ftps", "ftp"], default="ftps")
    parser.add_argument("--connection-check", action="store_true")
    parser.add_argument("--section-index", type=int)
    parser.add_argument("--probe-sections", action="store_true")
    parser.add_argument("--filezilla-site-match")
    parser.add_argument("--filezilla-path", default=str(DEFAULT_FILEZILLA_SITEMANAGER))
    parser.add_argument("--package")
    parser.add_argument("--package-manifest")
    parser.add_argument("--phase", choices=sorted(RELEASE_PHASES))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.connection_check:
        parser.error("--dry-run and --connection-check are mutually exclusive")

    release_invocation = not args.connection_check and not args.probe_sections
    phase_error = None
    if release_invocation and args.phase not in RELEASE_PHASES:
        phase_error = "release_phase_required"
    elif not release_invocation and args.phase is not None:
        phase_error = "release_phase_not_allowed_for_target_only_check"
    if phase_error:
        report = {
            "schemaVersion": "static_site.ftp_deploy.v3",
            "targetDomain": TARGET_DOMAIN,
            "releasePhase": args.phase,
            "status": phase_error,
            "safeNoOp": True,
            "uploadedCount": 0,
            "valuesRedacted": True,
        }
        emit_report(report, args)
        return 1

    if args.target_domain.strip().lower().rstrip(".") != TARGET_DOMAIN:
        report = {
            "schemaVersion": "static_site.ftp_deploy.v3",
            "targetDomain": TARGET_DOMAIN,
            "requestedTargetAccepted": False,
            "status": "target_domain_not_allowed",
            "safeNoOp": True,
            "uploadedCount": 0,
            "valuesRedacted": True,
        }
        emit_report(report, args)
        return 1
    args.target_domain = TARGET_DOMAIN

    site_root = Path(args.site_root)
    if args.probe_sections:
        try:
            report = redacted_section_probe(
                args.handoff, args.target_domain, args.protocol
            )
            report["status"] = "probe_complete"
        except (OSError, UnicodeError, ValueError):
            report = {
                "schemaVersion": "static_site.ftp_section_probe.v1",
                "targetDomain": args.target_domain,
                "status": "handoff_unavailable",
                "sectionCount": 0,
                "targetSectionLoginPassed": False,
                "anySectionLoginPassed": False,
                "safeNoOp": True,
                "uploadedCount": 0,
                "sections": [],
                "valuesRedacted": True,
            }
        emit_report(report, args)
        return 0 if report["targetSectionLoginPassed"] else 1

    credential_error = None
    filezilla_report = None
    filezilla_fields = None
    if args.filezilla_site_match:
        # A profile-only invocation must never touch the optional handoff path.
        parsed = empty_handoff_parse()
        credential_source = "filezilla_site_manager"
        try:
            filezilla_fields, filezilla_report = load_filezilla_site(
                args.filezilla_path, args.filezilla_site_match, args.target_domain
            )
        except (OSError, UnicodeError, ET.ParseError, ValueError):
            filezilla_fields = None
            filezilla_report = {
                "status": "filezilla_site_manager_invalid",
                "valuesRedacted": True,
            }
            credential_error = "filezilla_site_manager_invalid"
        if filezilla_fields:
            match_confirms_target = bool(
                filezilla_report.get("targetIdentityConfirmed")
            )
            parsed = {
                "raw": filezilla_fields,
                "signals": {
                    "hasFtp": True,
                    "hasHost": bool(filezilla_fields.get("ftp server")),
                    "hasUser": bool(filezilla_fields.get("ftp username")),
                    "hasPassword": bool(filezilla_fields.get("password")),
                    "mentionsTarget": match_confirms_target,
                    "selectedSectionMentionsTarget": match_confirms_target,
                    "selectedSectionIndex": None,
                    "sectionIndexValid": None,
                    "selectedSectionScore": 100,
                    "sectionCount": None,
                    "valuesRedacted": True,
                },
            }
        elif credential_error is None:
            credential_error = (filezilla_report or {}).get(
                "status", "filezilla_site_not_found"
            )
    else:
        credential_source = "handoff"
        try:
            parsed = (
                parse_handoff_section(
                    args.handoff, args.target_domain, args.section_index
                )
                if args.section_index is not None
                else parse_handoff(args.handoff, args.target_domain)
            )
            if args.section_index is not None and not parsed["signals"].get(
                "sectionIndexValid"
            ):
                credential_error = "section_index_invalid"
        except (OSError, UnicodeError, ValueError):
            parsed = empty_handoff_parse()
            credential_error = "handoff_unavailable"

    fields = parsed["raw"]
    host = pick(fields, ["ftp server", "ftp host", "server", "host"])
    user = pick(fields, ["ftp username", "ftp user", "username", "user"])
    password = pick(fields, ["ftp password", "ftp pass", "password", "pass"])
    port = pick_port(fields)
    remote_dir = args.remote_dir or pick(
        fields,
        [
            "remote_dir",
            "remote dir",
            "path",
            "directory",
            "application root",
            "app root",
            "document root",
            "public root",
        ],
    )
    if args.filezilla_site_match and filezilla_fields and not remote_dir:
        remote_dir = "."
    discovered_dir = None
    discovery_report = None
    if args.discover_remote_dir and not remote_dir:
        discovered_dir, discovery_report = discover_remote_dir(
            host, user, password, port, fields, args.target_domain, args.protocol
        )
        if args.dry_run or args.allow_discovered_live_upload:
            remote_dir = discovered_dir

    release_mode = not args.connection_check
    projection_report = {
        "checked": False,
        "ok": None,
        "driftFiles": [],
        "valuesRedacted": True,
    }
    projection_error = None
    snapshot_ledger = None
    source_snapshot = None
    snapshot_error = None
    if release_mode:
        try:
            source_snapshot = capture_site_snapshot(site_root, require_complete=True)
        except (OSError, UnicodeError, SitePackageError):
            snapshot_error = "site_snapshot_invalid"
    if source_snapshot is not None:
        try:
            snapshot_ledger, drift = snapshot_projection_drift(source_snapshot)
            if snapshot_ledger is not None:
                projection_report["checked"] = True
                projection_report["ok"] = not drift
                projection_report["driftFiles"] = drift
                if drift:
                    projection_error = "release_projection_drift"
        except SitePackageError:
            projection_report["checked"] = True
            projection_report["ok"] = False
            projection_error = "release_projection_invalid"

    package_snapshot = None
    package_error = None
    if args.connection_check and (args.package or args.package_manifest):
        package_error = "connection_check_is_target_only"
    elif release_mode and not (args.package and args.package_manifest):
        package_error = "immutable_package_required"
    elif bool(args.package) != bool(args.package_manifest):
        package_error = "package_arguments_incomplete"
    elif args.package and args.package_manifest and source_snapshot is not None:
        try:
            package_snapshot = verify_package(
                args.package,
                args.package_manifest,
                source_snapshot,
                phase=args.phase,
                repo_root=args.repo_root,
                site_root=site_root,
            )
        except ReleaseIdentityError as exc:
            package_error = exc.code
        except (OSError, UnicodeError, SitePackageError):
            package_error = "package_verification_failed"

    planned_snapshot = package_snapshot if release_mode else None
    packaged_files = planned_snapshot["files"] if planned_snapshot else []
    non_claim_files = []
    claim_files = []
    plan_error = None
    if packaged_files:
        try:
            non_claim_files, claim_files = split_truth_ordered_files(packaged_files)
        except SitePackageError:
            plan_error = "truth_ordered_upload_plan_invalid"
    operation = (
        "stage_nonclaims"
        if args.phase == PREACTIVATION_PHASE
        else "activate_claims"
        if args.phase == FINAL_PHASE
        else None
    )
    planned_upload_files = (
        non_claim_files
        if args.phase == PREACTIVATION_PHASE
        else claim_files
        if args.phase == FINAL_PHASE
        else []
    )
    planned_readback_count = (
        len(non_claim_files)
        if args.phase == PREACTIVATION_PHASE
        else len(non_claim_files) + len(claim_files)
        if args.phase == FINAL_PHASE
        else 0
    )
    release_identity = package_snapshot["releaseIdentity"] if package_snapshot else None
    activation_gate = release_activation_gate(release_identity)
    qualification = (
        package_snapshot.get("sourceQualification", {}) if package_snapshot else {}
    )
    report = {
        "schemaVersion": "static_site.ftp_deploy.v3",
        "targetDomain": args.target_domain,
        "dryRun": args.dry_run,
        "releasePhase": args.phase,
        "operation": operation,
        "siteRootKind": "selected_static_site",
        "siteRootExists": site_root.exists(),
        "plannedUploadCount": len(planned_upload_files),
        "plannedReadbackCount": planned_readback_count,
        "plannedNonClaimUploadCount": (
            len(non_claim_files) if args.phase == PREACTIVATION_PHASE else 0
        ),
        "plannedNonClaimReadbackCount": len(non_claim_files),
        "plannedClaimUploadCount": (
            len(claim_files) if args.phase == FINAL_PHASE else 0
        ),
        "plannedClaimReadbackCount": (
            len(claim_files) if args.phase == FINAL_PHASE else 0
        ),
        "claimUploadOrder": list(RELEASE_CLAIM_PATHS),
        "signals": parsed["signals"],
        "hasResolvedHost": bool(host),
        "hasResolvedUser": bool(user),
        "hasResolvedPassword": bool(password),
        "hasResolvedPort": bool(port),
        "protocol": args.protocol,
        "transportSecurity": transport_security(args.protocol),
        "serverCertificateVerification": args.protocol == "ftps",
        "remoteDirResolved": bool(remote_dir),
        "credentialSource": credential_source,
        "remoteDirSource": "argument_or_credential_source"
        if (
            args.remote_dir
            or pick(
                fields,
                [
                    "remote_dir",
                    "remote dir",
                    "path",
                    "directory",
                    "application root",
                    "app root",
                    "document root",
                    "public root",
                ],
            )
        )
        else (
            "filezilla_login_root"
            if (filezilla_fields and remote_dir == ".")
            else ("discovery" if remote_dir else None)
        ),
        "releaseProjection": projection_report,
        "releaseActivationGate": activation_gate,
        "sourceTagPublished": bool(qualification.get("remoteTagPresent")),
        "sourceTagIdentityVerified": bool(
            args.phase == FINAL_PHASE
            and qualification.get("remoteTagPresent")
            and qualification.get("tagSiteBytesVerified")
            and qualification.get("annotatedTagNameVerified")
        ),
        "mainPublished": False,
        "immutablePackageRequiredForRelease": release_mode,
        "immutablePackageProvided": bool(package_snapshot),
        "sourcePackageByteIdentical": bool(
            package_snapshot
            and source_snapshot
            and site_snapshot_matches(package_snapshot, source_snapshot)
        ),
        "valuesRedacted": True,
    }
    if source_snapshot:
        report["siteManifest"] = source_snapshot["manifest"]
    if package_snapshot:
        report["package"] = package_snapshot["package"]
        report["uploadManifest"] = package_snapshot["manifest"]
        report["releaseIdentity"] = package_snapshot["releaseIdentity"]
        report["sourceQualification"] = package_snapshot["sourceQualification"]
    if filezilla_report:
        report["filezilla"] = filezilla_report
    if remote_dir:
        report["remoteDirFingerprint"] = fingerprint(remote_dir)
    if discovery_report:
        report["discovery"] = discovery_report

    status = "ready"
    if credential_error:
        status = credential_error
    elif release_mode and args.protocol != "ftps":
        status = "release_requires_explicit_ftps"
    elif projection_error:
        status = projection_error
    elif snapshot_error:
        status = snapshot_error
    elif package_error:
        status = package_error
    elif plan_error:
        status = plan_error
    elif release_mode and (not site_root.exists() or not planned_upload_files):
        status = "missing_site_files"
    elif not (host and user and password):
        status = "missing_ftp_fields"
    elif not remote_dir:
        status = "remote_dir_unresolved"
    elif not parsed["signals"]["selectedSectionMentionsTarget"]:
        status = "target_section_not_confirmed"
    elif release_mode and not activation_gate["ok"]:
        status = "activation_date_not_current_utc"
    report["status"] = status
    report["safeNoOp"] = bool(
        args.dry_run or args.connection_check or report["status"] != "ready"
    )
    if discovered_dir and not args.allow_discovered_live_upload and not args.dry_run:
        report["status"] = "discovered_remote_dir_requires_explicit_live_allow"
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1

    def recheck_bound_inputs():
        if args.connection_check:
            return True
        try:
            current_source = capture_site_snapshot(site_root, require_complete=True)
            if source_snapshot is None or not site_snapshot_matches(
                source_snapshot, current_source
            ):
                return False
            if args.package and args.package_manifest:
                current_package = verify_package(
                    args.package,
                    args.package_manifest,
                    current_source,
                    phase=args.phase,
                    repo_root=args.repo_root,
                    site_root=site_root,
                )
                if package_snapshot is None or (
                    current_package["package"] != package_snapshot["package"]
                    or current_package["releaseIdentity"]
                    != package_snapshot["releaseIdentity"]
                    or current_package["sourceQualification"]
                    != package_snapshot["sourceQualification"]
                ):
                    return False
            return True
        except (OSError, UnicodeError, SitePackageError, ReleaseIdentityError):
            return False

    if args.dry_run and report["status"] == "ready":
        report["manifestRecheckedAtDryRun"] = recheck_bound_inputs()
        if not report["manifestRecheckedAtDryRun"]:
            report["status"] = "site_or_package_changed_during_preflight"
        report["releaseActivationGateAtDryRunCompletion"] = release_activation_gate(
            release_identity
        )
        if (
            report["status"] == "ready"
            and not report["releaseActivationGateAtDryRunCompletion"]["ok"]
        ):
            report["status"] = "activation_date_changed_during_dry_run"
    if args.dry_run:
        emit_report(report, args)
        return 0 if report["status"] == "ready" else 1
    if report["status"] != "ready":
        emit_report(report, args)
        return 1
    if args.connection_check:
        report["manifestRecheckedBeforeConnection"] = recheck_bound_inputs()
        if not report["manifestRecheckedBeforeConnection"]:
            report["status"] = "site_or_package_changed_during_preflight"
            report["safeNoOp"] = True
            emit_report(report, args)
            return 1
        phase = "login"
        try:
            with connect_ftp(host, user, password, port, args.protocol) as ftp:
                phase = "cwd_remote_dir"
                ftp.cwd(remote_dir)
                phase = "pwd"
                ftp.pwd()
        except Exception as exc:
            report["status"] = "connection_check_failed"
            report["uploadedCount"] = 0
            report["errorType"] = exc.__class__.__name__
            report["failedPhase"] = phase
            report["safeNoOp"] = True
            emit_report(report, args)
            return 1
        report["status"] = "connection_check_passed"
        report["uploadedCount"] = 0
        report["safeNoOp"] = True
        emit_report(report, args)
        return 0

    report["manifestRecheckedBeforeOperation"] = recheck_bound_inputs()
    if not report["manifestRecheckedBeforeOperation"]:
        report["status"] = "site_or_package_changed_before_operation"
        report["uploadedCount"] = 0
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1
    report["releaseActivationGateBeforeOperation"] = release_activation_gate(
        release_identity
    )
    if not report["releaseActivationGateBeforeOperation"]["ok"]:
        report["status"] = "activation_date_not_current_utc"
        report["uploadedCount"] = 0
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1

    uploaded_count = 0
    upload_attempted_count = 0
    readback_attempted_count = 0
    readback_verified_count = 0
    non_claim_uploaded_count = 0
    non_claim_readback_count = 0
    claim_uploaded_count = 0
    claim_readback_count = 0
    claims_exposed = False
    staged_nonclaim_readback_complete = False
    phase = "connect"
    try:
        phase = "login"
        with connect_ftp(host, user, password, port, args.protocol) as ftp:
            phase = "cwd_remote_dir"
            ftp.cwd(remote_dir)
            made_dirs = set(["."])
            if args.phase == PREACTIVATION_PHASE:
                for entry in non_claim_files:
                    rel = entry["relativePath"]
                    current = ""
                    for part in rel.parts[:-1]:
                        current = part if not current else current + "/" + part
                        if current in made_dirs:
                            continue
                        try:
                            phase = "mkdir:nonclaim:" + current
                            ftp.mkd(current)
                        except Exception:
                            pass
                        made_dirs.add(current)
                    remote_name = rel.as_posix()
                    phase = "upload:nonclaim:" + remote_name
                    upload_attempted_count += 1
                    ftp.storbinary("STOR " + remote_name, io.BytesIO(entry["bytes"]))
                    uploaded_count += 1
                    non_claim_uploaded_count += 1
            for entry in non_claim_files:
                remote_name = entry["relativePath"].as_posix()
                phase = (
                    "readback:nonclaim:"
                    if args.phase == PREACTIVATION_PHASE
                    else "readback:staged-nonclaim:"
                ) + remote_name
                readback_attempted_count += 1
                readback_exact(ftp, remote_name, entry["bytes"])
                readback_verified_count += 1
                non_claim_readback_count += 1
            staged_nonclaim_readback_complete = non_claim_readback_count == len(
                non_claim_files
            ) and (
                args.phase == FINAL_PHASE
                or non_claim_uploaded_count == len(non_claim_files)
            )
            if not staged_nonclaim_readback_complete:
                raise StaticSiteReadbackError(
                    "staged non-claim FTPS readback did not complete"
                )
            if args.phase == FINAL_PHASE:
                phase = "final-preclaim:bound-input-recheck"
                report["manifestRecheckedBeforeClaims"] = recheck_bound_inputs()
                if not report["manifestRecheckedBeforeClaims"]:
                    raise SitePackageError("bound inputs changed before claim exposure")
                phase = "final-preclaim:activation-date-gate"
                report["releaseActivationGateBeforeClaims"] = release_activation_gate(
                    release_identity
                )
                if not report["releaseActivationGateBeforeClaims"]["ok"]:
                    raise SitePackageError(
                        "activation date changed before claim exposure"
                    )
                for entry in claim_files:
                    rel = entry["relativePath"]
                    current = ""
                    for part in rel.parts[:-1]:
                        current = part if not current else current + "/" + part
                        if current in made_dirs:
                            continue
                        try:
                            phase = "mkdir:claim:" + current
                            ftp.mkd(current)
                        except Exception:
                            pass
                        made_dirs.add(current)
                    remote_name = rel.as_posix()
                    phase = "upload:claim:" + remote_name
                    upload_attempted_count += 1
                    claims_exposed = True
                    ftp.storbinary("STOR " + remote_name, io.BytesIO(entry["bytes"]))
                    uploaded_count += 1
                    claim_uploaded_count += 1
                    phase = "readback:claim:" + remote_name
                    readback_attempted_count += 1
                    readback_exact(ftp, remote_name, entry["bytes"])
                    readback_verified_count += 1
                    claim_readback_count += 1
    except Exception as exc:
        if args.phase == PREACTIVATION_PHASE:
            if phase.startswith("upload:nonclaim:") or phase.startswith(
                "mkdir:nonclaim:"
            ):
                status = "nonclaim_stage_upload_failed_partial_possible"
            elif phase.startswith("readback:nonclaim:"):
                status = "nonclaim_stage_readback_failed_partial_possible"
            else:
                status = "nonclaim_stage_connection_failed"
        else:
            if phase.startswith("readback:staged-nonclaim:"):
                status = "final_staged_nonclaim_readback_failed"
            elif phase.startswith("final-preclaim:"):
                status = "final_preclaim_gate_failed_no_claims"
            elif claims_exposed:
                status = "claim_activation_failed_partial_possible"
            else:
                status = "final_claim_activation_connection_failed"
        report["status"] = status
        report["uploadedCount"] = uploaded_count
        report["uploadAttemptedCount"] = upload_attempted_count
        report["readbackAttemptedCount"] = readback_attempted_count
        report["readbackVerifiedCount"] = readback_verified_count
        report["nonClaimUploadedCount"] = non_claim_uploaded_count
        report["nonClaimReadbackCount"] = non_claim_readback_count
        report["claimUploadedCount"] = claim_uploaded_count
        report["claimReadbackCount"] = claim_readback_count
        report["stagedNonClaimReadbackComplete"] = staged_nonclaim_readback_complete
        report["claimsExposed"] = claims_exposed
        report["errorType"] = exc.__class__.__name__
        report["failedPhase"] = phase
        report["safeNoOp"] = upload_attempted_count == 0
        emit_report(report, args)
        return 1
    report["manifestRecheckedAtCompletion"] = recheck_bound_inputs()
    report["releaseActivationGateAtCompletion"] = release_activation_gate(
        release_identity
    )
    if args.phase == PREACTIVATION_PHASE:
        if not report["manifestRecheckedAtCompletion"]:
            report["status"] = "nonclaims_staged_identity_changed"
        elif not report["releaseActivationGateAtCompletion"]["ok"]:
            report["status"] = "nonclaims_staged_activation_date_changed"
        else:
            report["status"] = "nonclaims_staged_preactivation"
            report["nextRequiredGate"] = "preactivation_nonclaim_https_verification"
    else:
        if not report["manifestRecheckedAtCompletion"]:
            report["status"] = "claims_activated_identity_changed"
        elif not report["releaseActivationGateAtCompletion"]["ok"]:
            report["status"] = "claims_activated_activation_date_changed"
        else:
            report["status"] = "claims_activated_final"
            report["nextRequiredGate"] = "final_full_https_verification"
    report["uploadedCount"] = uploaded_count
    report["uploadAttemptedCount"] = upload_attempted_count
    report["readbackAttemptedCount"] = readback_attempted_count
    report["readbackVerifiedCount"] = readback_verified_count
    report["nonClaimUploadedCount"] = non_claim_uploaded_count
    report["nonClaimReadbackCount"] = non_claim_readback_count
    report["claimUploadedCount"] = claim_uploaded_count
    report["claimReadbackCount"] = claim_readback_count
    report["stagedNonClaimReadbackComplete"] = staged_nonclaim_readback_complete
    report["claimsExposed"] = claims_exposed
    report["safeNoOp"] = False
    emit_report(report, args)
    expected_uploads = (
        len(non_claim_files) if args.phase == PREACTIVATION_PHASE else len(claim_files)
    )
    expected_readbacks = (
        len(non_claim_files)
        if args.phase == PREACTIVATION_PHASE
        else len(non_claim_files) + len(claim_files)
    )
    phase_complete = (
        uploaded_count == expected_uploads
        and readback_verified_count == expected_readbacks
        and staged_nonclaim_readback_complete
        and (
            claim_readback_count == 0
            if args.phase == PREACTIVATION_PHASE
            else claim_readback_count == len(RELEASE_CLAIM_PATHS)
        )
    )
    return (
        0
        if report["manifestRecheckedAtCompletion"]
        and report["releaseActivationGateAtCompletion"]["ok"]
        and phase_complete
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
