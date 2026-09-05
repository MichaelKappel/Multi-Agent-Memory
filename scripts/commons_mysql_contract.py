#!/usr/bin/env python3
"""Run the destructive Commons contract only against an acknowledged test DB."""

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get("MEMORYENDPOINTS_COMMONS_MYSQL_TEST") != "1":
        print("BLOCKED: set MEMORYENDPOINTS_COMMONS_MYSQL_TEST=1 for the isolated test database.")
        return 2
    if (
        os.environ.get("MEMORYENDPOINTS_COMMONS_MYSQL_TEST_ALLOW_MUTATION")
        != "isolated-disposable-database"
    ):
        print(
            "BLOCKED: explicit isolated-disposable-database mutation acknowledgement is required."
        )
        return 2
    if not os.environ.get("MEMORYENDPOINTS_COMMONS_MYSQL_TEST_DATABASE_SHA256"):
        print("BLOCKED: the exact isolated database-name fingerprint is required.")
        return 2

    suite = unittest.defaultTestLoader.loadTestsFromName(
        "tests.test_commons_mysql.CommonsMySQLContractTests"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print("BLOCKED: real MySQL Commons coverage was skipped.")
        return 2
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
