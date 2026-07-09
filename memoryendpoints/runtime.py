import os


def configured_store_backend():
    return os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file"


def mysql_backend_name(backend):
    return backend in ("mysql", "mariadb")


def backend_requires_third_party_runtime(backend):
    return mysql_backend_name(backend)


def store_backend_health():
    configured = configured_store_backend()
    health = {
        "configuredStoreBackend": configured,
        "storeBackend": configured,
        "storeBackendVerified": False,
        "storeBackendStatus": "not_checked",
        "thirdPartyRuntimeDependencies": backend_requires_third_party_runtime(configured),
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
        health["errorType"] = exc.__class__.__name__
    return health
