"""Daily submission cap (default 2 PRs/day, persisted on disk)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class DailyLimiter:
    def __init__(self, path: Path, cap: int = 2):
        self.path, self.cap = Path(path), max(0, min(cap, 2))

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            d = {}
        return d if d.get("day") == date.today().isoformat() else {"day": date.today().isoformat(), "count": 0}

    def remaining(self) -> int:
        return max(0, self.cap - self._load()["count"])

    def record(self) -> None:
        d = self._load()
        d["count"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d))
