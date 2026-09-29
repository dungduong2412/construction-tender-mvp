"""Small local JSON stores for governed master/formula workflow state.

The checked-in evidence remains immutable.  Only review decisions, project-scoped
overrides and formula proposals are written under ``runtime/``.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.getenv("GOVERNANCE_RUNTIME_DIR", ROOT / "runtime" / "governance"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(name: str, default: Any) -> Any:
    path = RUNTIME_DIR / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(name: str, payload: Any) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_DIR / name
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
