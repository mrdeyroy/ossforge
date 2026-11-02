"""Explicit candidate-specific false-positive reviews, never a global duplicate bypass."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import gh, issue_reviews
from .queue import Item


def candidate(it: Item) -> str:
    values = [it.repo, it.issue_title, it.issue_body, it.pr_title, it.pr_body, it.verification]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def snapshot(repo: str, number: int) -> dict:
    item = gh.api(f"repos/{repo}/issues/{number}", fresh=True)
    expected = f"https://github.com/{repo}/"
    if item.get("number") != number or item.get("html_url") not in (
        f"{expected}issues/{number}", f"{expected}pull/{number}"
    ) or not item.get("updated_at"):
        raise ValueError("duplicate review needs a complete matching upstream item")
    result = {k: item.get(k) for k in ("number", "html_url", "title", "body", "state", "updated_at", "comments", "locked")}
    if "pull_request" in item:
        pr = gh.api(f"repos/{repo}/pulls/{number}", fresh=True)
        head, base = pr.get("head", {}).get("sha"), pr.get("base", {}).get("sha")
        if not head or not base:
            raise ValueError("duplicate PR review needs current head and base")
        result["pr"] = {"head": head, "base": base, "state": pr.get("state"), "updated_at": pr.get("updated_at")}
    return result


def record(path: Path, it: Item, number: int, reason: str) -> None:
    if it.status != "verified" or not it.verification or not reason.strip():
        raise ValueError("verify the candidate and provide a specific non-duplicate reason first")
    data = issue_reviews.load(path)
    data[f"{it.repo.lower()}#{number}:{it.id}"] = {
        "candidate": candidate(it), "upstream": snapshot(it.repo, number), "reason": reason.strip()
    }
    issue_reviews._save(path, data)


def unchanged(path: Path, it: Item, number: int) -> bool:
    record = issue_reviews.load(path).get(f"{it.repo.lower()}#{number}:{it.id}", {})
    if not isinstance(record, dict) or record.get("candidate") != candidate(it) or not record.get("reason"):
        return False
    return record.get("upstream") == snapshot(it.repo, number)


def commit_snapshot(repo: str, sha: str) -> dict:
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("review requires the full commit SHA")
    data = gh.api(f"repos/{repo}/commits/{sha}", fresh=True)
    if data.get("sha") != sha or data.get("html_url") != f"https://github.com/{repo}/commit/{sha}":
        raise ValueError("commit does not match the target repository and SHA")
    # Immutable SHA plus tree and parents identify the exact reviewed code, not a moving tip.
    tree = data.get("commit", {}).get("tree", {}).get("sha")
    if not tree:
        raise ValueError("reviewed commit tree unavailable")
    return {"sha": sha, "tree": tree, "parents": [p["sha"] for p in data.get("parents", [])]}


def record_commit(path: Path, it: Item, sha: str, reason: str) -> None:
    if it.status != "verified" or not it.verification or not reason.strip():
        raise ValueError("verify the candidate and provide a specific non-duplicate reason first")
    data = issue_reviews.load(path)
    data[f"{it.repo.lower()}@{sha}:{it.id}"] = {
        "candidate": candidate(it), "upstream": commit_snapshot(it.repo, sha), "reason": reason.strip()
    }
    issue_reviews._save(path, data)


def unchanged_commit(path: Path, it: Item, url: str) -> bool:
    prefix = f"https://github.com/{it.repo}/commit/"
    if not url.startswith(prefix):
        return False
    sha = url[len(prefix):]
    record = issue_reviews.load(path).get(f"{it.repo.lower()}@{sha}:{it.id}", {})
    if not isinstance(record, dict) or record.get("candidate") != candidate(it) or not record.get("reason"):
        return False
    return record.get("upstream") == commit_snapshot(it.repo, sha)
