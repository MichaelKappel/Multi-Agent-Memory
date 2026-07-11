import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(url, attempts=5, retry_delay_seconds=2):
    last_error = None
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=20) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8", errors="replace"))
        except URLError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(retry_delay_seconds)
    raise last_error


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://memoryendpoints.com")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    status, payload = fetch_json(args.base_url.rstrip("/") + "/api/version")
    backend = (payload.get("storeBackend") or "").strip().lower()
    configured = (payload.get("configuredStoreBackend") or "").strip().lower()
    verified = bool(payload.get("storeBackendVerified"))
    report = {
        "schemaVersion": "memoryendpoints.mysql_backend_verifier.v1",
        "baseUrl": args.base_url.rstrip("/"),
        "httpStatus": status,
        "configuredStoreBackend": configured,
        "storeBackend": backend,
        "storeBackendVerified": verified,
        "mysqlBackendVerified": backend in ("mysql", "mariadb") and verified,
        "ok": status == 200 and backend in ("mysql", "mariadb") and verified,
        "sourceSha": (payload.get("build") or {}).get("sourceSha"),
        "valuesRedacted": True,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
