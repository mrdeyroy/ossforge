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


def tally(items: list[dict], user: str, outcome: str) -> dict[str, int]:
    """Count PR search hits per repo, ignoring PRs on the user's own repos."""
    out: dict[str, int] = defaultdict(int)
    for it in items:
        url = it.get("repository_url", "")
        if "repos/" not in url:
            continue
        repo = url.split("repos/")[1]
        if repo.split("/")[0].lower() == user.lower():
            continue
        out[repo] += 1
    return dict(out)


def bootstrap(stats: Stats, user: str = "") -> dict:
    me = user or gh.api("user", fresh=True)["login"]
    merged = tally(gh.search_issues(f"is:pr is:merged author:{me}", per_page=100, fresh=True), me, "merged")
    closed = tally(gh.search_issues(f"is:pr is:closed is:unmerged author:{me}", per_page=100, fresh=True), me, "closed")
    for repo in set(merged) | set(closed):
        stats.set_history(repo, merged.get(repo, 0), closed.get(repo, 0))
    stats.save()
    return {"user": me, "merged_repos": len(merged), "closed_repos": len(closed),
            "merged": merged, "closed": closed}
