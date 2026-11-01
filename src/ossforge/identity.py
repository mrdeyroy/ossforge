"""Identity gate: who is about to publish, and as whom the commits were written.

Checked before every publish (issue, fork push, PR, comment). Nothing here changes git or gh config: a
mismatch or a missing setting stops the write and tells the operator exactly what to correct.
Verified against: the authenticated gh login, the effective git author and committer in the work tree
(config files AND GIT_* environment overrides), every commit being published, the fork and upstream remotes.
"""

from __future__ import annotations

import re
import subprocess

from . import gh
from .config import Config

_IDENT = re.compile(r"^(?P<name>.*) <(?P<email>[^>]*)> ")


class IdentityError(Exception):
    pass


def _git(cwd: str, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    return p.stdout.strip() if p.returncode == 0 else ""


def expected(cfg: Config) -> tuple[str, str, str]:
    return cfg.github_user.strip(), cfg.git_name.strip(), cfg.git_email.strip()


def missing_settings(cfg: Config) -> list[str]:
    user, name, email = expected(cfg)
    return [k for k, v in (("github_user", user), ("git_name", name), ("git_email", email)) if not v]


def effective_idents(cwd: str) -> dict[str, tuple[str, str]]:
    """The author/committer git would stamp on a new commit right now (includes GIT_AUTHOR_* env overrides)."""
    out = {}
    for role, var in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        m = _IDENT.match(_git(cwd, "var", var) + " ")
        out[role] = (m["name"], m["email"]) if m else ("", "")
    return out


def check_login(cfg: Config) -> list[str]:
    user = cfg.github_user.strip()
    if not user:
        return ["github_user is not set in ossforge.yaml"]
    try:
        login = gh.api("user", fresh=True)["login"]
    except gh.GhError as e:
        return [f"could not read the authenticated gh account ({e})"]
    if login.lower() != user.lower():
        return [f"gh is logged in as {login!r} but ossforge is configured for {user!r}"]
    return []


def check_worktree(cfg: Config, cwd: str, base: str | None = None) -> list[str]:
    _, name, email = expected(cfg)
    problems = [f"{k} is not set in ossforge.yaml" for k in ("git_name", "git_email") if not getattr(cfg, k).strip()]
    if problems:
        return problems
    for role, (n, e) in effective_idents(cwd).items():
        if (n, e.lower()) != (name, email.lower()):
            problems.append(f"effective git {role} is {n} <{e}>, expected {name} <{email}>")
    if base:
        log = _git(cwd, "log", "--format=%an|%ae|%cn|%ce|%h", f"{base}..HEAD")
        for line in log.splitlines():
            an, ae, cn, ce, h = line.split("|")
            if (an, ae.lower()) != (name, email.lower()):
                problems.append(f"commit {h} author is {an} <{ae}>, expected {name} <{email}>")
            if (cn, ce.lower()) != (name, email.lower()):
                problems.append(f"commit {h} committer is {cn} <{ce}>, expected {name} <{email}>")
    return problems


def _owner_repo(url: str) -> str:
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
    return m.group(1).lower() if m else ""


def remote_slug(cwd: str, remote: str) -> str:
    return _owner_repo(_git(cwd, "config", "--get", f"remote.{remote}.url"))


def check_upstream(cwd: str, repo: str) -> list[str]:
    """The clone's origin must be the upstream the PR will target."""
    got = remote_slug(cwd, "origin")
    return [] if got == repo.lower() else [f"clone origin is {got or 'unknown'}, but the PR targets {repo}"]


def check_fork(cfg: Config, cwd: str, repo: str) -> list[str]:
    """The push destination must be the operator's own fork of the target repo, never upstream or someone else's."""
    got = remote_slug(cwd, "fork")
    want = f"{cfg.github_user.strip()}/{repo.split('/')[1]}".lower()
    if got != want:
        return [f"fork remote is {got or 'unset'}, expected {want}"]
    if got == repo.lower():
        return ["fork remote equals the upstream repo"]
    return []


def require(problems: list[str]) -> None:
    if problems:
        raise IdentityError("identity check failed: " + "; ".join(problems) +
                            ". Fix ossforge.yaml or the work tree's git identity, then retry. Nothing was published.")
