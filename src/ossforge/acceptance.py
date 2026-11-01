"""Do maintainers merge pull requests from outside contributors here, lately? Evidence, not a probability.

Reads recent closed PRs and reports facts: who wrote them (bots excluded), whether the author is outside the
project, whether they merged, who merged them, and when. "unknown" (no or unreadable data) is kept apart
from "none" (enough recent closed PRs seen, no external one merged).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import gh

EXTERNAL = {"CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"}
WINDOW_DAYS = 180
SAMPLE = 40
MIN_SAMPLE_FOR_NONE = 10
MIN_SPAN_FOR_NONE = 30  # days of history the sample must cover before 'none' is allowed
MERGER_LOOKUPS = 4


@dataclass
class Acceptance:
    repo: str
    status: str  # accepting | none | unknown
    reasons: list[str] = field(default_factory=list)
    external_merged: list[dict] = field(default_factory=list)  # {pr, author, merged_at, merged_by}
    external_closed_unmerged: int = 0
    closed_seen: int = 0
    window_days: int = WINDOW_DAYS
    sample_complete: bool = False
    covered_days: int = 0  # how far back the examined PRs reach (the whole window when the sample is complete)


def _age(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    return (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 86400


def _is_bot(pr: dict) -> bool:
    u = pr.get("user") or {}
    return u.get("type") == "Bot" or str(u.get("login", "")).endswith("[bot]")


def summarize(repo: str, prs: list[dict], now: datetime | None = None, merged_by=None) -> Acceptance:
    """Pure: ``prs`` are GitHub pull-request objects (closed, newest first). ``merged_by(pr)`` may resolve mergers."""
    now = now or datetime.now(timezone.utc)
    acc = Acceptance(repo, "unknown")
    recent = [p for p in prs if (a := _age(p.get("closed_at"), now)) is not None and a <= WINDOW_DAYS]
    humans = [p for p in recent if not _is_bot(p)]
    acc.closed_seen = len(humans)
    acc.sample_complete = len(prs) < SAMPLE or len(recent) < len(prs)  # the window ended inside the sample
    ages = [_age(p["closed_at"], now) for p in humans]
    acc.covered_days = WINDOW_DAYS if acc.sample_complete else int(max(ages, default=0))
    ext = [p for p in humans if p.get("author_association") in EXTERNAL]
    acc.external_closed_unmerged = sum(1 for p in ext if not p.get("merged_at"))
    for i, p in enumerate(x for x in ext if x.get("merged_at")):
        by = merged_by(p) if merged_by and i < MERGER_LOOKUPS else None
        acc.external_merged.append({"pr": p["number"], "author": p["user"]["login"], "merged_at": p["merged_at"],
                                    "merged_by": by})
    authors = {m["author"] for m in acc.external_merged}
    if acc.external_merged:
        last = min(_age(m["merged_at"], now) for m in acc.external_merged)
        acc.reasons.append(f"{len(acc.external_merged)} outside-contributor PR(s) merged in {WINDOW_DAYS}d "
                           f"by {len(authors)} author(s); latest {int(last)}d ago; "
                           f"{acc.external_closed_unmerged} outside PR(s) closed unmerged")
        self_merged = [m for m in acc.external_merged if m["merged_by"] and m["merged_by"] == m["author"]]
        if self_merged:
            acc.reasons.append(f"{len(self_merged)} of those were merged by their own author (not counted as maintainer acceptance)")
        counted = [m for m in acc.external_merged if m["merged_by"] != m["author"]]
        acc.status = "accepting" if counted and last <= 90 else "unknown"
        if acc.status == "unknown":
            acc.reasons.append("no counted outside merge in the last 90d")
    elif acc.closed_seen >= MIN_SAMPLE_FOR_NONE and acc.covered_days >= MIN_SPAN_FOR_NONE:
        acc.status = "none"
        acc.reasons.append(f"{acc.closed_seen} human PRs closed in the last {acc.covered_days}d, none from an outside contributor was merged "
                           f"({acc.external_closed_unmerged} outside PR(s) closed unmerged)")
    else:
        acc.reasons.append(f"only {acc.closed_seen} recent human PRs seen: not enough to say (unknown, not negative)")
    return acc


def evidence(repo: str) -> Acceptance:
    hit = gh.cache_get(f"accept:{repo}", 12 * 3600)
    if hit:
        return Acceptance(**hit)
    try:
        prs = gh.api(f"repos/{repo}/pulls", state="closed", per_page=SAMPLE, sort="updated", direction="desc") or []
    except gh.RateLimited:
        raise
    except gh.GhError as e:
        return Acceptance(repo, "unknown", [f"could not read PR history: {e}"])

    def merged_by(p: dict) -> str | None:
        try:
            return ((gh.api(f"repos/{repo}/pulls/{p['number']}").get("merged_by")) or {}).get("login")
        except gh.RateLimited:
            raise
        except gh.GhError:
            return None

    acc = summarize(repo, prs, merged_by=merged_by)
    gh.cache_put(f"accept:{repo}", acc.__dict__)
    return acc
