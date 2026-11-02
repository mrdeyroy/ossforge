"""Watch our open PRs: record outcomes, and say what each one needs next.

Classification idea from ContribAI's PR patrol. Pure `classify` is unit-tested;
`patrol` does the fetching. Nothing is posted from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import gh, safety
from .outcomes import Stats


@dataclass
class Action:
    repo: str
    pr: int
    kind: str  # merged | closed | dco | cla | ci | conflict | changes_requested | feedback | idle
    detail: str


def classify(pr: dict, checks: list[dict], reviews: list[dict], comments: list[dict], me: str) -> list[Action]:
    repo, n = pr["base"]["repo"]["full_name"], pr["number"]
    if pr.get("merged"):
        return [Action(repo, n, "merged", "merged")]
    if pr["state"] == "closed":
        return [Action(repo, n, "closed", "closed without merge")]
    out: list[Action] = []
    for c in checks:
        name = (c.get("name") or "").lower()
        if c.get("conclusion") in ("failure", "timed_out", "action_required"):
            kind = "dco" if "dco" in name else "cla" if "cla" in name else "ci"
            out.append(Action(repo, n, kind, f"check '{c['name']}' {c['conclusion']}"))
    if any(r.get("state") == "CHANGES_REQUESTED" for r in reviews):
        out.append(Action(repo, n, "changes_requested", "a reviewer requested changes"))
    if pr.get("mergeable_state") == "dirty":
        out.append(Action(repo, n, "conflict", "merge conflicts: rebase onto the base branch"))
    others = [c for c in comments if (c.get("user") or {}).get("login") != me and (c.get("user") or {}).get("type") != "Bot"]
    if others and (not comments or (comments[-1].get("user") or {}).get("login") != me):
        last_author = (others[-1].get("user") or {}).get("login") or "ghost"
        out.append(Action(repo, n, "feedback", f"unanswered comment from @{last_author}"))
    for c in comments:
        body = c.get("body", "").lower()
        if "cla" in body and ("sign" in body or "not signed" in body) and (c.get("user") or {}).get("type") == "Bot":
            out.append(Action(repo, n, "cla", f"CLA bot is waiting: {c['html_url']}"))
            break
    return out or [Action(repo, n, "idle", "no action needed")]


def patrol(audit: safety.Audit, stats: Stats) -> list[Action]:
    me = gh.api("user", fresh=True)["login"]
    hist = safety.effective_history(audit.read())
    actions: list[Action] = []
    for h in hist:
        if h.get("event") != "pr_opened" or h.get("state") != "open":
            continue
        repo, n = h["repo"], h["pr"]
        pr = gh.api(f"repos/{repo}/pulls/{n}", fresh=True)
        checks = gh.api(f"repos/{repo}/commits/{pr['head']['sha']}/check-runs", fresh=True).get("check_runs", [])
        reviews = gh.api(f"repos/{repo}/pulls/{n}/reviews", fresh=True) or []
        comments = gh.api(f"repos/{repo}/issues/{n}/comments", fresh=True) or []
        acts = classify(pr, checks, reviews, comments, me)
        for a in acts:
            if a.kind in ("merged", "closed"):
                state = "merged" if a.kind == "merged" else "closed_unmerged"
                audit.update_state(repo, n, state)
                stats.record_repo(repo, state)
        actions += acts
    stats.save()
    return actions
