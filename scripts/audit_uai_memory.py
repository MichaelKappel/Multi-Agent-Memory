import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UAI_DIR = ROOT / ".uai"
BOOTSTRAP_FILE = ".uai/startup-packet.uai"
REQUIRED_FIELDS = [
    "Purpose:",
    "Last verified:",
    "Memory scope:",
    "Public-safe status:",
    "Update route:",
    "Source of truth:",
    "Next action",
    "Must not expose:",
]
STARTUP_READ_ORDER = [
    ".uai/totem.uai",
    ".uai/constraints.uai",
    ".uai/file-handoff.uai",
    ".uai/intake-outcome-ledger.uai",
    ".uai/short-term-memory.uai",
    ".uai/long-term-memory.uai",
    ".uai/long-term-pointer-ledger.uai",
    ".uai/progress.uai",
]
FORBIDDEN_REFERENCES = [
    "docs/prompts",
    "enterprise-matm-memoryendpoints-goal",
    "uaix-agent-add-matm-wizard-guidance",
    "setup-llm-wiki",
    "Update URL: https://uaix.org",
]
SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----", re.I)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.I)),
    ("raw_memoryendpoints_key", re.compile(r"\bme_live_[A-Za-z0-9_-]{20,}\b")),
    ("credential_assignment", re.compile(r"\b(password|passwd|pwd|secret|api[_ -]?key|token)\b\s*[:=]\s*([^\s,;\"']{8,})", re.I)),
]


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def audit_file(path):
    text = read(path)
    missing = [field for field in REQUIRED_FIELDS if field not in text]
    forbidden = [needle for needle in FORBIDDEN_REFERENCES if needle in text]
    secret_hits = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            secret_hits.append(name)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "ok": not missing and not forbidden and not secret_hits,
        "missingRequiredFields": missing,
        "forbiddenReferences": forbidden,
        "secretHitCount": len(secret_hits),
        "secretRules": secret_hits,
        "valuesRedacted": True,
    }


def startup_read_order():
    startup = UAI_DIR / "startup-packet.uai"
    if not startup.exists():
        return []
    text = read(startup)
    lines = re.findall(r"^\s*\d+\.\s*(\.uai/[^\s]+)\s*$", text, re.M)
    return [line.strip() for line in lines]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    items = [audit_file(path) for path in sorted(UAI_DIR.glob("*.uai"))]
    required_names = {
        "constraints.uai",
        "file-handoff.uai",
        "intake-outcome-ledger.uai",
        "long-term-memory.uai",
        "long-term-pointer-ledger.uai",
        "progress.uai",
        "short-term-memory.uai",
        "startup-packet.uai",
        "totem.uai",
    }
    present_names = {Path(item["path"]).name for item in items}
    missing_files = sorted(required_names - present_names)
    unexpected_files = sorted(present_names - required_names)
    read_order = startup_read_order()
    read_order_matches = read_order == STARTUP_READ_ORDER
    bootstrap_path = UAI_DIR / "startup-packet.uai"
    bootstrap_text = read(bootstrap_path) if bootstrap_path.exists() else ""
    bootstrap_points_to_totem = ".uai/totem.uai" in bootstrap_text and "bootstrap" in bootstrap_text.lower()
    local_uai_stays_active = (UAI_DIR / "totem.uai").exists() and "Local `.uai` stays active always." in read(
        UAI_DIR / "totem.uai"
    )
    report = {
        "schemaVersion": "memoryendpoints.uai_memory_audit.v1",
        "ok": all(item["ok"] for item in items)
        and not missing_files
        and not unexpected_files
        and read_order_matches
        and bootstrap_points_to_totem
        and local_uai_stays_active,
        "bootstrapFile": BOOTSTRAP_FILE,
        "bootstrapFilePresent": bootstrap_path.exists(),
        "bootstrapPointsToTotem": bootstrap_points_to_totem,
        "fileCount": len(items),
        "missingFiles": missing_files,
        "unexpectedFiles": unexpected_files,
        "startupReadOrder": read_order,
        "expectedStartupReadOrder": STARTUP_READ_ORDER,
        "startupReadOrderMatchesExpected": read_order_matches,
        "startupReadOrderTotemFirst": bool(read_order and read_order[0] == ".uai/totem.uai"),
        "localUaiStaysActiveAlways": local_uai_stays_active,
        "items": items,
        "valuesRedacted": True,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
