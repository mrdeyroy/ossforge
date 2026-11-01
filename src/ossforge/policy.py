"""Repo policy gate.

Repos whose docs forbid AI-assisted contributions are never targeted. They are
recorded as ``anti_ai`` so the operator can see them in the report; no issue,
comment or PR is ever created for them.

Keyword table adapted from oss-scout's anti-llm-policy (MIT).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ANTI_AI_KEYWORDS: tuple[str, ...] = (
    "no ai-generated", "no ai generated", "no ai-assisted", "no ai assisted",
    "no llm-generated", "no llm generated", "no copilot-generated",
    "no chatgpt-generated", "human-authored only", "human authored only",
    "human-written only", "human written only", "ai-free contributions",
    "llm-free contributions", "ai-generated code is not allowed",
    "ai-generated code will not be accepted", "do not submit ai-generated",
    "do not submit llm-generated", "do not use ai to", "do not use llms",
    "do not use copilot", "do not use chatgpt", "without ai assistance",
    "without llm assistance", "no use of generative ai", "ban on ai-generated",
    "prohibit ai-generated", "prohibits ai-generated",
    "not be completed by automated agents", "must not be done by automated agents",
    "tasks are for humans only", "do not generate code",
    "explicitly rejected the generative use of agents",
    "you are explicitly forbidden from modifying",
)

POLICY_FILES: tuple[str, ...] = (
    "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.md",
    "AGENTS.md", "AI_POLICY.md", ".github/AI_POLICY.md", "README.md",
)


@dataclass
class PolicyResult:
    anti_ai: bool
    matched: list[str] = field(default_factory=list)
    source: str | None = None


def scan_text(text: str, source: str | None = None) -> PolicyResult:
    hay = (text or "").lower()
    hits = [k for k in ANTI_AI_KEYWORDS if k in hay]
    return PolicyResult(bool(hits), hits, source if hits else None)


def scan_files(files: dict[str, str]) -> PolicyResult:
    """``files`` maps repo path -> text. First file with a match wins."""
    for path in POLICY_FILES:
        if path in files:
            r = scan_text(files[path], path)
            if r.anti_ai:
                return r
    return PolicyResult(False)


# Only contributor-facing policy documents can make disclosure mandatory. README and AGENTS.md
# are not treated as authority: AGENTS.md is written for tools, README for anyone.
DISCLOSURE_FILES: tuple[str, ...] = (
    "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md",
    "AI_POLICY.md", ".github/AI_POLICY.md",
)

_AI = re.compile(r"(?:\bai\b|\bllms?\b|copilot|chatgpt|claude|gemini|generative|machine[- ]generated)", re.I)
_VERB = re.compile(r"(?:disclos\w*|declare|indicate|acknowledge|mention|state|label)", re.I)
_ASK = re.compile(r"(?:\bmust\b|\bshould\b|\brequired?\b|\bplease\b|need to|\bask\b|expected|mandatory|\balways\b)", re.I)
_NEG = re.compile(r"(?:no need|not required|not necessary|optional|don'?t need|do not need|need not)", re.I)


def requires_disclosure(text: str) -> bool:
    """True when one sentence of the text asks contributors to disclose AI use (and does not waive it).

    Heuristic on purpose: it only decides whether to add a short note. Anti-AI bans are handled by scan_text.
    """
    for sent in re.split(r"[.!?\n]+", text or ""):
        if _AI.search(sent) and _VERB.search(sent) and _ASK.search(sent) and not _NEG.search(sent):
            return True
    return False


def disclosure_required(files: dict[str, str]) -> str | None:
    """Return the first authoritative policy file that asks for AI-use disclosure, or None."""
    for path in DISCLOSURE_FILES:
        if path in files and requires_disclosure(files[path]):
            return path
    return None


def want_disclosure(setting, files: dict[str, str]) -> bool:
    """``setting`` is True (always), False (never) or "auto" (only when the repo's docs ask for it)."""
    if isinstance(setting, str):
        v = setting.strip().lower()
        if v == "auto":
            return disclosure_required(files) is not None
        return v in ("true", "yes", "always", "on")
    return bool(setting)
