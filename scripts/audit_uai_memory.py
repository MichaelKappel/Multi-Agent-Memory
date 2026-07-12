import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UAI_DIR = ROOT / ".uai"
BOOTSTRAP_FILE = ".uai/startup-packet.uai"
FORBIDDEN_ACTIVE_MEMORY_FILENAMES = {
    "active-memory.uai",
    "current-state.uai",
    "project-state.uai",
    "short-term-memory.uai",
    "working-state.uai",
}
FORBIDDEN_ACTIVE_MEMORY_POLICY = (
    "The local .uai folder is the active startup memory suite; actual local files named "
    "short-term-memory.uai, current-state.uai, active-memory.uai, "
    "project-state.uai, or working-state.uai are forbidden. A protected virtual UAIX "
    "package for an accountless browser may represent its configuration-specific short-term-memory "
    "logical role in database records because it creates no local file."
)
REQUIRED_FIELDS = [
    "Purpose:",
    "Verification status:",
    "Memory scope:",
    "Public-safe status:",
    "Update route:",
    "Source of truth:",
    "Next action",
    "Must not expose:",
]
STARTUP_READ_ORDER = [
    ".uai/startup-packet.uai",
    ".uai/memory-maintenance.uai",
    ".uai/identity.uai",
    ".uai/world-context.uai",
    ".uai/totem.uai",
    ".uai/taboo.uai",
    ".uai/talisman.uai",
    ".uai/system-profile.uai",
    ".uai/receiver-brief.uai",
    ".uai/index.uai",
    ".uai/context.uai",
    ".uai/constraints.uai",
    ".uai/overview.uai",
    ".uai/stack.uai",
    ".uai/architecture.uai",
    ".uai/coding-standards.uai",
    ".uai/operations.uai",
    ".uai/test-plan.uai",
    ".uai/decisions.uai",
    ".uai/risk-register.uai",
    ".uai/owners.uai",
    ".uai/agent-instructions.uai",
    ".uai/agents/memoryendpoints-frontend-agent.uai",
    ".uai/agents/memoryendpoints-backend-agent.uai",
    ".uai/style.uai",
    ".uai/memory.uai",
    ".uai/file-handoff.uai",
    ".uai/intake-outcome-ledger.uai",
    ".uai/handoff-brief.uai",
    ".uai/long-term-memory.uai",
    ".uai/long-term-pointer-ledger.uai",
    ".uai/next-actions.uai",
    ".uai/next-recursive-prompt.uai",
    ".uai/open-questions.uai",
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
DATE_PATTERNS = [
    ("iso_date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("iso_timestamp", re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", re.I)),
    ("compact_calendar_date", re.compile(r"\b20\d{6}\b")),
]
HANDOFF_ACTIVE_BUCKETS = [
    ROOT / "agent-file-handoff" / "Content",
    ROOT / "agent-file-handoff" / "Improvement",
]
FORBIDDEN_HANDOFF_GUIDANCE_NAMES = {
    "README",
    "README.md",
    "STATUS",
    "STATUS.md",
    "COUNT",
    "COUNT.md",
    "INDEX",
    "INDEX.md",
}


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
    date_hits = []
    for name, pattern in DATE_PATTERNS:
        if pattern.search(text):
            date_hits.append(name)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "ok": not missing and not forbidden and not secret_hits and not date_hits,
        "missingRequiredFields": missing,
        "forbiddenReferences": forbidden,
        "dateFree": not date_hits,
        "dateHitCount": len(date_hits),
        "dateRules": date_hits,
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


def manifest_read_order():
    path = UAI_DIR / "exports" / "manifest.json"
    if not path.exists():
        return []
    try:
        return json.loads(read(path)).get("activeReadOrder") or []
    except ValueError:
        return []


def forbidden_active_memory_paths(paths):
    return sorted(
        path for path in paths if Path(path).name.lower() in FORBIDDEN_ACTIVE_MEMORY_FILENAMES
    )


