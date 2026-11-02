"""Submit a VERIFIED item: issue + PR together.

Every gate is re-checked at the write boundary. Progress is saved after each remote
step so a failure (e.g. issue created, PR failed) resumes instead of duplicating.
`execute=False` (default) only reports what would happen.
"""

from __future__ import annotations

import subprocess
import fcntl
from collections.abc import Callable
from pathlib import Path

from . import admission, evidence, contributing, dedupe, gh, identity, policy, policy_review, review, safety, vet
from .config import Config
from .limiter import DailyLimiter
from .queue import Item

DISCLOSURE = "\n\n---\n_This issue/PR was prepared with AI assistance and reviewed by a human before submission._"


class Refused(Exception):
    pass


def _run(cmd: list[str], cwd: str | None = None) -> str:
    if cmd[0] == "gh" and cmd[1:3] in (["issue", "create"], ["pr", "create"], ["pr", "comment"], ["repo", "fork"]):
        gh.pace_write()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        raise Refused(f"{' '.join(cmd[:3])}...: {p.stderr.strip()}")
    return p.stdout.strip()


def _base(cwd: str) -> str:
    return _run(["git", "merge-base", "HEAD", "origin/HEAD"], cwd)


def _identity_gate(cfg: Config, cwd: str, base: str, repo: str, fork: bool) -> None:
    problems = identity.check_login(cfg) + identity.check_worktree(cfg, cwd, base) + identity.check_upstream(cwd, repo)
    if fork:
        problems += identity.check_fork(cfg, cwd, repo)
    try:
        identity.require(problems)
    except identity.IdentityError as e:
        raise Refused(str(e)) from e


def _evidence_gate(it: Item) -> None:
    try:
        evidence.check(Path(it.clone), _base(it.clone), it.branch, it.verification)
    except evidence.StaleEvidence as e:
        raise Refused(str(e)) from e


def _admission_gate(it: Item, cfg: Config) -> dict:
    if not cfg.maintainer_admission:
        return {}
    base = _base(it.clone)
    paths = _run(["git", "diff", "--name-only", "--no-renames", f"{base}..HEAD"], it.clone).splitlines()
    numbers = _run(["git", "diff", "--numstat", "--no-renames", f"{base}..HEAD"], it.clone)
    try:
        return admission.check(it.repo, it.consent_issue, paths, numbers)
    except admission.Denied as e:
        raise Refused(f"maintainer admission: {e}") from e


def _ensure_signoff(cwd: str) -> None:
    base = _base(cwd)
    unsigned = _run(["git", "rev-list", "--grep=^Signed-off-by:", "--invert-grep", f"{base}..HEAD"], cwd)
    if unsigned:
        _run(["git", "rebase", "--signoff", base], cwd)


def _policy_files(repo: str) -> dict[str, str]:
    """Fail closed: if the repo's policy docs cannot be read, nothing is published."""
    try:
        return vet.policy_texts(repo)
    except gh.GhError as e:
        raise Refused(f"could not read {repo} policy docs ({e}); not publishing") from e


def _disclosure(cfg: Config, repo: str) -> tuple[bool, policy.Disclosure]:
    try:
        return policy.decide_disclosure(cfg.disclosure, _policy_files(repo))
    except policy.NeedsReview as e:
        raise Refused(f"needs your review: {e}") from e


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
    if limiter.remaining() <= 0 and not it.submitted.get("pr_url"):
        raise Refused("daily PR cap reached")
    why = safety.repo_allowed(cfg, it.repo, history)
    if why and not it.submitted.get("issue_url"):
        raise Refused(why)
    files = _policy_files(it.repo)
    pol = policy.scan_files(files)
    if pol.anti_ai:
        raise Refused(f"anti-AI policy in {pol.source}")
    why = policy_review.check(cfg, it.repo)
    if why:
        raise Refused(why)
    _disclosure(cfg, it.repo)  # surfaces an unclear or conflicting disclosure policy in the dry run
    if not it.submitted.get("issue_url"):
        ms = dedupe.find_matches(it.repo, it.issue_title, it.issue_body, it.path, [])
        if dedupe.is_duplicate(ms):
            raise Refused("duplicate found: " + ", ".join(f"#{m.number}({m.state})" for m in ms[:3]))
        recent = dedupe.recent_commit_hits(it.repo, it.path, sorted(dedupe.tokens(it.issue_title))[:6])
        if recent:
            raise Refused(f"recent commit already touches this: {recent[0]}")
    cwd = str(Path(it.clone))
    base = _base(cwd)
    _identity_gate(cfg, cwd, base, it.repo, fork=False)
    _evidence_gate(it)
    _admission_gate(it, cfg)
    changed = _run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd).splitlines()
    diff = _run(["git", "diff", f"{base}..HEAD"], cwd)
    bad = safety.check_diff(changed, diff)
    if bad:
        raise Refused("diff blocked: " + "; ".join(bad))
    found = review.review_branch(it.repo, cwd, base, it.pr_body, _run, gh)
    if review.blocking(found):
        raise Refused("self-review: " + "; ".join(review.blocking(found)))
    it.notes = [n for n in it.notes if not n.startswith("review: ")] + [f"review: {f.msg}" for f in found if f.level == "warn"]
    conv = contributing.parse(next((t for k, t in files.items() if "CONTRIBUTING" in k), ""))
    if conv.requires_assignment:
        raise Refused("repo requires assignment first: " + "; ".join(conv.notes))
    msg = _run(["git", "log", "-1", "--format=%B"], cwd)
    signed = bool(_run(["git", "rev-list", "--grep=^Signed-off-by:", f"{base}..HEAD"], cwd))
    if cfg.signoff_for(it.repo):
        pass  # sign-off approved for this repo; it is added right before the push
    elif signed:
        raise Refused("a commit carries Signed-off-by but sign-off is not approved for this repo; "
                      f"add {it.repo!r} to signoff_repos after reading its DCO, or remove the trailer")
    elif conv.dco:
        raise Refused(f"{it.repo} asks for a DCO Signed-off-by. That is your personal attestation: "
                      f"read the DCO, then add {it.repo!r} to signoff_repos to approve it for this repo")
    problems = [p for p in contributing.commit_message_ok(msg, conv) if "Signed-off-by" not in p]
    if problems:
        raise Refused("commit: " + "; ".join(problems))


