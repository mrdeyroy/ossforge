"""Bounded, read-only discovery planning and temporary result rotation.

Repository affinity selects where to look, never whether an issue is valid.
The existing scout gates remain authoritative for every fetched issue.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from . import issue_reviews, scout
from .config import Config
from .outcomes import Stats

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


@dataclass
class Plan:
    strategy: str
    repos: list[str]
    query: str


def plan(cfg: Config, stats: Stats, language: str | None, label: str,
         strategy: str, cursor: int) -> Plan:
    if strategy not in {"rotate", "broad", "history", "preferred"}:
        raise ValueError("strategy must be rotate, broad, history or preferred")
    preferred = sorted({r.lower() for r in cfg.preferred_repos if _REPO.fullmatch(r)})
    history = sorted(r.lower() for r in stats.d["repos"] if _REPO.fullmatch(r) and stats.repo_boost(r) > 0)
    pools = {"preferred": preferred, "history": history}
    enabled = ["broad"] + [s for s in ("preferred", "history") if pools[s]]
    chosen = enabled[cursor % len(enabled)] if strategy == "rotate" else strategy
    repos = pools.get(chosen, [])
    # Five repositories bound query length and request cost. Rotating windows eventually cover the list.
    window = cursor // len(enabled) if strategy == "rotate" else cursor
    repos = [repos[(window * 5 + i) % len(repos)] for i in range(min(5, len(repos)))] if repos else []
    query = scout.build_query(language, label, cfg.min_stars)
    if chosen != "broad":
        query += " " + " ".join(f"repo:{r}" for r in repos)
    return Plan(chosen, repos, query)


def recent_reason(data: dict, repo: str, number: int, updated_at: str | None,
                  days: int, now: float | None = None) -> str:
    entry = data.get(f"{repo.lower()}#{number}")
    now = time.time() if now is None else now
    if days > 0 and updated_at and isinstance(entry, dict) and entry.get("updated_at") == updated_at:
        seen = entry.get("seen_at")
        if isinstance(seen, (int, float)) and 0 <= now - seen < days * 86400:
            return "recently surfaced unchanged issue"
    return ""


def discover(cfg: Config, stats: Stats, language: str | None = None, label: str = "help wanted",
             limit: int = 20, strategy: str = "rotate", include_recent: bool = False,
             skip_repos: set[str] | None = None) -> list[scout.Candidate]:
    state_path = cfg.path("discovery.json")
    state = issue_reviews.load(state_path)
    cursor = state.get("cursor", 0)
    cursor = cursor if isinstance(cursor, int) and cursor >= 0 else 0
    selected = plan(cfg, stats, language, label, strategy, cursor)
    recent = state.get("recent", {})
    recent = recent if isinstance(recent, dict) else {}
    if selected.strategy != "broad" and not selected.repos:
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(fetched=0, kept=0, approved=0, stopped="")
        result = []
    else:
        result = scout.scout(cfg, stats, language, label, limit, skip_repos=skip_repos,
                             query=selected.query, recent={} if include_recent else recent)
    # A stopped pass does not consume its strategy turn or hide partial results on retry.
    if not scout.LAST_FUNNEL.get("stopped"):
        now = time.time()
        recent = {k: v for k, v in recent.items() if isinstance(v, dict)
                  and isinstance(v.get("seen_at"), (int, float))
                  and 0 <= now - v["seen_at"] < max(0, cfg.recent_issue_days) * 86400}
        for c in result:
            if c.verdict.decision == "approve":
                recent[f"{c.repo.lower()}#{c.number}"] = {"updated_at": c.updated_at, "seen_at": now}
        issue_reviews._save(state_path, {"cursor": cursor + 1, "recent": recent})
    for c in result:
        c.why.append(f"discovery source: {selected.strategy}")
    scout.LAST_FUNNEL.update(strategy=selected.strategy, query=selected.query, repos=selected.repos)
    return result
