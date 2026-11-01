"""Personalisation from your own public PR history.

`ossforge bootstrap` reads the PRs you opened on other people's repos, counts merged and
closed-unmerged per repo, and stores that in the stats file. `scout` then prefers projects that
already merged your work and avoids ones that closed it. Same idea as oss-scout's history import,
written independently on top of the plain GitHub search API.
"""

from __future__ import annotations

from collections import defaultdict

from . import gh
from .outcomes import Stats


def tally(items: list[dict], user: str, outcome: str, own: set[str] | None = None) -> dict[str, int]:
    """Count PR search hits per repo, ignoring PRs on your own account or orgs."""
    mine = {user.lower()} | {o.lower() for o in (own or set())}
    out: dict[str, int] = defaultdict(int)
    for it in items:
        url = it.get("repository_url", "")
        if "repos/" not in url:
            continue
        repo = url.split("repos/")[1]
        if repo.split("/")[0].lower() in mine:
            continue
        out[repo] += 1
    return dict(out)


def bootstrap(stats: Stats, user: str = "", own_orgs: list[str] | None = None) -> dict:
    """Import merged/closed history. Classification of repo owners:
    - your login, and orgs listed in config ``own_orgs``: yours, ignored.
    - orgs you are a member of but did not list: unclassified. Membership is not ownership and not
      outside contribution either, so they are reported but neither boost nor are discarded silently.
    - everything else: outside contributions, used for boosting."""
    me = user or gh.api("user", fresh=True)["login"]
    own = {o.lower() for o in (own_orgs or [])}
    member: set[str] = set()
    try:  # best effort: private memberships need read:org
        member = {o["login"].lower() for o in gh.api("user/orgs", fresh=True) or []} - own
    except gh.GhError:
        pass
    merged_all = tally(gh.search_issues(f"is:pr is:merged author:{me}", per_page=100, fresh=True), me, "merged", own)
    closed_all = tally(gh.search_issues(f"is:pr is:closed is:unmerged author:{me}", per_page=100, fresh=True), me, "closed", own)
    unclassified = sorted({r for r in (*merged_all, *closed_all) if r.split("/")[0].lower() in member})
    merged = {r: n for r, n in merged_all.items() if r not in unclassified}
    closed = {r: n for r, n in closed_all.items() if r not in unclassified}
    for repo in set(merged) | set(closed):
        stats.set_history(repo, merged.get(repo, 0), closed.get(repo, 0))
    stats.save()
    return {"user": me, "merged_repos": len(merged), "closed_repos": len(closed), "merged": merged, "closed": closed,
            "unclassified": unclassified}