def submit(it: Item, limiter: DailyLimiter, cfg: Config, audit: safety.Audit, execute: bool = False,
           save: Callable[[dict], None] | None = None) -> dict:
    """Serialize same-state writes and recover progress before checking or writing."""
    if not execute:
        return _submit(it, limiter, cfg, audit, execute, save)
    from .queue import Queue
    cfg.path("publication.lock").parent.mkdir(parents=True, exist_ok=True)
    with cfg.path("publication.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refused("another publication holds this state directory; retry after it finishes") from exc
        try:
            q = Queue(cfg.path("queue.json"))
            stored = q.items.get(it.id)
            if stored:
                it.submitted = dict(stored.submitted)
                if stored.status == "submitted":
                    it.status = "verified"  # recheck gates, then return saved URLs without new writes
            def persist(progress):
                it.submitted = dict(progress)
                # Reload to preserve unrelated queue updates; the publication lock owns this item's writes.
                current = Queue(cfg.path("queue.json"))
                if it.id in current.items:
                    current.set(it.id, submitted=dict(progress))
                    current.save()
                if save:
                    save(progress)
            return _submit(it, limiter, cfg, audit, execute, persist)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _submit(it: Item, limiter: DailyLimiter, cfg: Config, audit: safety.Audit, execute: bool = False,
            save: Callable[[dict], None] | None = None) -> dict:
    history = safety.effective_history(audit.read())
    preflight(it, limiter, cfg, history)
    plan = {"repo": it.repo, "issue": it.issue_title, "pr": it.pr_title, "branch": it.branch,
            "resume": bool(it.submitted.get("issue_url")),
            "disclosure": "add" if _disclosure(cfg, it.repo)[0] else "no"}
    plan["maintainer_admission"] = _admission_gate(it, cfg)
    if not execute:
        return {"dry_run": True, **plan}

    prog = dict(it.submitted)
    add_note, disc = _disclosure(cfg, it.repo)
    note = DISCLOSURE if add_note else ""
    cwd = str(Path(it.clone))
    _identity_gate(cfg, cwd, _base(cwd), it.repo, fork=False)  # re-check at the write boundary
    _evidence_gate(it)  # exact tested content again immediately before the first external write
    _admission_gate(it, cfg)  # current upstream consent, never cached
    me = gh.api("user", fresh=True)["login"]

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
        gh.pace_write()
        subprocess.run(["gh", "repo", "fork", it.repo, "--clone=false"], capture_output=True)
        fork = f"https://github.com/{me}/{it.repo.split('/')[1]}.git"
        have = subprocess.run(["git", "remote"], cwd=cwd, capture_output=True, text=True).stdout.split()
        _run(["git", "remote", "set-url" if "fork" in have else "add", "fork", fork], cwd)
        if cfg.signoff_for(it.repo):
            _ensure_signoff(cwd)
        _identity_gate(cfg, cwd, _base(cwd), it.repo, fork=True)  # the destination is the operator's own fork
        _admission_gate(it, cfg)
        _evidence_gate(it)  # signoff may rewrite commits, but must not change the tested tree
        _run(["git", "push", "-u", "fork", it.branch], cwd)
        progress(fork_pushed=True)

    if not prog.get("pr_url"):
        if limiter.remaining() <= 0:
            raise Refused("daily PR cap reached; existing issue/fork progress retained for a later day")
        body = f"{it.pr_body}\n\nCloses #{num}{note}"
        _admission_gate(it, cfg)
        draft = ["--draft"] if cfg.maintainer_admission else []
        url = _run(["gh", "pr", "create", *draft, "-R", it.repo, "--head", f"{me}:{it.branch}", "-t", it.pr_title, "-b", body], cwd)
        progress(pr_url=url)
        limiter.record()
        audit.log("pr_opened", repo=it.repo, pr=int(url.rsplit("/", 1)[-1]), url=url, item=it.id, state="open")
    return {"dry_run": False, "issue": prog["issue_url"], "pr": prog["pr_url"],
            "disclosure_added": add_note, "disclosure_policy": disc.status, "disclosure_source": disc.source}
