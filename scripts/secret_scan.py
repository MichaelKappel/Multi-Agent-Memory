import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from package_memoryendpoints import iter_files


SECRET_RULES = [
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("bearer_token_literal", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{24,}")),
    ("jwt_literal", re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")),
    ("secret_assignment", re.compile(r"(?i)\b(?:password|passwd|pwd|ftp_pass|db_pass|secret|api[_-]?key|token)\b\s*[:=]\s*[\"'][A-Za-z0-9_./+=~$-]{16,}[\"']")),
    ("dsn_with_inline_secret", re.compile(r"(?i)\b(?:mysql|mariadb|postgres|ftp|ftps)://[^:\s]+:[^@\s]+@")),
]

FORBIDDEN_INCLUDED_NAMES = {"ftp_Deploy.txt", ".env"}

ALLOWED_TEST_FIXTURES = (
    ("tests/test_connector_rate_limits.py", "secret_assignment", "private-secret-must-not-persist"),
    ("tests/test_connector_rate_limits.py", "secret_assignment", "one-time-code-value-must-not-persist"),
    ("tests/test_governed_security.py", "bearer_token_literal", "me_live_legacyworkspacekey"),
    ("tests/test_governed_security.py", "bearer_token_literal", "me_invite_v1.invite-record."),
    ("tests/test_governed_security.py", "secret_assignment", "private-agent-secret-value"),
)


def text_lines(path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []


def allowed_fixture(rel_text, rule_name, line):
    return any(
        rel_text == allowed_path and rule_name == allowed_rule and marker in line
        for allowed_path, allowed_rule, marker in ALLOWED_TEST_FIXTURES
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    hits = []
    scanned = 0
    paths = list(iter_files())
    seen = {str(rel).replace("\\", "/") for _path, rel in paths}
    for path in sorted((ROOT / ".uai").glob("*.uai")):
        rel = path.relative_to(ROOT)
        rel_text = str(rel).replace("\\", "/")
        if rel_text not in seen:
            paths.append((path, rel))
            seen.add(rel_text)
    for path, rel in paths:
        scanned += 1
        rel_text = str(rel).replace("\\", "/")
        if path.name in FORBIDDEN_INCLUDED_NAMES:
            hits.append({"file": rel_text, "line": 0, "rule": "forbidden_included_name"})
            continue
        for number, line in enumerate(text_lines(path), 1):
            for rule_name, pattern in SECRET_RULES:
                if pattern.search(line) and not allowed_fixture(rel_text, rule_name, line):
                    hits.append({"file": rel_text, "line": number, "rule": rule_name})

    report = {
        "schemaVersion": "memoryendpoints.secret_scan.v1",
        "ok": not hits,
        "scannedFileCount": scanned,
        "hitCount": len(hits),
        "hits": hits,
        "valuesRedacted": True,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
