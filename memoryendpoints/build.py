import json
import os

from .config import ROOT


BUILD_INFO_PATH = ROOT / "memoryendpoints" / "build_info.generated.json"


def _safe_build_info(data):
    source_sha = str(data.get("sourceSha") or data.get("source_sha") or os.environ.get("MEMORYENDPOINTS_SOURCE_SHA") or "unknown")
    source_sha_short = str(data.get("sourceShaShort") or data.get("source_sha_short") or source_sha[:12])
    return {
        "schemaVersion": "memoryendpoints.build_info.v1",
        "sourceSha": source_sha,
        "sourceShaShort": source_sha_short,
        "sourceRepository": "https://github.com/MichaelKappel/Multi-Agent-Memory",
        "generatedAt": data.get("generatedAt"),
        "generatedBy": data.get("generatedBy") or "runtime_fallback",
        "valuesRedacted": True,
    }


def build_provenance():
    if BUILD_INFO_PATH.exists():
        try:
            return _safe_build_info(json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return _safe_build_info({"generatedBy": "runtime_fallback_unreadable"})
    return _safe_build_info({"generatedBy": "runtime_fallback_missing"})
