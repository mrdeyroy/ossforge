"""Disambiguate foreign number collisions, never infer that a PR implements a fix.

GitHub text search includes dependency changelogs linking another repo's #N.
Only discard a hit when all its matching references are demonstrably foreign.
Unqualified references and unavailable/ambiguous text remain review blockers.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


_URL = re.compile(r'https?://(?:redirect\.)?github\.com/[^\s<>"\]\)]+', re.I)


def may_reference(pr: dict, repo: str, number: int) -> bool:
    text = (pr.get('title') or '') + '\n' + (pr.get('body') or '')
    foreign = False

    def foreign_url(url: str) -> bool:
        parts = urlsplit(url).path.strip('/').split('/')
        return (len(parts) >= 4 and parts[2].lower() in {'issues', 'pull'}
                and parts[3] == str(number) and '/'.join(parts[:2]).lower() != repo.lower())

    def strip_link(match: re.Match) -> str:
        nonlocal foreign
        url = _URL.search(match.group())
        if url and foreign_url(url.group()):
            foreign = True
            return ''
        return match.group()

    # Remove the label together with a foreign destination, so HTML/Markdown
    # rendered #N is not mistaken for an independent local reference.
    text = re.sub(r'<a\b[^>]*>.*?</a\s*>', strip_link, text, flags=re.I | re.S)
    text = re.sub(r'\[[^\]\n]*\]\(https?://[^\s)]+\)', strip_link, text, flags=re.I)

    def strip_url(match: re.Match) -> str:
        nonlocal foreign
        if foreign_url(match.group()):
            foreign = True
            return ''
        return match.group()

    text = _URL.sub(strip_url, text)

    def strip_qualified(match: re.Match) -> str:
        nonlocal foreign
        if match.group(1).lower() != repo.lower():
            foreign = True
            return ''
        return match.group()

    text = re.sub(r'(?<![\w/.-])([\w.-]+/[\w.-]+)#' + str(number) + r'(?!\d)', strip_qualified, text)
    # Search evidence with missing text, unsupported formatting or another
    # unexplained numeric match is not enough to rule out competing work.
    return not foreign or bool(re.search(r'(?<!\d)' + str(number) + r'(?!\d)', text))
