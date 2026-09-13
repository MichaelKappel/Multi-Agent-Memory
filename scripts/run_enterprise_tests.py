"""Run the owned Multi-Agent-Memory test surface in a hermetic, auditable environment.

The default mode is deliberately local-only.  Tests whose filename identifies a
live, MySQL, or dogfood dependency are reported as a separate external set and
are only run with ``--mode full``.  This keeps a green local run from becoming
an accidental live-service claim.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "Multi-Agent-Memory"
SLUG = "matm"
SOURCE_PACKAGES = ("memoryendpoints",)
TEST_ROOTS = ("tests", "scripts")
EXTERNAL_MARKERS = ("live", "mysql", "dogfood")
HERMETIC_EXTERNAL_TEST_FILES = (
    "tests/test_mysql_store.py",
    "tests/test_commons_mysql.py",
)
NON_CRITICAL_SKIP_DETAILS = (
    "real MySQL Commons contract requires explicit opt-in",
)
REQUIRED_MODULES = {"pytest": "pytest", "coverage": "coverage"}
OPTIONAL_MODULES = {}
NODE_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "tests/browser_invite_redemption_contract.js": ("static/js/site.js",),
    "tests/connector_authorize_client_contract.js": ("static/js/connector-authorize.js",),
    "tests/contrast_contract.js": ("static/css/site.css",),
    "tests/human_access_ui_contract.js": ("static/js/human-access.js", "static/css/human-access.css"),
    "tests/human_operational_ui_contract.js": ("static/js/human-operational.js",),
    "tests/knowledge_ui_contract.js": ("static/js/knowledge.js",),
    "tests/mock_transport_contract.js": ("static/js/mock-transport.js", "static/js/site.js"),
    "tests/setup_ui_contract.js": ("static/js/site.js",),
    "tests/site_nav_contract.js": ("static/js/site.js",),
    "tests/strict_mock_transport_contract.js": ("static/js/mock-transport.js",),
}
STATEMENT_MINIMUM = 90.0
BRANCH_MINIMUM = 85.0
CRITICAL_MINIMUM = 100.0


def _safe_text(value: object, limit: int = 200_000) -> str:
    text = str(value or "")
    text = text.replace("synthetic-enterprise-test-pepper", "<synthetic-secret>")
    text = re.sub(r"(?i)(?:test-only|synthetic|fixture)[-_][A-Za-z0-9._-]+", "<synthetic>", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
    text = re.sub(
        r"(?i)(authorization|password|token|secret|credential|pepper)\s*[=:]\s*([^\s,;]+)",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"(?i)(https?://[^\s?]+)\?[^\s]+", r"\1?<redacted>", text)
    return text[:limit]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _is_external(path: Path) -> bool:
    name = path.name.lower()
    return any(marker in name for marker in EXTERNAL_MARKERS)


def _test_files(include_external: bool) -> list[Path]:
    files: list[Path] = []
    for relative_root in TEST_ROOTS:
        root = ROOT / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "runtime" in path.parts and "autonomy-test-deps" in path.parts:
                continue
            if not path.name.startswith("test") or (relative_root == "scripts" and not path.name.startswith("test_")):
                continue
            relative = str(path.relative_to(ROOT)).replace("\\", "/")
            if (
                include_external
                or not _is_external(path)
                or relative in HERMETIC_EXTERNAL_TEST_FILES
            ):
                files.append(path)
    return sorted(set(files))


def _node_files(include_external: bool) -> list[Path]:
    files: list[Path] = []
    for relative_root in TEST_ROOTS:
        root = ROOT / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*.js"):
            if "__pycache__" in path.parts:
                continue
            if (str(path.relative_to(ROOT)).replace("\\", "/") in NODE_ARGUMENTS
                    and (include_external or not _is_external(path))):
                files.append(path)
        for path in root.rglob("*.cjs"):
            if (str(path.relative_to(ROOT)).replace("\\", "/") in NODE_ARGUMENTS
                    and (include_external or not _is_external(path))):
                files.append(path)
    return sorted(set(files))


def _isolated_environment(temp_root: Path, support_root: Path, dependency_paths: list[str]) -> dict[str, str]:
    allowed = ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "PROGRAMFILES")
    environment = {name: os.environ[name] for name in allowed if os.environ.get(name)}
    home = temp_root / "home"
    data = temp_root / "data"
    home.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "0",
            "PYTHONUNBUFFERED": "1",
            "SOURCE_DATE_EPOCH": "315532800",
            "TZ": "UTC",
            "HOME": str(home),
            "USERPROFILE": str(home),
            "HOMEDRIVE": home.drive or "C:",
            "HOMEPATH": str(home).replace(home.drive or "C:", ""),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "PROGRAMDATA": str(temp_root / "ProgramData"),
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "TMPDIR": str(temp_root),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "PYTHONPATH": os.pathsep.join((str(support_root), str(ROOT), *dependency_paths)),
            "TEST_NETWORK_MODE": "hermetic",
            "TEST_NETWORK_LOG": str(temp_root / "network-attempts.log"),
            "MEMORYENDPOINTS_STORE_BACKEND": "sqlite",
            "MEMORYENDPOINTS_CREDENTIAL_PEPPER": "synthetic-enterprise-test-pepper",
            "MEMORYENDPOINTS_DATA_DIR": str(data),
            "MEMORYENDPOINTS_SQLITE_PATH": str(data / "memoryendpoints.sqlite3"),
            "MEMORYENDPOINTS_STORE_PATH": str(data / "memoryendpoints.json"),
            "MEMORYENDPOINTS_MCP_OAUTH_PATH": str(data / "oauth.sqlite3"),
            "CONCRESCA_ENVIRONMENT": "local-test",
            "CONCRESCA_ACTIVATION_STATE": "local-wip",
            "CONCRESCA_DATA_DIR": str(data),
        }
    )
    return environment


def _write_network_guard(support_root: Path) -> None:
    support_root.mkdir(parents=True, exist_ok=True)
    guard = r'''
import os
import socket

_original_connect = socket.socket.connect
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo
_log_path = os.environ.get("TEST_NETWORK_LOG")
_local_names = {"localhost", socket.gethostname().lower()}

def _local(host):
    return host in (None, "") or str(host).strip("[]").lower() in _local_names | {"127.0.0.1", "::1"}

def _record(host):
    if _log_path:
        with open(_log_path, "a", encoding="utf-8") as handle:
            handle.write(str(host) + "\n")

def _guard(host):
    if not _local(host):
        _record(host)
        raise OSError("hermetic network access denied")

def _connect(self, address):
    if isinstance(address, tuple) and address:
        _guard(address[0])
    return _original_connect(self, address)

def _create_connection(address, *args, **kwargs):
    if isinstance(address, tuple) and address:
        _guard(address[0])
    return _original_create_connection(address, *args, **kwargs)

def _getaddrinfo(host, *args, **kwargs):
    _guard(host)
    return _original_getaddrinfo(host, *args, **kwargs)

socket.socket.connect = _connect
socket.create_connection = _create_connection
socket.getaddrinfo = _getaddrinfo
'''
    (support_root / "sitecustomize.py").write_text(guard, encoding="utf-8")


def _parse_junit(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if not path.exists():
        return failures, skipped
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return [{"test": "junit", "detail": "junit_parse_failed"}], skipped
    for case in root.iter("testcase"):
        test = f"{case.attrib.get('classname', '')}.{case.attrib.get('name', '')}".strip(".")
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is not None:
            failures.append({"test": test, "detail": _safe_text(failure.text or failure.attrib.get("message", ""))})
        skip = case.find("skipped")
        if skip is not None:
            skipped.append({"test": test, "detail": _safe_text(skip.attrib.get("message", "skipped"))})
    try:
        tree = ET.parse(path)
        for element in tree.getroot().iter():
            if element.text:
                element.text = _safe_text(element.text)
            for key, value in list(element.attrib.items()):
                element.attrib[key] = _safe_text(value, 4_000)
        tree.write(path, encoding="utf-8", xml_declaration=True)
    except (OSError, ET.ParseError):
        path.write_text("<testsuite name=\"enterprise\" tests=\"0\" errors=\"1\"><error>junit_sanitize_failed</error></testsuite>\n", encoding="utf-8")
    return failures, skipped


def _classify_failure(detail: str) -> str:
    lowered = detail.lower()
    if any(marker in lowered for marker in ("modulenotfounderror", "importerror", "required_dependency", "node-preflight")):
        return "dependency"
    if any(marker in lowered for marker in ("winerror 206", "permissionerror", "access is denied", "path too long", "network access denied")):
        return "environment"
    if any(marker in lowered for marker in ("junit_parse_failed", "junit_sanitize_failed", "timeoutexpired")):
        return "runner"
    return "test_or_product"


def _coverage_summary(coverage_path: Path, artifacts: Path) -> dict[str, object]:
    command = [sys.executable, "-m", "coverage", "json", "--data-file", str(coverage_path), "-o", str(artifacts / "coverage.json")]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120, shell=False)
    if result.returncode != 0 or not (artifacts / "coverage.json").exists():
        return {"available": False, "error": _safe_text(result.stderr or result.stdout or "coverage_json_failed")}
    try:
        document = json.loads((artifacts / "coverage.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "error": "coverage_json_unreadable"}
    totals = document.get("totals", {})
    covered_lines = int(totals.get("covered_lines", 0))
    statements = int(totals.get("num_statements", 0))
    covered_branches = int(totals.get("covered_branches", 0))
    branches = int(totals.get("num_branches", 0))
    statement_percent = (covered_lines / statements * 100) if statements else 0.0
    branch_percent = (covered_branches / branches * 100) if branches else 100.0
    capability_rows: dict[str, dict[str, int]] = {}
    for filename, details in document.get("files", {}).items():
        lower = filename.lower()
        if any(word in lower for word in ("credential", "auth", "security", "privacy", "secret")):
            capability = "identity_security"
        elif any(word in lower for word in ("memory", "knowledge", "correction", "withdrawal")):
            capability = "memory_knowledge_correction"
        elif any(word in lower for word in ("mcp", "connector", "commons", "room", "message")):
            capability = "coordination_connectors"
        elif any(word in lower for word in ("database", "schema", "migration", "storage", "mysql")):
            capability = "persistence_migration"
        elif any(word in lower for word in ("recovery", "reconcile", "reconciliation", "rotation", "revocation", "replay", "renewal", "rollback", "non_resurrection", "lifecycle")):
            capability = "recovery_lifecycle"
        else:
            capability = "public_runtime"
        row = capability_rows.setdefault(capability, {"covered": 0, "statements": 0, "branchesCovered": 0, "branches": 0})
        summary = details.get("summary", {})
        row["covered"] += int(summary.get("covered_lines", 0))
        row["statements"] += int(summary.get("num_statements", 0))
        row["branchesCovered"] += int(summary.get("covered_branches", 0))
        row["branches"] += int(summary.get("num_branches", 0))
    for critical_capability in ("identity_security", "recovery_lifecycle"):
        capability_rows.setdefault(critical_capability, {"covered": 0, "statements": 0, "branchesCovered": 0, "branches": 0})
    capabilities = {}
    for name, row in capability_rows.items():
        capabilities[name] = {
            **row,
            "statementPercent": round(row["covered"] / row["statements"] * 100, 2) if row["statements"] else 0.0,
            "branchPercent": round(row["branchesCovered"] / row["branches"] * 100, 2) if row["branches"] else 100.0,
        }
    return {
        "available": True,
        "statementPercent": round(statement_percent, 2),
        "branchPercent": round(branch_percent, 2),
        "coveredLines": covered_lines,
        "statements": statements,
        "coveredBranches": covered_branches,
        "branches": branches,
        "capabilities": capabilities,
    }


def _run_node(files: list[Path], environment: dict[str, str], artifacts: Path) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if not files:
        return failures
    node = shutil.which("node")
    if not node:
        return [{"test": "node-preflight", "detail": "required_node_runtime_missing"}]
    results = []
    for path in files:
        try:
            relative = str(path.relative_to(ROOT)).replace("\\", "/")
            completed = subprocess.run([node, str(path), *NODE_ARGUMENTS.get(relative, ())], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180, shell=False)
            row = {"test": str(path.relative_to(ROOT)), "exitCode": str(completed.returncode), "output": _safe_text(completed.stdout + completed.stderr)}
            results.append(row)
            if completed.returncode:
                failures.append({"test": row["test"], "detail": row["output"]})
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append({"test": str(path.relative_to(ROOT)), "detail": _safe_text(error)})
    _write_json(artifacts / "node-tests.json", results)
    return failures


def run(mode: str, artifacts: Path, temp_root: Path) -> int:
    artifacts.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    include_external = mode == "full"
    test_files = _test_files(include_external)
    node_files = _node_files(include_external)
    missing = [name for name, module in REQUIRED_MODULES.items() if not _module_available(module)]
    optional_missing = [name for name, module in OPTIONAL_MODULES.items() if not _module_available(module)]
    dependency_paths = []
    for module in (*REQUIRED_MODULES.values(), *OPTIONAL_MODULES.values()):
        spec = importlib.util.find_spec(module)
        origin = getattr(spec, "origin", None) if spec else None
        if origin and origin not in {"built-in", "frozen"}:
            candidate = Path(origin).resolve().parent
            while candidate != candidate.parent:
                if candidate.name.lower() in {"site-packages", "dist-packages"}:
                    dependency_paths.append(str(candidate))
                    break
                candidate = candidate.parent
    dependency_paths = sorted(set(dependency_paths))
    environment_diagnostic = {
        "project": PROJECT,
        "mode": mode,
        "hermetic": mode != "full",
        "parentEnvironmentValuesUsed": ["PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "PROGRAMFILES"],
        "syntheticCredentials": True,
        "networkPolicy": "loopback_only" if mode != "full" else "external_allowed_by_test_selection",
        "testFiles": [str(path.relative_to(ROOT)) for path in test_files],
        "hermeticExternalTestFiles": list(HERMETIC_EXTERNAL_TEST_FILES),
        "nodeFiles": [str(path.relative_to(ROOT)) for path in node_files],
        "missingRequiredModules": missing,
        "missingOptionalModules": optional_missing,
        "dependencyLocations": [Path(path).name for path in dependency_paths],
    }
    _write_json(artifacts / "environment.json", environment_diagnostic)
    if missing:
        report = {"schema": "enterprise-test-report.v1", "status": "blocked", "blocker": "missing_required_dependency", "missing": missing, "valuesRedacted": True}
        _write_json(artifacts / "report.json", report)
        return 2
    temp_root_cleaned = False
    with tempfile.TemporaryDirectory(prefix=f"{SLUG}-", dir=str(temp_root)) as temporary:
        isolated = Path(temporary)
        support = isolated / "support"
        _write_network_guard(support)
        environment = _isolated_environment(isolated, support, dependency_paths)
        coverage_path = artifacts / ".coverage"
        junit_path = artifacts / "junit.xml"
        command = [sys.executable, "-m", "coverage", "run", "--branch", "--source", ",".join(SOURCE_PACKAGES), "--data-file", str(coverage_path), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml", str(junit_path)] + [str(path) for path in test_files]
        started = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=1800, shell=False)
            test_exit = completed.returncode
            output = _safe_text(completed.stdout + completed.stderr)
        except subprocess.TimeoutExpired as error:
            test_exit = 124
            output = _safe_text(error)
        (artifacts / "pytest-output.log").write_text(output, encoding="utf-8")
        failures, skipped = _parse_junit(junit_path)
        node_failures = _run_node(node_files, environment, artifacts)
        failures.extend(node_failures)
        network_log = isolated / "network-attempts.log"
        network_attempts = network_log.read_text(encoding="utf-8", errors="replace").splitlines() if network_log.exists() else []
    temp_root_cleaned = not isolated.exists()
    for failure in failures:
        failure["classification"] = _classify_failure(failure.get("detail", ""))
    coverage = _coverage_summary(coverage_path, artifacts) if coverage_path.exists() else {"available": False, "error": "coverage_data_missing"}
    critical_skips = [
        row
        for row in skipped
        if re.search(r"auth|credential|security|persist|recover|isolation|idempot|correction|withdrawal", row["test"], re.I)
        and not any(detail in row.get("detail", "") for detail in NON_CRITICAL_SKIP_DETAILS)
    ]
    threshold_failures = []
    if not coverage.get("available"):
        threshold_failures.append("coverage_unavailable")
    else:
        if float(coverage["statementPercent"]) < STATEMENT_MINIMUM:
            threshold_failures.append("statement_coverage_below_90")
        if float(coverage["branchPercent"]) < BRANCH_MINIMUM:
            threshold_failures.append("branch_coverage_below_85")
        for capability, row in coverage.get("capabilities", {}).items():
            if capability in {"identity_security", "recovery_lifecycle"} and int(row.get("statements", 0)) > 0 and float(row["statementPercent"]) < CRITICAL_MINIMUM:
                threshold_failures.append(f"critical_capability_below_100:{capability}")
    report = {
        "schema": "enterprise-test-report.v1",
        "project": PROJECT,
        "mode": mode,
        "status": "pass" if test_exit == 0 and not failures and not critical_skips and not threshold_failures and not network_attempts else "fail",
        "exitCode": test_exit,
        "durationSeconds": round(time.monotonic() - started, 3),
        "tests": {"pythonFiles": len(test_files), "nodeFiles": len(node_files), "failures": len(failures), "skipped": len(skipped), "criticalSkips": len(critical_skips)},
        "coverage": coverage,
        "failures": failures,
        "failureClassCounts": {name: sum(1 for row in failures if row.get("classification") == name) for name in ("dependency", "environment", "runner", "test_or_product")},
        "skipped": skipped,
        "criticalSkips": critical_skips,
        "thresholdFailures": threshold_failures,
        "networkAttempts": len(network_attempts),
        "temporaryRootCleaned": temp_root_cleaned,
        "valuesRedacted": True,
    }
    _write_json(artifacts / "failures.json", failures)
    _write_json(artifacts / "skipped.json", skipped)
    _write_json(artifacts / "report.json", report)
    return 0 if report["status"] == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("hermetic", "full"), default="hermetic")
    parser.add_argument("--artifacts", type=Path, default=Path(tempfile.gettempdir()) / "enterprise-test-artifacts" / SLUG)
    parser.add_argument("--temp-root", type=Path, default=None)
    args = parser.parse_args(argv)
    temp_root = args.temp_root or (Path(tempfile.gettempdir()) / "ent-tmp" / SLUG)
    return run(args.mode, args.artifacts.resolve(), temp_root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
