"""Find candidate issues (fixes or features), gate by repo health, filter spam, vet."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import acceptance, gh, radar, vet
from .config import Config
from .outcomes import Stats

FEATURE_LABELS = ["enhancement", "feature request", "feature"]
_MONEY = re.compile(r"(\$\s?\d|\b\d[\d,]*\s?(eth|usdt|usdc|rtc|btc|sol)\b)", re.I)


@dataclass
class Candidate:
    repo: str
    number: int
    title: str
    url: str
    repo_score: int
    verdict: vet.Verdict
    kind: str = "fix"  # fix | feature
    acceptance: str = "not checked"  # accepting | none | unknown | not checked
    score: float = 0.0
    why: list[str] = field(default_factory=list)


def is_spam(title: str, body: str, keywords: list[str]) -> bool:
    hay = f"{title}\n{(body or '')[:600]}".lower()
    return bool(_MONEY.search(hay)) or any(k in hay for k in keywords)


def score_issue(it: dict, repo_score: int, now: datetime | None = None) -> tuple[float, list[str]]:
    """Explainable 0-100 priority from search-result fields only (no extra API calls).

    Favors: healthy repo, recent activity, a maintainer already engaged, a bug label, some discussion but
    not a crowd. A heuristic for ordering, never a reason to skip the real vetting.
    """
    now = now or datetime.now(timezone.utc)
    score, why = repo_score * 0.5, [f"repo health {repo_score}"]
    try:
        age = (now - datetime.fromisoformat(it["updated_at"].replace("Z", "+00:00"))).days
    except (KeyError, ValueError):
        age = None
    if age is not None:
        pts = 20 if age <= 14 else 12 if age <= 60 else 4 if age <= 180 else -10
        score += pts
        why.append(f"updated {age}d ago")
    labels = {(lb.get("name") if isinstance(lb, dict) else str(lb)).lower() for lb in it.get("labels", [])}
    if labels & {"bug", "regression", "defect"}:
        score += 12
        why.append("bug label")
    if it.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR"):
        score += 8
        why.append("filed by a maintainer")
    n = it.get("comments", 0)
    if n == 0:
        score -= 3
        why.append("no discussion yet")
    elif n <= 8:
        score += 5
    else:
        score -= 8
        why.append(f"{n} comments: likely contested or crowded")
    return max(0.0, min(100.0, score)), why


def build_query(language: str | None, label: str, min_stars: int) -> str:
    q = f'is:issue is:open no:assignee archived:false label:"{label}"'
    if language:
        q += f" language:{language}"
    return q + f" stars:>={min_stars}"


# Why a run returned what it did. Reset by every scout() call; read by the CLI to tell "no matches"
# from "everything filtered" from "stopped early by a rate limit".
LAST_FUNNEL: dict = {}


def explain_funnel(f: dict) -> str:
    if f.get("stopped"):
        return f"STOPPED EARLY: {f['stopped']}. Results so far are partial."
    if not f.get("fetched"):
        return "NO MATCHES: the search returned no issues for this query (try another label/language or lower min_stars)."
    if not f.get("kept"):
        dropped = {k: f[k] for k in ("spam", "unclear", "skipped", "radar_failed") if f.get(k)}
        return f"ALL FILTERED: {f['fetched']} issues found, none usable; dropped by stage: {dropped or 'n/a'}."
    return f"{f['kept']} of {f['fetched']} issues kept ({f['approved']} approved)."


def scout(
    cfg: Config,
    stats: Stats | None = None,
    language: str | None = None,
    label: str = "help wanted",
    limit: int = 20,
    kind: str = "fix",
    skip_repos: set[str] | None = None,
) -> list[Candidate]:
    f = LAST_FUNNEL
    f.clear()
    f.update(fetched=0, spam=0, unclear=0, skipped=0, radar_failed=0, kept=0, approved=0, stopped="")
    scores: dict[str, radar.RepoScore] = {}
    out: list[Candidate] = []
    try:
        items = gh.search_issues(build_query(language, label, cfg.min_stars), per_page=limit)
    except gh.RateLimited as e:
        f["stopped"] = f"GitHub rate limit while searching ({e}); nothing was fetched"
        return out
    f["fetched"] = len(items)
    for it in items:
        # cheap local filters first: they cost no API calls
        if is_spam(it["title"], it.get("body") or "", cfg.spam_keywords):
            f["spam"] += 1
            continue
        if not vet.clear_requirements(it.get("body") or ""):
            f["unclear"] += 1
            continue
        repo = it["repository_url"].split("repos/")[1]
        if skip_repos and repo in skip_repos:
            f["skipped"] += 1
            continue
        try:
            if repo not in scores:
                try:
                    scores[repo] = radar.analyze(repo)
                except gh.RateLimited:
                    raise
                except gh.GhError:
                    f["radar_failed"] += 1
                    continue
            rs = scores[repo]
            boost = stats.repo_boost(repo) if stats else 0
            v = vet.vet_issue(repo, it["number"], repo_ok=rs.score + boost >= cfg.min_repo_score)
            acc = None
            if v.decision == "approve":  # spend the extra calls only on candidates that already passed
                acc = acceptance.evidence(repo)
                if acc.status == "none":
                    v = vet.Verdict(v.issue, "skip", v.reasons + ["no outside-contributor PR merged recently: " + acc.reasons[0]])
        except gh.RateLimited as e:
            f["stopped"] = f"GitHub rate limit while vetting {repo} ({e}); {len(items) - f['kept']} issues not examined"
            break
        sc, why = score_issue(it, rs.score + boost)
        if acc:
            why = why + [f"outside PRs: {acc.status} ({acc.reasons[0] if acc.reasons else ''})"]
        out.append(Candidate(repo, it["number"], it["title"], it["html_url"], rs.score + boost, v, kind, score=sc, why=why,
                             acceptance=acc.status if acc else "not checked"))
        f["kept"] += 1
        f["approved"] += v.decision == "approve"
    out.sort(key=lambda c: (c.verdict.decision != "approve", -c.score))
    return out


def scout_features(cfg: Config, stats: Stats | None = None, language: str | None = None, limit: int = 15,
                   skip_repos: set[str] | None = None) -> list[Candidate]:
    res: list[Candidate] = []
    total: dict = {}
    for lb in FEATURE_LABELS[:2]:
        res += scout(cfg, stats, language, lb, limit, kind="feature", skip_repos=skip_repos)
        for k, v in LAST_FUNNEL.items():
            total[k] = f"{total[k]}; {v}".strip("; ") if k == "stopped" else total.get(k, 0) + v
    LAST_FUNNEL.clear()
    LAST_FUNNEL.update(total)
    seen: set[tuple[str, int]] = set()
    uniq = []
    for c in res:
        if (c.repo, c.number) not in seen:
            seen.add((c.repo, c.number))
            uniq.append(c)
    return uniq
