import argparse
import ftplib
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
EXCLUDE_NAMES = {".gitkeep"}
EXCLUDE_SUFFIXES = {".bak", ".tmp", ".log"}


def emit_report(report, args):
    if getattr(args, "json_out", None):
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


def parse_handoff(path, target_domain):
    text, sections = parse_sections(path)
    target = target_domain.lower()
    target_labels = {target, target.replace(".", ""), target.split(".", 1)[0]}
    parsed_sections = []
    for lines in sections:
        section_text = "\n".join(lines)
        lower = section_text.lower()
        score = 0
        if any(label and label in lower for label in target_labels):
            score += 100
        if re.search(r"ftp|ftps|sftp", section_text, re.I):
            score += 10
        if re.search(r"pass|password", section_text, re.I):
            score += 5
        if re.search(r"user|username", section_text, re.I):
            score += 3
        if re.search(r"host|server", section_text, re.I):
            score += 3
        parsed_sections.append({"fields": fields_from_lines(lines), "score": score, "text": section_text})
    best = max(parsed_sections, key=lambda item: item["score"]) if parsed_sections else {"fields": {}, "score": 0, "text": ""}
    joined = " ".join(text.split())
    return {
        "raw": best["fields"],
        "signals": {
            "hasFtp": bool(re.search(r"ftp|ftps|sftp", text, re.I)),
            "hasHost": bool(re.search(r"host|server", text, re.I)),
            "hasUser": bool(re.search(r"user|username", text, re.I)),
            "hasPassword": bool(re.search(r"pass|password", text, re.I)),
            "mentionsTarget": any(label and label in joined.lower() for label in target_labels),
            "selectedSectionMentionsTarget": any(label and label in best["text"].lower() for label in target_labels),
            "sectionCount": len(parsed_sections),
            "valuesRedacted": True,
        },
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
    ftp = ftplib.FTP_TLS()
    ftp.connect(host, port, timeout=20)
    ftp.login(user, password)
    ftp.prot_p()
    return ftp


def transport_security(protocol):
    return "plain_ftp" if protocol == "ftp" else "explicit_ftps"


def iter_site_files(site_root):
    site_root = site_root.resolve()
    for path in site_root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(site_root)
        if path.name in EXCLUDE_NAMES:
            continue
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        yield path, rel


def candidate_remote_dirs(fields, target_domain):
    explicit = pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root", "document root", "public root"])
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", default=r"E:\ftp_Deploy.txt")
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--target-domain", default="multiagentmemory.com")
    parser.add_argument("--remote-dir")
    parser.add_argument("--json-out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--discover-remote-dir", action="store_true")
    parser.add_argument("--allow-discovered-live-upload", action="store_true")
    parser.add_argument("--protocol", choices=["ftps", "ftp"], default="ftps")
    parser.add_argument("--connection-check", action="store_true")
    args = parser.parse_args(argv)

    site_root = Path(args.site_root)
    parsed = parse_handoff(args.handoff, args.target_domain)
    fields = parsed["raw"]
    host = pick(fields, ["ftp server", "ftp host", "server", "host"])
    user = pick(fields, ["ftp username", "ftp user", "username", "user"])
    password = pick(fields, ["ftp password", "ftp pass", "password", "pass"])
    port = pick_port(fields)
    remote_dir = args.remote_dir or pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root", "document root", "public root"])
    discovered_dir = None
    discovery_report = None
    if args.discover_remote_dir and not remote_dir:
        discovered_dir, discovery_report = discover_remote_dir(host, user, password, port, fields, args.target_domain, args.protocol)
        if args.dry_run or args.allow_discovered_live_upload:
            remote_dir = discovered_dir

    planned_files = list(iter_site_files(site_root))
    report = {
        "schemaVersion": "static_site.ftp_deploy.v1",
        "targetDomain": args.target_domain,
        "dryRun": args.dry_run,
        "siteRoot": str(site_root),
        "siteRootExists": site_root.exists(),
        "plannedUploadCount": len(planned_files),
        "signals": parsed["signals"],
        "hasResolvedHost": bool(host),
        "hasResolvedUser": bool(user),
        "hasResolvedPassword": bool(password),
        "hasResolvedPort": bool(port),
        "protocol": args.protocol,
        "transportSecurity": transport_security(args.protocol),
        "remoteDirResolved": bool(remote_dir),
        "remoteDirSource": "argument_or_handoff" if (args.remote_dir or pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root", "document root", "public root"])) else ("discovery" if remote_dir else None),
        "valuesRedacted": True,
    }
    if remote_dir:
        report["remoteDirFingerprint"] = fingerprint(remote_dir)
    if discovery_report:
        report["discovery"] = discovery_report
    report["status"] = "ready" if (remote_dir and site_root.exists() and planned_files) else "missing_prerequisite"
    report["safeNoOp"] = bool(args.dry_run or args.connection_check or report["status"] != "ready")
    if discovered_dir and not args.allow_discovered_live_upload and not args.dry_run:
        report["status"] = "discovered_remote_dir_requires_explicit_live_allow"
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1
    if args.dry_run:
        emit_report(report, args)
        return 0 if report["status"] == "ready" else 1
    if report["status"] != "ready":
        emit_report(report, args)
        return 1
    if not parsed["signals"]["selectedSectionMentionsTarget"] and not args.remote_dir:
        report["status"] = "target_section_not_confirmed"
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1
    if not (host and user and password):
        report["status"] = "missing_ftp_fields"
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1
    if args.connection_check:
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

    uploaded_count = 0
    phase = "connect"
    try:
        phase = "login"
        with connect_ftp(host, user, password, port, args.protocol) as ftp:
            phase = "cwd_remote_dir"
            ftp.cwd(remote_dir)
            made_dirs = set(["."])
            for path, rel in planned_files:
                current = ""
                for part in rel.parts[:-1]:
                    current = part if not current else current + "/" + part
                    if current in made_dirs:
                        continue
                    try:
                        phase = "mkdir:" + current
                        ftp.mkd(current)
                    except Exception:
                        pass
                    made_dirs.add(current)
                remote_name = str(rel).replace(os.sep, "/")
                phase = "upload:" + remote_name
                with open(str(path), "rb") as handle:
                    ftp.storbinary("STOR " + remote_name, handle)
                uploaded_count += 1
            marker = ("Static site upload for %s completed %s\n" % (args.target_domain, datetime.now(timezone.utc).replace(microsecond=0).isoformat())).encode("utf-8")
            phase = "upload:.deployment-marker.txt"
            ftp.storbinary("STOR .deployment-marker.txt", io.BytesIO(marker))
    except Exception as exc:
        report["status"] = "upload_failed_partial_possible" if uploaded_count else "connection_or_upload_failed"
        report["uploadedCount"] = uploaded_count
        report["errorType"] = exc.__class__.__name__
        report["failedPhase"] = phase
        report["safeNoOp"] = uploaded_count == 0
        emit_report(report, args)
        return 1
    report["status"] = "uploaded"
    report["uploadedCount"] = uploaded_count
    report["deploymentMarkerWritten"] = True
    report["safeNoOp"] = False
    emit_report(report, args)
    return 0

if __name__ == "__main__":
    sys.exit(main())
