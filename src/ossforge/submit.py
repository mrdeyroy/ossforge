"""Submit a VERIFIED item: issue + PR together.

Every gate is re-checked at the write boundary. Progress is saved after each remote
step so a failure (e.g. issue created, PR failed) resumes instead of duplicating.
`execute=False` (default) only reports what would happen.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from . import contributing, dedupe, gh, policy, safety, vet
from .config import Config
from .limiter import DailyLimiter
from .queue import Item

DISCLOSURE = "\n\n---\n_This issue/PR was prepared with AI assistance and reviewed by a human before submission._"


class Refused(Exception):
    pass


def _run(cmd: list[str], cwd: str | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        raise Refused(f"{' '.join(cmd[:3])}...: {p.stderr.strip()}")
    return p.stdout.strip()


def _base(cwd: str) -> str:
    return _run(["git", "merge-base", "HEAD", "origin/HEAD"], cwd)


def _ensure_signoff(cwd: str) -> None:
    base = _base(cwd)
    unsigned = _run(["git", "rev-list", "--grep=^Signed-off-by:", "--invert-grep", f"{base}..HEAD"], cwd)
    if unsigned:
        _run(["git", "rebase", "--signoff", base], cwd)


def cla_status(repo: str, pr: int) -> str:
    """Read-only: link to the CLA bot's comment. Signing is always the contributor's own act."""
    for c in gh.api(f"repos/{repo}/issues/{pr}/comments", fresh=True) or []:
        if "cla" in c.get("body", "").lower():
            return c["html_url"]
    return ""


def preflight(it: Item, limiter: DailyLimiter, cfg: Config, history: list[dict]) -> None:
    try:
        safety.kill_switch(cfg)
    except safety.Blocked as e:
        raise Refused(str(e)) from e
    if it.status != "verified":
        raise Refused(f"status is {it.status!r}, must be 'verified'")
    if not (it.issue_title and it.issue_body and it.pr_title and it.pr_body and it.branch and it.clone):
        raise Refused("missing issue/PR text, branch or clone path")
    if limiter.remaining() <= 0 and not it.submitted.get("issue_url"):
        raise Refused("daily PR cap reached")
    why = safety.repo_allowed(cfg, it.repo, history)
    if why and not it.submitted.get("issue_url"):
        raise Refused(why)
    files = vet.policy_texts(it.repo)
    pol = policy.scan_files(files)
    if pol.anti_ai:
        raise Refused(f"anti-AI policy in {pol.source}")
    if not it.submitted.get("issue_url"):
        ms = dedupe.find_matches(it.repo, it.issue_title, it.issue_body, it.path, [])
        if dedupe.is_duplicate(ms):
            raise Refused("duplicate found: " + ", ".join(f"#{m.number}({m.state})" for m in ms[:3]))
        recent = dedupe.recent_commit_hits(it.repo, it.path, sorted(dedupe.tokens(it.issue_title))[:6])
        if recent:
            raise Refused(f"recent commit already touches this: {recent[0]}")
    cwd = str(Path(it.clone))
    base = _base(cwd)
    changed = _run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd).splitlines()
    diff = _run(["git", "diff", f"{base}..HEAD"], cwd)
    bad = safety.check_diff(changed, diff)
    if bad:
        raise Refused("diff blocked: " + "; ".join(bad))
    conv = contributing.parse(next((t for k, t in files.items() if "CONTRIBUTING" in k), ""))
    if conv.requires_assignment:
        raise Refused("repo requires assignment first: " + "; ".join(conv.notes))
    if not cfg.signoff:
        msg = _run(["git", "log", "-1", "--format=%B"], cwd)
        problems = contributing.commit_message_ok(msg, conv)
        if problems:
            raise Refused("commit: " + "; ".join(problems))


def submit(it: Item, limiter: DailyLimiter, cfg: Config, audit: safety.Audit, execute: bool = False,
           save: Callable[[dict], None] | None = None) -> dict:
    history = safety.effective_history(audit.read())
    preflight(it, limiter, cfg, history)
    plan = {"repo": it.repo, "issue": it.issue_title, "pr": it.pr_title, "branch": it.branch,
            "resume": bool(it.submitted.get("issue_url"))}
    if not execute:
        return {"dry_run": True, **plan}

    prog = dict(it.submitted)
    note = DISCLOSURE if cfg.disclosure else ""
    me = gh.api("user", fresh=True)["login"]
    cwd = str(Path(it.clone))

    def progress(**kw) -> None:
        prog.update(kw)
        if save:
            save(dict(prog))

    if not prog.get("issue_url"):
        url = _run(["gh", "issue", "create", "-R", it.repo, "-t", it.issue_title, "-b", it.issue_body + note])
        progress(issue_url=url)
        audit.log("issue_opened", repo=it.repo, url=url, item=it.id)
    num = prog["issue_url"].rsplit("/", 1)[-1]

    if not prog.get("fork_pushed"):
        subprocess.run(["gh", "repo", "fork", it.repo, "--clone=false"], capture_output=True)
        fork = f"https://github.com/{me}/{it.repo.split('/')[1]}.git"
        have = subprocess.run(["git", "remote"], cwd=cwd, capture_output=True, text=True).stdout.split()
        _run(["git", "remote", "set-url" if "fork" in have else "add", "fork", fork], cwd)
        if cfg.signoff:
            _ensure_signoff(cwd)
        _run(["git", "push", "-u", "fork", it.branch], cwd)
        progress(fork_pushed=True)

    if not prog.get("pr_url"):
        body = f"{it.pr_body}\n\nCloses #{num}{note}"
        url = _run(["gh", "pr", "create", "-R", it.repo, "--head", f"{me}:{it.branch}", "-t", it.pr_title, "-b", body], cwd)
        progress(pr_url=url)
        limiter.record()
        audit.log("pr_opened", repo=it.repo, pr=int(url.rsplit("/", 1)[-1]), url=url, item=it.id, state="open")
    return {"dry_run": False, "issue": prog["issue_url"], "pr": prog["pr_url"]}
