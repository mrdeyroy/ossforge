"""Explicit local issue-review decisions, invalidated by changed upstream activity."""

from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(path: Path, repo: str, number: int, updated_at: str, reason: str) -> None:
    if not reason.strip() or not updated_at:
        raise ValueError("a reason and upstream updated_at are required")
    data = load(path)
    data[f"{repo.lower()}#{number}"] = {"updated_at": updated_at, "reason": reason.strip()}
    _save(path, data)


def reconsider(path: Path, repo: str, number: int) -> None:
    data = load(path)
    data.pop(f"{repo.lower()}#{number}", None)
    _save(path, data)


def unchanged_reason(data: dict, repo: str, number: int, updated_at: str | None) -> str:
    item = data.get(f"{repo.lower()}#{number}")
    if isinstance(item, dict) and updated_at and item.get("updated_at") == updated_at:
        return item.get("reason", "")
    return ""


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
