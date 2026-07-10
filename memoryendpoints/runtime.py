import os
from pathlib import Path

from .config import ROOT


def configured_store_backend():
    configured = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND")
    if configured and configured.strip():
        return configured.strip().lower()
    if mysql_secret_config_path().exists():
        return "mysql"
    return "file"


def mysql_secret_config_path():
    configured = os.environ.get("MEMORYENDPOINTS_MYSQL_CONFIG_PATH")
    return Path(configured) if configured else ROOT / ".local-secrets" / "mysql.json"


def mysql_backend_name(backend):
    return backend in ("mysql", "mariadb")


def host_provided_runtime_adapters(backend):
    if not mysql_backend_name(backend):
        return []
    return [
        {
            "name": "mysql_python_driver",
            "source": "host_environment",
            "packagedWithRepository": False,
            "requiredWhen": "MEMORYENDPOINTS_STORE_BACKEND=mysql",
        }
    ]


def backend_error_code(backend, exc):
    if not mysql_backend_name(backend):
        return "backend_unavailable"
    message = str(exc).lower()
    error_type = exc.__class__.__name__.lower()
    if "required database settings are missing" in message:
        return "mysql_missing_settings"
    if "no mysql python driver" in message or "importerror" in error_type:
        return "mysql_driver_missing"
    if "access denied" in message or "authentication" in message:
        return "mysql_auth_failed"
    if "unknown database" in message or "does not exist" in message:
        return "mysql_database_missing"
    if "can't connect" in message or "cannot connect" in message or "connection" in error_type or "operational" in error_type:
        return "mysql_connection_failed"
    if "syntax" in message or "schema" in message or "programming" in error_type:
        return "mysql_schema_init_failed"
    return "mysql_unavailable"


def store_backend_health():
    configured = configured_store_backend()
    health = {
        "configuredStoreBackend": configured,
        "storeBackend": configured,
        "storeBackendVerified": False,
        "storeBackendStatus": "not_checked",
        "thirdPartyRuntimeDependencies": False,
        "packageManagedThirdPartyRuntimeDependencies": False,
        "hostProvidedRuntimeAdapters": host_provided_runtime_adapters(configured),
        "valuesRedacted": True,
    }
    try:
        if mysql_backend_name(configured):
            from .storage import MySQLStore

            MySQLStore().healthcheck()
            health["storeBackendStatus"] = "connected"
            health["storeBackendVerified"] = True
        elif configured == "sqlite":
            from .storage import SQLiteStore

            SQLiteStore().healthcheck()
            health["storeBackendStatus"] = "connected"
            health["storeBackendVerified"] = True
        else:
            from .storage import FileStore

            FileStore().healthcheck()
            health["storeBackend"] = "file"
            health["storeBackendStatus"] = "available"
            health["storeBackendVerified"] = True
    except Exception as exc:
        health["storeBackend"] = "%s_unavailable" % configured
        health["storeBackendStatus"] = "unavailable"
        health["storeBackendVerified"] = False
        health["errorCode"] = backend_error_code(configured, exc)
        health["errorType"] = exc.__class__.__name__
    return health
