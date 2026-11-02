"""Daily submission cap (default 2 PRs/day, persisted on disk)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path


class InvalidState(ValueError):
    """Unknown spending of the PR allowance, never permission to reset it."""


class DailyLimiter:
    def __init__(self, path: Path, cap: int = 2):
        self.path, self.cap = Path(path), max(0, min(cap, 2))

    def _load(self) -> dict:
        today = date.today().isoformat()
        try:
            d = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"day": today, "count": 0}
        except (OSError, ValueError) as exc:
            raise InvalidState("daily PR ledger unreadable; recover it before publishing") from exc
        if not isinstance(d, dict) or not isinstance(d.get("day"), str) or type(d.get("count")) is not int or d["count"] < 0:
            raise InvalidState("daily PR ledger invalid; recover it before publishing")
        try:
            stored = date.fromisoformat(d["day"])
        except ValueError as exc:
            raise InvalidState("daily PR ledger has invalid date") from exc
        if stored > date.today():
            raise InvalidState("daily PR ledger is from a future date; inspect the host clock/state")
        # fromisoformat also accepts compact/week dates on supported runtimes.
        # Compare parsed days, not spellings: an alias for today is no rollover.
        return {"day": today, "count": d["count"] if stored == date.today() else 0}

    def remaining(self) -> int:
        return max(0, self.cap - self._load()["count"])

    def record(self) -> None:
        d = self._load()
        d["count"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=self.path.name + ".", delete=False) as out:
                temp = Path(out.name)
                json.dump(d, out)
                out.flush()
                os.fsync(out.fileno())
            temp.replace(self.path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
