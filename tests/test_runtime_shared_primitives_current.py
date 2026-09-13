"""Shared current coverage for the identical runtime backend health helpers."""

import os
import unittest
from unittest.mock import patch

from memoryendpoints import runtime


class SharedRuntimePrimitivesCurrentTests(unittest.TestCase):
    def test_backend_error_classification_covers_specific_and_fallback_errors(self):
        self.assertEqual(
            "mysql_driver_missing",
            runtime.backend_error_code("mysql", ImportError("driver unavailable")),
        )
        self.assertEqual(
            "mysql_unavailable",
            runtime.backend_error_code("mysql", RuntimeError("unclassified failure")),
        )
        self.assertEqual(
            "backend_unavailable",
            runtime.backend_error_code("sqlite", RuntimeError("unclassified failure")),
        )

    def test_successful_mysql_and_file_health_are_mocked_and_redacted(self):
        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_STORE_BACKEND": "mysql"},
            clear=False,
        ), patch("memoryendpoints.storage.MySQLStore") as mysql_store:
            mysql_store.return_value.healthcheck.return_value = None
            health = runtime.store_backend_health()
        self.assertEqual("mysql", health["configuredStoreBackend"])
        self.assertEqual("connected", health["storeBackendStatus"])
        self.assertTrue(health["storeBackendVerified"])
        self.assertTrue(health["valuesRedacted"])

        with patch.dict(
            os.environ,
            {"MEMORYENDPOINTS_STORE_BACKEND": "file"},
            clear=False,
        ), patch("memoryendpoints.storage.FileStore") as file_store:
            file_store.return_value.healthcheck.return_value = None
            health = runtime.store_backend_health()
        self.assertEqual("file", health["storeBackend"])
        self.assertEqual("available", health["storeBackendStatus"])
        self.assertTrue(health["storeBackendVerified"])
        self.assertTrue(health["valuesRedacted"])


if __name__ == "__main__":
    unittest.main()

