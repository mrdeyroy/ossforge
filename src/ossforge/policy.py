"""Repo policy gate.

Repos whose docs forbid AI-assisted contributions are never targeted. They are
recorded as ``anti_ai`` so the operator can see them in the report; no issue,
comment or PR is ever created for them.

Keyword table adapted from oss-scout's anti-llm-policy (MIT).
"""

from __future__ import annotations

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
