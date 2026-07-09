import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ftp_deploy_memoryendpoints import connect_ftp, fingerprint, pick_port, transport_security
from ftp_deploy_static_site import DEFAULT_FILEZILLA_SITEMANAGER, load_filezilla_site


def load_secret(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError("MySQL secret config must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MySQL secret config must be a JSON object.")
    required = ("host", "database", "user", "password")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise RuntimeError("MySQL secret config is missing required fields.")
    if "port" in payload:
        int(payload["port"])
    return payload


def emit(report, json_out=None):
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


def safe_remote_path(value):
    path = (value or ".local-secrets/mysql.json").replace("\\", "/").strip("/")
    parts = [part for part in path.split("/") if part]
    if not parts or ".." in parts or parts[0] != ".local-secrets" or not path.endswith(".json"):
        raise RuntimeError("Remote secret path must stay under .local-secrets/ and end with .json.")
    return path


def ensure_remote_dirs(ftp, remote_path):
    current = ""
    for part in remote_path.split("/")[:-1]:
        current = part if not current else current + "/" + part
        try:
            ftp.mkd(current)
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-json", default=str(ROOT / ".local-secrets" / "mysql.json"))
    parser.add_argument("--remote-path", default=".local-secrets/mysql.json")
    parser.add_argument("--remote-dir")
    parser.add_argument("--filezilla-site-match", default="memoryendpoints")
    parser.add_argument("--filezilla-path", default=str(DEFAULT_FILEZILLA_SITEMANAGER))
    parser.add_argument("--protocol", choices=["ftps", "ftp"], default="ftps")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--connection-check", action="store_true")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    secret_path = Path(args.secret_json)
    remote_path = safe_remote_path(args.remote_path)
    report = {
        "schemaVersion": "memoryendpoints.mysql_secret_upload.v1",
        "dryRun": args.dry_run,
        "connectionCheck": args.connection_check,
        "secretFilePresent": secret_path.exists(),
        "remotePathFingerprint": fingerprint(remote_path),
        "protocol": args.protocol,
        "transportSecurity": transport_security(args.protocol),
        "valuesRedacted": True,
    }
    try:
        if not secret_path.exists():
            raise RuntimeError("MySQL secret config file does not exist.")
        load_secret(secret_path)
        report["secretJsonValid"] = True
        fields, filezilla = load_filezilla_site(args.filezilla_path, args.filezilla_site_match)
        report["filezilla"] = filezilla
        if not fields:
            raise RuntimeError("FileZilla site profile was not found.")
        host = fields.get("ftp server")
        user = fields.get("ftp username")
        password = fields.get("password")
        port = pick_port(fields)
        remote_dir = args.remote_dir or fields.get("remote_dir") or "."
        report["hasResolvedHost"] = bool(host)
        report["hasResolvedUser"] = bool(user)
        report["hasResolvedPassword"] = bool(password)
        report["hasResolvedPort"] = bool(port)
        report["remoteDirFingerprint"] = fingerprint(remote_dir)
        report["remoteDirResolved"] = bool(remote_dir)
        if args.dry_run:
            report["status"] = "ready"
            report["safeNoOp"] = True
            report["uploadedCount"] = 0
            emit(report, args.json_out)
            return 0
        with connect_ftp(host, user, password, port, args.protocol) as ftp:
            ftp.cwd(remote_dir)
            if args.connection_check:
                ftp.pwd()
                report["status"] = "connection_check_passed"
                report["safeNoOp"] = True
                report["uploadedCount"] = 0
                emit(report, args.json_out)
                return 0
            ensure_remote_dirs(ftp, remote_path)
            ftp.storbinary("STOR " + remote_path, io.BytesIO(secret_path.read_bytes()))
        report["status"] = "uploaded"
        report["safeNoOp"] = False
        report["uploadedCount"] = 1
        emit(report, args.json_out)
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["errorType"] = exc.__class__.__name__
        report["safeNoOp"] = True
        report["uploadedCount"] = 0
        emit(report, args.json_out)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
