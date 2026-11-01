"""Learning loop: per-detector precision (from verify/reject decisions) and per-repo merge
outcomes. Calibration idea from GitSense; personalization idea from oss-scout.
"""

from __future__ import annotations

import json
from pathlib import Path

from .audit import Finding

KIND_PRIOR = {  # prior probability that a finding of this kind is a real, fileable bug
    "mutable-default": 0.15, "swallowed-exception": 0.10, "bare-except": 0.15, "eq-none": 0.05,
    "is-literal": 0.3, "list-membership-in-loop": 0.1, "pop0-in-loop": 0.05,
    "async-foreach": 0.45, "async-promise-executor": 0.4, "empty-catch": 0.1,
}


class Stats:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("kinds", {})
        self.d.setdefault("repos", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.d, indent=1), encoding="utf-8")

    def record_kind(self, kind: str, confirmed: bool) -> None:
        k = self.d["kinds"].setdefault(kind, {"yes": 0, "no": 0})
        k["yes" if confirmed else "no"] += 1

    def precision(self, kind: str) -> float:
        """Beta(prior*4, (1-prior)*4) smoothed hit rate."""
        p = KIND_PRIOR.get(kind, 0.1)
        k = self.d["kinds"].get(kind, {"yes": 0, "no": 0})
        return (k["yes"] + p * 4) / (k["yes"] + k["no"] + 4)

    def record_repo(self, repo: str, outcome: str) -> None:
        r = self.d["repos"].setdefault(repo, {"merged": 0, "closed": 0})
        if outcome == "merged":
            r["merged"] += 1
        elif outcome == "closed_unmerged":
            r["closed"] += 1

    def set_history(self, repo: str, merged: int, closed_imported: int) -> None:
        """Idempotent import of your GitHub history. Closed-unmerged is stored for display only:
        a closure can mean duplicate, superseded or withdrawn, so it never lowers a repo's score.
        Outcomes ossforge itself recorded (`closed`) are left untouched."""
        r = self.d["repos"].setdefault(repo, {"merged": 0, "closed": 0})
        r["merged_imported"] = merged
        r["closed_imported"] = closed_imported

    def repo_boost(self, repo: str) -> int:
        """Repos that merged us before are worth more (oss-scout 'merged' strategy)."""
        r = self.d["repos"].get(repo)
        if not r:
            return 0
        merged = max(r.get("merged", 0), r.get("merged_imported", 0))  # same PRs can appear in both: no double count
        return min(20, 10 * merged) - min(30, 15 * r.get("closed", 0))


def rank(findings: list[Finding], stats: Stats) -> list[tuple[float, Finding]]:
    def score(f: Finding) -> float:
        s = stats.precision(f.kind)
        parts = f.path.split("/")
        if any(x in {"src", "lib", "core", "pkg"} for x in parts):
            s *= 1.3
        if f.severity == "perf":
            s *= 0.7
        return round(s, 3)

    return sorted(((score(f), f) for f in findings), key=lambda t: -t[0])
