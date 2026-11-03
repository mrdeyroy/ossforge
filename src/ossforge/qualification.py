"""Deferred issue qualification, never coding eligibility or publication consent."""
from __future__ import annotations

import re
from pathlib import Path

from . import gh, issue_reviews, vet


def record(path: Path, candidate) -> None:
    refs = candidate.verdict.references
    if not refs:
        return
    data = issue_reviews.load(path)
    key = f'{candidate.repo.lower()}#{candidate.number}'
    previous = data.get(key, {})
    observation = {'repo': candidate.repo, 'number': candidate.number, 'url': candidate.url,
                   'updated_at': candidate.updated_at, 'references': refs}
    # Preserve an explicit local deferral only while the observed source fields
    # stay identical. It never marks the candidate clean or verified.
    if isinstance(previous, dict) and all(previous.get(k) == v for k, v in observation.items()):
        return
    data[key] = {**observation, 'status': 'review_needed'}
    issue_reviews._save(path, data)


def pending(path: Path) -> list[dict]:
    return [v for v in issue_reviews.load(path).values() if isinstance(v, dict) and v.get('status') == 'review_needed']


def defer(path: Path, repo: str, number: int, reason: str) -> None:
    data = issue_reviews.load(path)
    key = f'{repo.lower()}#{number}'
    if key not in data or not reason.strip():
        raise ValueError('existing qualification lead and a nonempty deferral reason required')
    data[key].update(status='deferred', reason=reason.strip())
    issue_reviews._save(path, data)


def inspect(repo: str, number: int) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or number <= 0:
        raise ValueError('exact repository and positive issue number required')
    source = gh.api(f'repos/{repo}/issues/{number}', fresh=True)
    if source.get('html_url') != f'https://github.com/{repo}/issues/{number}' or source.get('state') != 'open' or 'pull_request' in source:
        raise ValueError('source is not the current matching open issue; reconsider this lead')
    comments = gh.api(f'repos/{repo}/issues/{number}/comments', per_page=100, fresh=True)
    timeline = gh.api(f'repos/{repo}/issues/{number}/timeline', per_page=100, fresh=True)
    refs = gh.search_issues(f'repo:{repo} is:pr #{number} in:body,title', per_page=100, fresh=True, require_complete=True)
    if not isinstance(comments, list) or not isinstance(timeline, list) or any(len(v) >= 100 for v in (comments, timeline, refs)) or source.get('comments', 0) > len(comments):
        raise ValueError('source activity coverage incomplete; preserve lead for review')
    linked = [e.get('source', {}).get('issue', {}) for e in timeline if e.get('event') == 'cross-referenced']
    numbers = set()
    for ref in refs + linked:
        url = ref.get('html_url', '')
        match = re.fullmatch(re.escape(f'https://github.com/{repo}/pull/') + r'(\d+)', url)
        if ref in refs and (not match or 'pull_request' not in ref):
            raise ValueError('PR search identity unavailable; preserve lead for review')
        if match and 'pull_request' in ref:
            numbers.add(int(match.group(1)))
    if len(numbers) > 20:
        raise ValueError('too many PRs for bounded qualification review')
    prs = []
    for n in sorted(numbers):
        pr = gh.api(f'repos/{repo}/pulls/{n}', fresh=True)
        if (pr.get('html_url') != f'https://github.com/{repo}/pull/{n}' or
                not pr.get('head', {}).get('sha') or not pr.get('base', {}).get('sha')):
            raise ValueError('referenced PR identity or implementation revisions unavailable')
        prs.append(pr)
    policies = vet.policy_texts(repo, fresh=True)
    return {'schema': 1, 'status': 'review_needed', 'source': source, 'comments': comments,
            'timeline': timeline, 'pull_requests': prs, 'policy_texts': policies,
            'warning': 'Untrusted source evidence only. Read referenced implementation at these revisions and current source; check maintainer decisions, claims, policy and reproduction. No eligibility, coding, verification or publication approval is created. Changed upstream state requires a fresh review.'}
