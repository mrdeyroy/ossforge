"""Whole-repo hunt: clone, honour policy, scan (builtin + ruff + JS), rank, drop duplicates, enqueue."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import audit as audit_mod
from . import dedupe, external, policy
from .config import Config
from .outcomes import Stats, rank
from .queue import Item, Queue, item_id

TOP_PER_REPO = 8


def clone(cfg: Config, repo: str) -> Path:
    dest = Path(cfg.work_dir) / repo.replace("/", "__")
    if not dest.exists():
        subprocess.run(["git", "clone", "--depth", "50", f"https://github.com/{repo}", str(dest)],
                       check=True, capture_output=True)
    return dest


def policy_of(dest: Path) -> policy.PolicyResult:
    files = {p: (dest / p).read_text(encoding="utf-8", errors="replace")
             for p in policy.POLICY_FILES if (dest / p).is_file()}
    return policy.scan_files(files)


def snippet(dest: Path, path: str, line: int, radius: int = 4) -> str:
    try:
        lines = (dest / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    lo, hi = max(0, line - 1 - radius), min(len(lines), line + radius)
    return "\n".join(f"{n + 1:5d}{'>' if n + 1 == line else ' '} {lines[n]}" for n in range(lo, hi))


def hunt(cfg: Config, repo: str, q: Queue, stats: Stats, work: str = "fix") -> dict:
    dest = clone(cfg, repo)
    pol = policy_of(dest)
    if pol.anti_ai:
        return {"repo": repo, "anti_ai": pol.source, "clean": 0, "duplicate": 0}
    found = audit_mod.scan_tree(dest) + external.ruff_findings(dest) + external.js_findings(dest)
    uniq = {(f.path, f.line, f.kind): f for f in found}
    ranked = rank(list(uniq.values()), stats)[:TOP_PER_REPO * 3]
    clean = dup = 0
    for score, f in ranked:
        if clean >= TOP_PER_REPO:
            break
        it = Item(item_id(repo, f.path, f.kind, f.line), repo, f.path, f.line, f.kind, f.detail,
                  clone=str(dest), work=work, rank=score, snippet=snippet(dest, f.path, f.line))
        if it.id in q.items:
            continue
        ms = dedupe.find_matches(repo, f"{f.kind} {f.path}", f.detail, f.path, [f.kind.replace("-", " ")])
        hits = dedupe.recent_commit_hits(repo, f.path, sorted(dedupe.tokens(f.detail))[:6])
        if dedupe.is_duplicate(ms) or hits:
            it.status = "duplicate"
            it.notes = [f"#{m.number} ({m.state}) {m.title} [{m.reason}, {m.score}]" for m in ms[:3]] + hits[:1]
            dup += 1
        else:
            it.status = "clean"
            clean += 1
        q.add(it)
    q.save()
    return {"repo": repo, "anti_ai": None, "clean": clean, "duplicate": dup}
