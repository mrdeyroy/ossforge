"""Source-backed policy review that must exist before anything is published to a third-party repo.

`snapshot` reads the repo's policy-bearing docs (fixed list of locations, read-only) and keeps their URLs and blob
SHAs. The owner reads them and records the review with a note on any restrictions. `check` then requires, at
submit time, a record whose doc SHAs still match. A changed doc, a missing record or a record marked prohibited
stops the submission. Missing or empty scan results mean "review needed", never "no policy": the scan covers a
fixed list of files and cannot see rules kept elsewhere (project docs sites, wikis, linked pages).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from . import gh, policy
from .config import Config


def snapshot(repo: str) -> dict:
    docs = []
    for p in gh.existing_files(repo, policy.POLICY_FILES):
        d = gh.api(f"repos/{repo}/contents/{p}", fresh=True)
        if isinstance(d, dict) and d.get("encoding") == "base64":
            text = base64.b64decode(d["content"]).decode("utf-8", "replace")
            docs.append({"path": p, "url": d.get("html_url", ""), "sha": d.get("sha", ""), "text": text})
    sc = policy.scan_files({d["path"]: d["text"] for d in docs})
    return {"repo": repo, "docs": docs, "scanned_locations": list(policy.POLICY_FILES), "anti_ai": sc.anti_ai,
            "ai_policy_docs": policy.ai_policy_docs({d["path"]: d["text"] for d in docs})}


def _file(cfg: Config):
    return cfg.path("policy_reviews.json")


def _load(cfg: Config) -> dict:
    try:
        return json.loads(_file(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(cfg: Config, repo: str, snap: dict, note: str, prohibited: bool = False) -> dict:
    rec = {"repo": repo, "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note,
           "prohibited": prohibited, "docs": [{k: d[k] for k in ("path", "url", "sha")} for d in snap["docs"]],
           "scanned_locations": snap["scanned_locations"]}
    allr = _load(cfg)
    allr[repo.lower()] = rec
    _file(cfg).parent.mkdir(parents=True, exist_ok=True)
    _file(cfg).write_text(json.dumps(allr, indent=1), encoding="utf-8")
    return rec


def check(cfg: Config, repo: str, snap: dict | None = None) -> str:
    """Empty string when a current, non-prohibiting review exists; otherwise the reason it does not."""
    rec = _load(cfg).get(repo.lower())
    if not rec:
        return (f"no policy review recorded for {repo}. Run `ossforge policy-review {repo}`, read the documents it "
                "prints (and the project's own contribution pages, which the scan cannot see), then record the review")
    if rec.get("prohibited"):
        return f"policy review for {repo} is recorded as prohibited: {rec.get('note', '')}"
    snap = snap or snapshot(repo)
    now = {d["path"]: d["sha"] for d in snap["docs"]}
    was = {d["path"]: d["sha"] for d in rec["docs"]}
    if now != was:
        changed = sorted(set(now) ^ set(was) | {p for p in now if p in was and now[p] != was[p]})
        return f"policy documents changed since the review ({', '.join(changed)}); review {repo} again"
    return ""
