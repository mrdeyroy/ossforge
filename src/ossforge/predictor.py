"""Merge-likelihood score for an open PR (0-100), ported from GitSense predictor."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PRSignals:
    review_decision: str | None
    is_draft: bool
    conflicting: bool
    ci_failing: bool
    changed_files: int
    additions: int
    touches_tests: bool
    age_days: float | None


@dataclass
class PRPrediction:
    score: int
    label: str
    notes: list[str] = field(default_factory=list)


def score_pr(s: PRSignals) -> PRPrediction:
    score, notes = 50, []
    d = (s.review_decision or "").upper()
    if d == "APPROVED":
        score += 28
        notes.append("already approved")
    elif d == "CHANGES_REQUESTED":
        score -= 25
        notes.append("changes requested")
    else:
        notes.append("no review decision yet")
    if s.is_draft:
        score -= 18
        notes.append("still a draft")
    if s.conflicting:
        score -= 18
        notes.append("has merge conflicts")
    if s.ci_failing:
        score -= 20
        notes.append("CI failing")
    else:
        score += 8
    if s.changed_files <= 3 and s.additions <= 100:
        score += 15
        notes.append("small, focused diff")
    elif s.changed_files >= 30 or s.additions >= 1000:
        score -= 15
        notes.append("large diff")
    if s.touches_tests:
        score += 10
        notes.append("includes tests")
    else:
        notes.append("no test changes")
    if s.age_days is not None and s.age_days > 60:
        score -= 12
        notes.append("open 60+ days, may be stalled")
    score = max(0, min(100, score))
    label = "likely" if score >= 70 else "uncertain" if score >= 45 else "unlikely"
    return PRPrediction(score, label, notes)


def is_test_path(path: str) -> bool:
    p = path.lower()
    return "test" in p.split("/")[-1] or "/tests/" in f"/{p}" or "/test/" in f"/{p}" or "spec" in p.split("/")[-1]
