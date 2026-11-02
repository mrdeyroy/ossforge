"""Persistent work queue. Status flow:
found -> clean (no duplicates) -> verified (confirmed by reading + failing test + patch) -> submitted
Also: duplicate, rejected, anti_ai.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATUSES = {"found", "clean", "duplicate", "verified", "submitted", "rejected", "anti_ai"}


@dataclass
class Item:
    id: str
    repo: str
    path: str
    line: int
    kind: str
    detail: str
    status: str = "found"
    notes: list[str] = field(default_factory=list)
    clone: str = ""
    branch: str = ""
    issue_title: str = ""
    issue_body: str = ""
    pr_title: str = ""
    pr_body: str = ""
    consent_issue: int = 0  # existing upstream issue with explicit maintainer approval label
    verification: dict = field(default_factory=dict)  # exact tested tree/base/branch and commands
    submitted: dict = field(default_factory=dict)  # partial progress lives here (issue_url, fork_pushed, pr_url)
    work: str = "fix"  # fix | feature
    rank: float = 0.0
    snippet: str = ""  # a few lines around the finding so a human can accept or reject it quickly


class Queue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, Item] = {}
        try:
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                self.items[d["id"]] = Item(**d)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(i) for i in self.items.values()], indent=1), encoding="utf-8")

    def add(self, item: Item) -> bool:
        if item.id in self.items:
            return False
        self.items[item.id] = item
        return True

    def by_status(self, status: str) -> list[Item]:
        return [i for i in self.items.values() if i.status == status]

    def set(self, id_: str, **kw) -> Item:
        it = self.items[id_]
        for k, v in kw.items():
            setattr(it, k, v)
        return it


def item_id(repo: str, path: str, kind: str, line: int) -> str:
    return f"{repo}:{path}:{kind}:{line}"
