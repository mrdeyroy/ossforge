"""Post an approved critique comment on someone else's PR. Gated; never automatic."""

from __future__ import annotations

import subprocess

from . import gh, policy, safety, vet
from .config import Config

NOTE = "\n\n_This review was prepared with AI assistance and checked by a human before posting._"


class Refused(Exception):
    pass


def post(cfg: Config, audit: safety.Audit, repo: str, pr: int, body: str, execute: bool = False) -> str:
    try:
        safety.kill_switch(cfg)
    except safety.Blocked as e:
        raise Refused(str(e)) from e
    if any(r.get("event") == "critique_posted" and r["repo"] == repo and r["pr"] == pr for r in audit.read()):
        raise Refused("already critiqued this PR once; a second comment is noise")
    try:
        files = vet.policy_texts(repo)
    except gh.GhError as e:
        raise Refused(f"could not read policy docs ({e}); not posting") from e
    pol = policy.scan_files(files)
    if pol.anti_ai:
        raise Refused(f"anti-AI policy in {pol.source}")
    if "<describe" in body or "<" in body and ">" in body and "placeholder" in body.lower():
        raise Refused("draft still contains placeholders")
    text = body + (NOTE if policy.want_disclosure(cfg.disclosure, files) else "")
    if not execute:
        return "dry-run:\n" + text
    gh.pace_write()
    p = subprocess.run(["gh", "pr", "comment", str(pr), "-R", repo, "-b", text], capture_output=True, text=True)
    if p.returncode:
        raise Refused(p.stderr.strip())
    audit.log("critique_posted", repo=repo, pr=pr)
    return p.stdout.strip()
