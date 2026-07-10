import json


def json_bytes(data):
    return json.dumps(data, indent=2, sort_keys=True).encode("utf-8")


def response(start_response, status, body, content_type="application/json; charset=utf-8", headers=None):
    if isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = body
    extra_headers = list(headers or [])
    supplied = {key.lower() for key, _value in extra_headers}
    out_headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(raw))),
        ("X-Content-Type-Options", "nosniff"),
    ]
    if "cache-control" not in supplied:
        out_headers.append(("Cache-Control", "no-store" if status.startswith(("4", "5")) else "public, max-age=60"))
    out_headers.extend(extra_headers)
    start_response(status, out_headers)
    return [raw]


def json_response(start_response, data, status="200 OK", headers=None):
    headers = list(headers or [])
    if not any(key.lower() == "cache-control" for key, _value in headers):
        headers.append(("Cache-Control", "no-store"))
    return response(start_response, status, json_bytes(data), "application/json; charset=utf-8", headers)


def problem(start_response, status, title, detail, code):
    return json_response(
        start_response,
        {
            "ok": False,
            "safeNoOp": True,
            "valuesRedacted": True,
            "rawCredentialExposed": False,
            "rawPayloadExposed": False,
            "error": {
                "code": code,
                "title": title,
                "detail": detail,
                "safeNoOp": True,
                "valuesRedacted": True,
            },
        },
        status,
    )
