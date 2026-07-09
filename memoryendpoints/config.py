import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_NAME = "MemoryEndpoints.com"
SITE_URL = os.environ.get("MEMORYENDPOINTS_SITE_URL", "https://memoryendpoints.com")
DATA_DIR = Path(os.environ.get("MEMORYENDPOINTS_DATA_DIR", str(ROOT / "var")))
DOCS_DIR = Path(os.environ.get("MEMORYENDPOINTS_DOCS_DIR", str(ROOT / "docs")))
STORE_PATH = Path(os.environ.get("MEMORYENDPOINTS_STORE_PATH", str(DATA_DIR / "matm_store.json")))
SQLITE_PATH = Path(os.environ.get("MEMORYENDPOINTS_SQLITE_PATH", str(DATA_DIR / "matm_store.sqlite3")))
STORE_BACKEND = os.environ.get("MEMORYENDPOINTS_STORE_BACKEND", "file").strip().lower() or "file"
PUBLIC_STORAGE_BYTES = 200 * 1024 * 1024


def utc_now():
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
