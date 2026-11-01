"""Repo health scoring (0-100), ported from GitSense radar. Pure scorer + fetcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

from . import gh


@dataclass
class RepoSignals:
    merged_prs: int
    open_prs: int
    stale_ratio: float
    median_merge_days: float | None
    external_merged_ratio: float | None
    stars: int
    pushed_days: float | None = None
    archived: bool = False


@dataclass
class RepoScore:
    repo: str
    score: int
    recommendation: str
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def score_repo(s: RepoSignals) -> tuple[int, list[str], list[str]]:
    score, notes, flags = 50, [], []

    def add(delta: int, note: str = "") -> None:
        nonlocal score
        score += delta
        if note:
            notes.append(note)

    if s.merged_prs >= 30:
        add(15, "active merge history")
    elif s.merged_prs >= 10:
        add(8, "some recent merges")
    elif s.merged_prs == 0:
        add(-18, "no recent merged PRs")
        flags.append("no recent merges")

    if s.median_merge_days is not None:
        if s.median_merge_days <= 7:
            add(14, "fast median merge time")
        elif s.median_merge_days <= 21:
            add(6, "reasonable merge time")
        elif s.median_merge_days > 45:
            add(-12, "slow merge time")
            flags.append("slow merge time")

    if s.stale_ratio >= 0.5 and s.open_prs:
        add(-24, "many stale open PRs")
        flags.append("stale backlog")
    elif s.stale_ratio >= 0.25:
        add(-12, "noticeable stale backlog")
    elif s.open_prs:
        add(6, "stale ratio manageable")

    if s.external_merged_ratio is not None:
        if s.external_merged_ratio >= 0.5:
            add(10, "outside contributors get merged")
        elif s.external_merged_ratio < 0.2:
            add(-8, "recent merges mostly internal")
            flags.append("mostly internal merges")

    if s.open_prs >= 100 and s.merged_prs < 10:
        add(-10, "queue far larger than merge volume")
    elif s.open_prs >= 50 and s.merged_prs < 5:
        add(-8, "crowded open queue")

    if s.stars >= 10_000:
        add(5)
    elif s.stars >= 1_000:
        add(3)

    if s.archived:
        flags.append("archived")
        score = 0
    elif s.pushed_days is not None and s.pushed_days > 90:
        add(-20, "no push in 90+ days")
        flags.append("inactive")
    return max(0, min(100, score)), notes, flags


def recommendation(score: int, flags: list[str]) -> str:
    if "archived" in flags:
        return "Avoid"
    if score >= 75:
        return "Go"
    if score >= 60:
        return "Watch"
    if score >= 45:
        return "Comment first"
    return "Avoid"


def _parse(x: str) -> datetime:
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def _days(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return (_parse(b) - _parse(a)).total_seconds() / 86400


RADAR_TTL = 24 * 3600  # repo health does not change hour to hour


DEAD_AFTER_DAYS = 365


def analyze(repo: str, days: int = 90, stale_days: int = 14) -> RepoScore:
    hit = gh.cache_get(f"radar:{repo}", RADAR_TTL)
    if hit:
        return RepoScore(**hit)
    res = _analyze(repo, days, stale_days)
    gh.cache_put(f"radar:{repo}", res.__dict__)
    return res


def _analyze(repo: str, days: int, stale_days: int) -> RepoScore:
    info = gh.api(f"repos/{repo}")
    now = datetime.now(timezone.utc)
    since = (now.date() - timedelta(days=days)).isoformat()
    stale = (now.date() - timedelta(days=stale_days)).isoformat()
    merged_q = f"repo:{repo} is:pr is:merged merged:>={since}"
    pushed = _days(info.get("pushed_at"), now.isoformat())
    if info.get("archived") or (pushed is not None and pushed > DEAD_AFTER_DAYS):
        # no search calls spent on a repo nobody is maintaining
        flag = "archived" if info.get("archived") else "inactive"
        return RepoScore(repo, 0, "Avoid", [f"{flag}: last push {int(pushed or 0)}d ago"], [flag])
    page = gh.search_page(merged_q, per_page=20)
    merged = page["total_count"]
    open_n = gh.search_count(f"repo:{repo} is:pr is:open")
    stale_n = gh.search_count(f"repo:{repo} is:pr is:open created:<{stale}")
    sample = page["items"]
    md = [d for d in (_days(i.get("created_at"), i.get("closed_at")) for i in sample) if d is not None]
    ext = [i for i in sample if i.get("author_association") not in ("OWNER", "MEMBER", "COLLABORATOR")]
    sig = RepoSignals(
        merged_prs=merged,
        open_prs=open_n,
        stale_ratio=(stale_n / open_n) if open_n else 0.0,
        median_merge_days=median(md) if md else None,
        external_merged_ratio=(len(ext) / len(sample)) if sample else None,
        stars=info.get("stargazers_count", 0),
        pushed_days=_days(info.get("pushed_at"), now.isoformat()),
        archived=bool(info.get("archived")),
    )
    score, notes, flags = score_repo(sig)
    return RepoScore(repo, score, recommendation(score, flags), notes, flags)