def audit_handoff_buckets():
    items = []
    for bucket in HANDOFF_ACTIVE_BUCKETS:
        relative_bucket = str(bucket.relative_to(ROOT)).replace("\\", "/")
        if not bucket.exists():
            items.append(
                {
                    "bucket": relative_bucket,
                    "exists": False,
                    "activePayloadCount": 0,
                    "forbiddenGuidanceFiles": [],
                    "ok": False,
                }
            )
            continue
        active_payloads = []
        forbidden_guidance = []
        for path in sorted(bucket.iterdir()):
            if path.name == ".gitkeep":
                continue
            active_payloads.append(str(path.relative_to(ROOT)).replace("\\", "/"))
            if path.name in FORBIDDEN_HANDOFF_GUIDANCE_NAMES:
                forbidden_guidance.append(str(path.relative_to(ROOT)).replace("\\", "/"))
        items.append(
            {
                "bucket": relative_bucket,
                "exists": True,
                "activePayloadCount": len(active_payloads),
                "activePayloads": active_payloads,
                "forbiddenGuidanceFiles": forbidden_guidance,
                "ok": not active_payloads and not forbidden_guidance,
            }
        )
    return items


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    items = [audit_file(path) for path in sorted(UAI_DIR.rglob("*.uai"))]
    required_paths = set(STARTUP_READ_ORDER) | {
        ".uai/archives/changelog.uai",
        ".uai/exports/llms.uai",
        ".uai/exports/llms-full.uai",
    }
    required_support_paths = {
        "AGENTS.md",
        "workspace.uai",
        ".uai/readme.human",
        ".uai/exports/manifest.json",
        "reports/deployment-memory-and-test-report.uai",
    }
    present_paths = {item["path"] for item in items}
    missing_files = sorted(required_paths - present_paths)
    unexpected_files = sorted(present_paths - required_paths)
    forbidden_active_memory_files = forbidden_active_memory_paths(present_paths)
    missing_support_files = sorted(
        path for path in required_support_paths if not (ROOT / path).exists()
    )
    read_order = startup_read_order()
    manifest_order = manifest_read_order()
    read_order_matches = read_order == STARTUP_READ_ORDER
    manifest_read_order_matches = manifest_order == STARTUP_READ_ORDER
    manifest_forbidden_active_memory_files = forbidden_active_memory_paths(manifest_order)
    bootstrap_path = UAI_DIR / "startup-packet.uai"
    bootstrap_text = read(bootstrap_path) if bootstrap_path.exists() else ""
    bootstrap_points_to_totem = ".uai/totem.uai" in bootstrap_text and "bootstrap" in bootstrap_text.lower()
    handoff_items = audit_handoff_buckets()
    handoff_buckets_ready = all(item["ok"] for item in handoff_items)
    local_uai_stays_active = (UAI_DIR / "totem.uai").exists() and "Local `.uai` stays active always." in read(
        UAI_DIR / "totem.uai"
    )
    report = {
        "schemaVersion": "memoryendpoints.uai_memory_audit.v1",
        "ok": all(item["ok"] for item in items)
        and not missing_files
        and not missing_support_files
        and not unexpected_files
        and not forbidden_active_memory_files
        and read_order_matches
        and manifest_read_order_matches
        and not manifest_forbidden_active_memory_files
        and bootstrap_points_to_totem
        and local_uai_stays_active
        and handoff_buckets_ready,
        "bootstrapFile": BOOTSTRAP_FILE,
        "bootstrapFilePresent": bootstrap_path.exists(),
        "bootstrapPointsToTotem": bootstrap_points_to_totem,
        "fileCount": len(items),
        "missingFiles": missing_files,
        "missingSupportFiles": missing_support_files,
        "forbiddenActiveMemoryFileNames": sorted(FORBIDDEN_ACTIVE_MEMORY_FILENAMES),
        "forbiddenActiveMemoryPolicy": FORBIDDEN_ACTIVE_MEMORY_POLICY,
        "unexpectedFiles": unexpected_files,
        "forbiddenActiveMemoryFiles": forbidden_active_memory_files,
        "manifestForbiddenActiveMemoryFiles": manifest_forbidden_active_memory_files,
        "startupReadOrder": read_order,
        "expectedStartupReadOrder": STARTUP_READ_ORDER,
        "startupReadOrderMatchesExpected": read_order_matches,
        "manifestReadOrder": manifest_order,
        "manifestReadOrderMatchesExpected": manifest_read_order_matches,
        "startupReadOrderBootstrapFirst": bool(
            read_order and read_order[0] == BOOTSTRAP_FILE
        ),
        "anchorFilesPresent": all((UAI_DIR / name).exists() for name in ("totem.uai", "taboo.uai", "talisman.uai")),
        "localUaiStaysActiveAlways": local_uai_stays_active,
        "dateFreeHotMemory": all(item["dateFree"] for item in items),
        "noForbiddenActiveMemoryFilename": not forbidden_active_memory_files,
        "accountlessBrowserVirtualLogicalRoleCreatesLocalFile": False,
        "handoffBucketsReady": handoff_buckets_ready,
        "handoffBucketItems": handoff_items,
        "items": items,
        "valuesRedacted": True,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
