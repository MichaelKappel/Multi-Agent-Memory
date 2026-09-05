import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.enterprise_readiness_audit import (
    isolated_readiness_environment,
    run_content_free_process,
)


ISOLATED_TEST_PATH_ENVIRONMENT = (
    "ALLUSERSPROFILE",
    "APPDATA",
    "HOME",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "MEMORYENDPOINTS_DATA_DIR",
    "MEMORYENDPOINTS_SQLITE_PATH",
    "MEMORYENDPOINTS_STORE_PATH",
    "MEMORYENDPOINTS_MCP_OAUTH_PATH",
    "MEMORYENDPOINTS_CREDENTIAL_CONFIG_PATH",
    "MEMORYENDPOINTS_MCP_HOST_CONFIG_PATH",
    "MEMORYENDPOINTS_MYSQL_CONFIG_PATH",
    "MEMORYENDPOINTS_ADMIN_DIAGNOSTICS_PATH",
)


def _is_within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


def validate_isolated_test_environment(environment, isolation_root, repository_root=ROOT):
    if environment.get("MEMORYENDPOINTS_STORE_BACKEND") != "sqlite":
        raise RuntimeError("unsafe_test_store_backend")
    for name in ISOLATED_TEST_PATH_ENVIRONMENT:
        value = environment.get(name)
        if not value:
            raise RuntimeError("missing_isolated_test_path")
        candidate = Path(value)
        if not candidate.is_absolute():
            raise RuntimeError("relative_isolated_test_path")
        if not _is_within(candidate, isolation_root):
            raise RuntimeError("unsafe_test_store_path")
        if _is_within(candidate, repository_root):
            raise RuntimeError("repository_test_store_path")
    combined_home = Path(
        str(environment.get("HOMEDRIVE") or "")
        + str(environment.get("HOMEPATH") or "")
    )
    if not combined_home.is_absolute() or not _is_within(combined_home, isolation_root):
        raise RuntimeError("unsafe_test_home_path")
    return True


def run_isolated_unittest(arguments=None, base_environment=None):
    unittest_arguments = list(arguments or ("discover", "-s", "tests"))
    with tempfile.TemporaryDirectory(prefix="memoryendpoints-suite-") as temporary:
        environment = isolated_readiness_environment(
            temporary,
            base_environment=base_environment,
        )
        validate_isolated_test_environment(environment, temporary)
        returncode, diagnostics = run_content_free_process(
            [sys.executable, "-m", "unittest"] + unittest_arguments,
            cwd=str(ROOT),
            environment=environment,
        )
        return returncode, diagnostics


def main(argv=None):
    returncode, diagnostics = run_isolated_unittest(
        list(sys.argv[1:] if argv is None else argv)
    )
    print(
        json.dumps(
            {
                "schemaVersion": "memoryendpoints.isolated_test_result.v1",
                "ok": returncode == 0,
                "exitCode": returncode,
                "output": diagnostics,
                "valuesRedacted": True,
            },
            sort_keys=True,
        )
    )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
