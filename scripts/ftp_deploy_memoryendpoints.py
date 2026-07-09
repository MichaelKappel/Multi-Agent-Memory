import argparse
import ftplib
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dist" / "MemoryEndpoints.com-Production.zip"
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from package_memoryendpoints import iter_files, write_build_info


def emit_report(report, args):
    if getattr(args, "json_out", None):
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_handoff(path):
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

    parsed_sections = []
    for lines in sections:
        fields = {}
        section_text = "\n".join(lines)
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
            elif "=" in line:
                key, value = line.split("=", 1)
            else:
                continue
            fields[key.strip().lower()] = value.strip()
        score = 0
        lower = section_text.lower()
        if "memoryendpoints" in lower:
            score += 100
        if re.search(r"ftp|ftps|sftp", section_text, re.I):
            score += 10
        if re.search(r"pass|password", section_text, re.I):
            score += 5
        if re.search(r"user|username", section_text, re.I):
            score += 3
        if re.search(r"host|server", section_text, re.I):
            score += 3
        parsed_sections.append({"fields": fields, "score": score})
    best = max(parsed_sections, key=lambda item: item["score"]) if parsed_sections else {"fields": {}, "score": 0}
    joined = " ".join(text.split())
    return {
        "raw": best["fields"],
        "signals": {
            "hasFtp": bool(re.search(r"ftp|ftps|sftp", text, re.I)),
            "hasHost": bool(re.search(r"host|server", text, re.I)),
            "hasUser": bool(re.search(r"user|username", text, re.I)),
            "hasPassword": bool(re.search(r"pass|password", text, re.I)),
            "mentionsMemoryEndpoints": "memoryendpoints" in joined.lower(),
            "sectionCount": len(parsed_sections),
            "selectedSectionMentionsMemoryEndpoints": best["score"] >= 100,
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


def candidate_remote_dirs(fields):
    explicit = pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root"])
    candidates = []
    if explicit:
        candidates.append(("handoff_field", explicit))
    for label, path in [
        ("domain_app_root", "memoryendpoints.com"),
        ("public_html_domain", "public_html/memoryendpoints.com"),
        ("public_html_root", "public_html"),
        ("www_domain", "www/memoryendpoints.com"),
    ]:
        candidates.append((label, path))
    unique = []
    seen = set()
    for label, path in candidates:
        normalized = path.strip().strip("/")
        if normalized and normalized not in seen:
            unique.append((label, normalized))
            seen.add(normalized)
    return unique


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


def discover_remote_dir(host, user, password, port, fields, protocol):
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
    candidates = candidate_remote_dirs(fields)
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
    parser.add_argument("--package", default=str(PACKAGE))
    parser.add_argument("--remote-dir")
    parser.add_argument("--json-out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--discover-remote-dir", action="store_true")
    parser.add_argument("--allow-discovered-live-upload", action="store_true")
    parser.add_argument("--protocol", choices=["ftps", "ftp"], default="ftps")
    parser.add_argument("--connection-check", action="store_true")
    args = parser.parse_args(argv)

    parsed = parse_handoff(args.handoff)
    fields = parsed["raw"]
    host = pick(fields, ["ftp server", "ftp host", "server", "host"])
    user = pick(fields, ["ftp username", "ftp user", "username", "user"])
    password = pick(fields, ["ftp password", "ftp pass", "password", "pass"])
    port = pick_port(fields)
    remote_dir = args.remote_dir or pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root"])
    discovered_dir = None
    discovery_report = None
    if args.discover_remote_dir and not remote_dir:
        discovered_dir, discovery_report = discover_remote_dir(host, user, password, port, fields, args.protocol)
        if args.dry_run or args.allow_discovered_live_upload:
            remote_dir = discovered_dir

    build_info = write_build_info()
    planned_files = list(iter_files())
    report = {
        "schemaVersion": "memoryendpoints.ftp_deploy.v1",
        "dryRun": args.dry_run,
        "packageExists": Path(args.package).exists(),
        "plannedUploadCount": len(planned_files),
        "signals": parsed["signals"],
        "hasResolvedHost": bool(host),
        "hasResolvedUser": bool(user),
        "hasResolvedPassword": bool(password),
        "hasResolvedPort": bool(port),
        "protocol": args.protocol,
        "transportSecurity": transport_security(args.protocol),
        "remoteDirResolved": bool(remote_dir),
        "remoteDirSource": "argument_or_handoff" if (args.remote_dir or pick(fields, ["remote_dir", "remote dir", "path", "directory", "application root", "app root"])) else ("discovery" if remote_dir else None),
        "passengerRestartPlanned": bool(remote_dir),
        "valuesRedacted": True,
        "build": {
            "sourceSha": build_info["sourceSha"],
            "sourceShaShort": build_info["sourceShaShort"],
            "buildInfoFile": "memoryendpoints/build_info.generated.json",
            "valuesRedacted": True,
        },
    }
    if remote_dir:
        report["remoteDirFingerprint"] = fingerprint(remote_dir)
    if discovery_report:
        report["discovery"] = discovery_report
    report["status"] = "ready" if remote_dir else "missing_remote_dir"
    report["safeNoOp"] = not bool(remote_dir)
    if discovered_dir and not args.allow_discovered_live_upload and not args.dry_run:
        report["status"] = "discovered_remote_dir_requires_explicit_live_allow"
        report["safeNoOp"] = True
        emit_report(report, args)
        return 1
    if args.dry_run:
        emit_report(report, args)
        return 0 if report["packageExists"] and remote_dir else 1
    if not remote_dir:
        emit_report(report, args)
        return 1
    if not (host and user and password):
        report["status"] = "missing_ftp_fields"
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
                parts = list(rel.parts[:-1])
                current = ""
                for part in parts:
                    current = part if not current else current + "/" + part
                    if current in made_dirs:
                        continue
                    try:
                        phase = "mkdir:" + current
                        ftp.mkd(current)
                    except Exception:
                        pass
                    made_dirs.add(current)
                remote_name = str(rel).replace("\\", "/")
                phase = "upload:" + remote_name
                with open(str(path), "rb") as handle:
                    ftp.storbinary("STOR " + remote_name, handle)
                uploaded_count += 1
            try:
                phase = "mkdir:tmp"
                ftp.mkd("tmp")
            except Exception:
                pass
            restart_body = ("MemoryEndpoints Passenger restart requested %s\n" % datetime.now(timezone.utc).replace(microsecond=0).isoformat()).encode("utf-8")
            phase = "upload:tmp/restart.txt"
            ftp.storbinary("STOR tmp/restart.txt", io.BytesIO(restart_body))
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
    report["passengerRestartRequested"] = True
    emit_report(report, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
