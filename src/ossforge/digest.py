"""Daily markdown digest of what was scouted, queued, skipped and submitted."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from . import safety
from .patrol import Action
from .queue import Queue


def render(q: Queue, audit: safety.Audit, actions: list[Action], notes: list[str] | None = None) -> str:
    day = time.strftime("%Y-%m-%d")
    counts = Counter(i.status for i in q.items.values())
    today = [r for r in audit.read() if time.strftime("%Y-%m-%d", time.localtime(r["ts"])) == day]
    lines = [f"# ossforge digest {day}", "", "## Queue", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(counts.items())] or ["- empty"]
    lines += ["", "## Submitted today", ""]
    opened = [r for r in today if r["event"] in ("issue_opened", "pr_opened")]
    lines += [f"- {r['event']}: {r['url']}" for r in opened] or ["- nothing"]
    lines += ["", "## Needs your attention", ""]
    todo = [a for a in actions if a.kind not in ("idle", "merged", "closed")]
    lines += [f"- {a.repo}#{a.pr} [{a.kind}] {a.detail}" for a in todo] or ["- nothing"]
    skipped = [i for i in q.items.values() if i.status in ("anti_ai", "duplicate")]
    lines += ["", "## Skipped (policy / duplicate)", ""]
    lines += [f"- {i.repo} {i.path}:{i.line} [{i.status}] {'; '.join(i.notes[:1])}" for i in skipped[:20]] or ["- none"]
    if notes:
        lines += ["", "## Run notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
