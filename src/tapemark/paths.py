"""Where data lives on disk.

Everything under ``data/`` is git-ignored and can be rebuilt from public sources.
Set the TAPEMARK_DATA environment variable to keep data somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TAPEMARK_DATA", ROOT / "data"))
RAW = DATA / "raw"      # files exactly as downloaded, never edited
CLEAN = DATA / "clean"  # tables derived from RAW, safe to delete and rebuild
