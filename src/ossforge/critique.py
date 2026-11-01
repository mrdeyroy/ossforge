"""Open-PR critique: score merge likelihood, scan the PR's changed lines for
bug/perf candidates, and DRAFT a respectful maintainer comment.

Nothing here posts. The draft is for human approval (Agent.md Template A).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import audit, gh, predictor


@dataclass
class Critique:
    repo: str
    number: int
    title: str
    author: str
    prediction: predictor.PRPrediction
    findings: list[audit.Finding] = field(default_factory=list)
    draft: str = ""


def _age_days(created: str) -> float:
    from .radar import _days
    from datetime import datetime, timezone

    return _days(created, datetime.now(timezone.utc).isoformat()) or 0.0


def signals(repo: str, number: int) -> tuple[dict, predictor.PRSignals, list[dict]]:
    pr = gh.api(f"repos/{repo}/pulls/{number}")
    files = gh.api(f"repos/{repo}/pulls/{number}/files", per_page=100) or []
    reviews = gh.api(f"repos/{repo}/pulls/{number}/reviews") or []
    decision = None
    for r in reviews:
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED"):
            decision = r["state"]
    checks = gh.api(f"repos/{repo}/commits/{pr['head']['sha']}/check-runs").get("check_runs", [])
    failing = any(c.get("conclusion") in ("failure", "timed_out", "cancelled") for c in checks)
    sig = predictor.PRSignals(
        review_decision=decision,
        is_draft=bool(pr.get("draft")),
        conflicting=pr.get("mergeable_state") == "dirty",
        ci_failing=failing,
        changed_files=pr.get("changed_files", len(files)),
        additions=pr.get("additions", 0),
        touches_tests=any(predictor.is_test_path(f["filename"]) for f in files),
        age_days=_age_days(pr["created_at"]),
    )
    return pr, sig, files


def added_line_findings(repo: str, pr: dict, files: list[dict]) -> list[audit.Finding]:
    """Scan only .py files the PR touches, at the PR head, keeping findings on added lines."""
    out: list[audit.Finding] = []
    head = pr["head"]["sha"]
    for f in files:
        if not f["filename"].endswith(".py") or f.get("status") == "removed":
            continue
        text = gh.file_text_at(repo, f["filename"], head)
        if not text:
            continue
        added = _added_lines(f.get("patch", ""))
        out += [x for x in audit.scan_source(text, f["filename"]) if x.line in added]
    return out


def _added_lines(patch: str) -> set[int]:
    lines: set[int] = set()
    cur = 0
    for ln in patch.splitlines():
        if ln.startswith("@@"):
            cur = int(ln.split("+")[1].split(",")[0].split(" ")[0]) - 1
        elif ln.startswith("+") and not ln.startswith("+++"):
            cur += 1
            lines.add(cur)
        elif not ln.startswith("-"):
            cur += 1
    return lines


def draft_comment(c: Critique, alternative: str = "") -> str:
    """Template A. Only states what was measured; `alternative` must be supplied
    (and benchmarked) by whoever reviews the draft."""
    obs = "\n".join(f"- `{f.path}:{f.line}` {f.detail}" for f in c.findings) or "- (no automated findings; add manual observations)"
    return (
        f"Hi @{c.author},\n\n"
        f"Thanks for working on #{c.number}! While reading the change I noticed a few things worth a look:\n\n"
        f"{obs}\n\n"
        f"Suggested alternative:\n{alternative or '- <describe the better approach and show a benchmark or complexity comparison>'}\n\n"
        "Happy to share a patch or collaborate if that would help.\n"
    )


def critique(repo: str, number: int) -> Critique:
    pr, sig, files = signals(repo, number)
    c = Critique(repo, number, pr["title"], pr["user"]["login"], predictor.score_pr(sig))
    c.findings = added_line_findings(repo, pr, files)
    c.draft = draft_comment(c)
    return c
