#!/usr/bin/env python3
"""Per-user diagnostic wrapper for the unreleased managed-connection adapter."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryendpoints.managed_connection import main


if __name__ == "__main__":
    raise SystemExit(main())
