"""Thin GitHub access through the authenticated `gh` CLI (no token handling here).

Adds a disk TTL cache for GETs and a sliding-window budget for the search API
(30 req/min), the same idea as oss-scout's http-cache and search-budget.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

_CACHE_DIR: Path | None = None
_TTL = 900
_SEARCH_TIMES: deque[float] = deque()
SEARCH_PER_MIN = 9  # well under GitHub's secondary limit; bursts of searches look like scraping


class GhError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class RateLimited(GhError):
    """Primary or secondary GitHub rate limit. Callers stop the pass instead of retrying."""


PACING_S = 0.4  # gap after every uncached call; keeps bursts under the secondary limit


def configure(cache_dir: str | Path | None, ttl: int = 900) -> None:
    global _CACHE_DIR, _TTL
    _CACHE_DIR = Path(cache_dir) if cache_dir else None
    _TTL = ttl


def _budget(path: str) -> None:
    if not path.startswith("search/"):
        return
    now = time.time()
    while _SEARCH_TIMES and now - _SEARCH_TIMES[0] > 60:
        _SEARCH_TIMES.popleft()
    if len(_SEARCH_TIMES) >= SEARCH_PER_MIN:
        time.sleep(max(0.0, 60 - (now - _SEARCH_TIMES[0])) + 0.2)
    _SEARCH_TIMES.append(time.time())


def _cache_path(path: str, params: dict) -> Path | None:
    if _CACHE_DIR is None:
        return None
    key = hashlib.sha1(json.dumps([path, sorted(params.items())]).encode()).hexdigest()
    return _CACHE_DIR / f"{key}.json"


def api(path: str, /, *, fresh: bool = False, **params: Any) -> Any:
    cp = _cache_path(path, params)
    if cp and not fresh and cp.exists() and time.time() - cp.stat().st_mtime < _TTL:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except ValueError:
            pass
    _budget(path)
    cmd = ["gh", "api", "-X", "GET", path]
    for k, v in params.items():
        cmd += ["-f", f"{k}={v}"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    time.sleep(PACING_S)
    if p.returncode != 0:
        err = p.stderr.strip()
        status = 404 if "404" in err else 403 if "403" in err else None
        if "rate limit" in err.lower():
            raise RateLimited(err, status)
        raise GhError(err or "gh api failed", status)
    data = json.loads(p.stdout) if p.stdout.strip() else None
    if cp and data is not None:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(data), encoding="utf-8")
    return data


def search_issues(q: str, per_page: int = 30, sort: str = "updated", fresh: bool = False) -> list[dict]:
    return api("search/issues", fresh=fresh, q=q, per_page=per_page, sort=sort, order="desc")["items"]


def search_count(q: str) -> int:
    return api("search/issues", q=q, per_page=1)["total_count"]


def file_text_at(repo: str, path: str, ref: str) -> str | None:
    return file_text(repo, path, ref)


def cache_get(key: str, ttl: int) -> Any | None:
    """Generic derived-value cache (e.g. a repo's health score) with its own TTL."""
    cp = _cache_path("derived:" + key, {})
    if cp and cp.exists() and time.time() - cp.stat().st_mtime < ttl:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def cache_put(key: str, value: Any) -> None:
    cp = _cache_path("derived:" + key, {})
    if cp:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(value), encoding="utf-8")


def existing_files(repo: str, paths: tuple[str, ...]) -> list[str]:
    """Which of `paths` exist, using one directory listing per parent (3 calls) instead of one probe per path."""
    parents = {p.rsplit("/", 1)[0] if "/" in p else "" for p in paths}
    present: set[str] = set()
    for d in parents:
        try:
            listing = api(f"repos/{repo}/contents/{d}".rstrip("/")) or []
        except RateLimited:
            raise
        except GhError:
            continue
        if isinstance(listing, list):
            present.update(x["path"] for x in listing if x.get("type") == "file")
    return [p for p in paths if p in present]


_MISSING: set[tuple[str, str, str | None]] = set()


def file_text(repo: str, path: str, ref: str | None = None) -> str | None:
    if (repo, path, ref) in _MISSING:
        return None
    try:
        d = api(f"repos/{repo}/contents/{path}", **({"ref": ref} if ref else {}))
    except GhError as e:
        if e.status == 404 and not isinstance(e, RateLimited):
            _MISSING.add((repo, path, ref))
            return None
        raise
    if isinstance(d, dict) and d.get("encoding") == "base64":
        return base64.b64decode(d["content"]).decode("utf-8", "replace")
    return None
