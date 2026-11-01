"""Read a repo's CONTRIBUTING/PR template and extract the conventions we must follow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Conventions:
    dco: bool = False
    cla: bool = False
    conventional_commits: bool = False
    branch_hint: str = ""
    test_commands: list[str] = field(default_factory=list)
    lint_commands: list[str] = field(default_factory=list)
    issue_first: bool = False          # asks for an issue/discussion before larger changes
    requires_assignment: bool = False  # must be assigned before opening a PR
    pr_template: str = ""
    notes: list[str] = field(default_factory=list)


CMD_RE = re.compile(r"^\s*(?:\$\s*)?((?:pytest|python -m pytest|tox|nox|make (?:test|check|lint)|npm (?:run )?test|"
                    r"pnpm (?:run )?test|yarn test|cargo test|go test[^\n]*|ruff[^\n]*|flake8[^\n]*|black[^\n]*|mypy[^\n]*|"
                    r"npm run lint|eslint[^\n]*|cargo clippy[^\n]*)[^\n]*)$", re.M)


def parse(contributing: str, pr_template: str = "") -> Conventions:
    t = contributing or ""
    low = t.lower()
    c = Conventions(pr_template=pr_template or "")
    c.dco = bool(re.search(r"signed-off-by|git commit (?:-s|--signoff)|developer certificate of origin|\bdco\b", low))
    c.cla = bool(re.search(r"contributor licen[sc]e agreement|\bcla\b", low))
    c.conventional_commits = bool(re.search(r"conventional commits?|\b(?:feat|fix)\(?[a-z-]*\)?:\s", low))
    m = re.search(r"branch(?:es)? (?:name|naming)[^\n]*\n+[^\n]*`([^`]+)`", t, re.I)
    if m:
        c.branch_hint = m.group(1)
    for cmd in CMD_RE.findall(t):
        cmd = cmd.strip()
        bucket = c.lint_commands if re.match(r"(ruff|flake8|black|mypy|eslint|npm run lint|cargo clippy|make (check|lint))", cmd) else c.test_commands
        if cmd not in bucket:
            bucket.append(cmd)
    c.issue_first = bool(re.search(r"(open|create|file) an issue (first|before)|discuss[^\n]{0,40}before|wait for a reply", low))
    c.requires_assignment = bool(re.search(r"(must|need to|should) be assigned|wait (to be )?assigned|assigned to you before", low))
    if c.requires_assignment:
        c.notes.append("repo asks to be assigned first: comment on the issue and wait; do not open a PR yet")
    if c.issue_first:
        c.notes.append("repo wants an issue/discussion before larger changes")
    return c


def commit_message_ok(msg: str, c: Conventions) -> list[str]:
    problems = []
    first = msg.splitlines()[0] if msg else ""
    if c.conventional_commits and not re.match(r"^(feat|fix|perf|test|docs|refactor|chore|ci|build|style)(\([^)]+\))?!?: .+", first):
        problems.append("subject is not a Conventional Commit")
    if c.dco and "Signed-off-by:" not in msg:
        problems.append("missing Signed-off-by (DCO)")
    return problems
