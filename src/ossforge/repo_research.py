"""Durable repo-first research leads, independent of the issue-search cursor.

Selection only collects sources; begin may clone a policy-reviewed repo and
propose records an unverified hypothesis. No patch execution or publication.
The IDE owns semantic diagnosis. Health and merge samples are not permission.
"""
from __future__ import annotations

import json
import hashlib
import fcntl
from contextlib import contextmanager
from dataclasses import asdict

from pathlib import Path

from . import acceptance, audit, dedupe, discovery, evidence, gh, hunt, policy_review, radar, repo_access, safety, submit
from .queue import Item, Queue, item_id
from .config import Config


class Invalid(ValueError):
    pass


@contextmanager
def locked(cfg: Config):
    """Share the existing state-run exclusion without rewriting its journal."""
    cfg.path('run.lock').parent.mkdir(parents=True, exist_ok=True)
    with cfg.path('run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Invalid('another run holds this state directory; preserve pending work') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load(cfg: Config) -> dict:
    try:
        data = json.loads(cfg.path('repo_research.json').read_text())
    except FileNotFoundError:
        return {'schema': 1, 'cursor': 0, 'lead': None}
    except (OSError, ValueError) as exc:
        raise Invalid('repo research state unreadable; preserve it before retry') from exc
    if (not isinstance(data, dict) or data.get('schema') != 1
            or type(data.get('cursor')) is not int or data['cursor'] < 0
            or (data.get('lead') is not None and not isinstance(data['lead'], dict))):
        raise Invalid('repo research state invalid; preserve it before retry')
    lead = data['lead']
    if lead is not None and (not isinstance(lead.get('repo'), str)
                             or not discovery._REPO.fullmatch(lead.get('repo', ''))
                             or lead.get('status') not in {'collecting', 'repo_review_needed', 'investigating'}):
        raise Invalid('repo research lead invalid; preserve it before retry')
    if lead and lead['status'] == 'investigating' and any(not lead.get(k) for k in
            ('clone', 'base', 'checkout', 'revision', 'revision_url', 'default_branch')):
        raise Invalid('investigation state incomplete; preserve it before retry')
    return data


def _save(cfg: Config, data: dict) -> None:
    path = cfg.path('repo_research.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _selection_scope(cfg: Config) -> str:
    return hashlib.sha256(json.dumps({'languages': cfg.languages, 'min_stars': cfg.min_stars,
        'min_repo_score': cfg.min_repo_score, 'preferred_repos': cfg.preferred_repos}, sort_keys=True).encode()).hexdigest()


def prepare(cfg: Config) -> dict:
    """One bounded repository selection and source collection, no issue query."""
    safety.kill_switch(cfg)
    data = load(cfg)
    if data['lead'] is not None:
        return data['lead']  # explicit refresh/defer, never silently replace a lead
    if len(cfg.languages) != 1:
        raise Invalid('repo-first research requires exactly one configured language')
    with gh.read_budget(cfg.discovery_read_budget_seconds):
        pool = discovery.discover_broad_repos(cfg, cfg.languages[0], data['cursor'] // 5)
        if not pool:
            raise Invalid('repository pool unavailable; cursor unchanged, not proof of no work')
        scope = _selection_scope(cfg)
        rejected = {d['repo'].lower() for d in data.get('deferred', [])
                    if d.get('scope', scope) == scope}
        ordered = pool[data['cursor'] % len(pool):] + pool[:data['cursor'] % len(pool)]
        repo = next((r for r in ordered if r.lower() not in rejected), None)
        if repo is None:
            data['exhausted'] = {'status': 'repo_pool_exhausted', 'scope': scope, 'pool': pool,
                                 'reason': 'all repositories in this bounded pool were deferred; inspect recorded reasons or explicitly choose another selection scope'}
            _save(cfg, data)
            return data['exhausted']
        data.pop('exhausted', None)
        # Persist identity before potentially slow evidence collection. A partial
        # read is a recoverable research lead, never a completed suitability pass.
        lead = {'repo': repo, 'status': 'collecting', 'pool': pool,
                'reason': 'source collection incomplete; refresh before assessment'}
        data['lead'] = lead
        _save(cfg, data)
    return refresh(cfg)


def refresh(cfg: Config) -> dict:
    safety.kill_switch(cfg)
    data = load(cfg)
    lead = data['lead']
    if not lead:
        raise Invalid('no selected repository; run research-repo first')
    repo = lead['repo']
    with gh.read_budget(cfg.discovery_read_budget_seconds):
        restriction = repo_access.pr_restriction(repo)
        health = radar.analyze(repo)
        outside = acceptance.evidence(repo)
        snapshot = policy_review.snapshot(repo)
        info = gh.api(f'repos/{repo}', fresh=True)
        branch = info.get('default_branch')
        if not branch or not info.get('html_url'):
            raise Invalid('default branch identity unavailable; preserve lead')
        tip = gh.api(f'repos/{repo}/commits/{branch}', fresh=True)
        if not tip.get('sha') or not tip.get('html_url'):
            raise Invalid('default branch revision unavailable; preserve lead')
    reasons = []
    if restriction:
        reasons.append(restriction)
    if health.score < cfg.min_repo_score:
        reasons.append('repository health below configured threshold')
    if snapshot['anti_ai']:
        reasons.append('literal contribution prohibition; do not target')
    if snapshot['agent_review']:
        reasons.append('agent-specific contribution restriction needs review')
    result = {**lead, 'status': 'repo_review_needed', 'url': info['html_url'],
              'default_branch': branch, 'revision': tip['sha'], 'revision_url': tip['html_url'],
              'health': asdict(health), 'outside_contributions': asdict(outside),
              'policy': snapshot, 'holds': reasons,
              'requirements': ['read full policy documents and linked contribution guides',
                               'merge samples and stars are not permission or bug proof',
                               'check feasibility of native reproduction before selecting work',
                               'IDE AI must inspect code, diagnose and reproduce a useful bug',
                               'search issues, all-state PRs and recent commits before a patch',
                               'issue age alone never clears claims, assignment or policy',
                               'no code handoff or publication approval is created here']}
    data['lead'] = result
    _save(cfg, data)
    return result


def defer(cfg: Config, reason: str) -> dict:
    if not reason.strip():
        raise Invalid('a source-backed reason is required')
    data = load(cfg)
    if not data['lead']:
        raise Invalid('no selected repository to defer')
    history = data.setdefault('deferred', [])
    history.append({'repo': data['lead']['repo'], 'reason': reason,
                    'revision': data['lead'].get('revision'), 'scope': _selection_scope(cfg),
                    'freshness': 'until explicit selection-scope change; not a permanent claim about upstream'})
    data.update(cursor=data['cursor'] + 1, lead=None)
    _save(cfg, data)
    return {'status': 'deferred', 'reason': reason, 'cursor': data['cursor']}


def begin(cfg: Config) -> dict:
    """Policy-reviewed, source-pinned clean checkout for IDE investigation.

    No finding, queue item, patch or permission is manufactured by this step.
    """
    lead = refresh(cfg)
    if lead['holds']:
        raise Invalid('; '.join(lead['holds']))
    why = policy_review.check(cfg, lead['repo'], lead['policy'])
    if why:
        raise Invalid(why)
    try:
        route = policy_review.publication_route(cfg, lead['repo'])
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    if route not in {'issue_pr', 'pr_only'}:
        raise Invalid('contribution discussion/permission prerequisite unresolved; no coding investigation')
    history = safety.Audit(cfg.path('audit.jsonl')).read()
    blocked = safety.repo_allowed(cfg, lead['repo'], safety.effective_history(history))
    if blocked:
        raise Invalid(blocked)
    try:
        clone = hunt.clone(cfg, lead['repo'])
    except (RuntimeError, OSError) as exc:
        raise Invalid(f'checkout unavailable; preserve it and inspect: {exc}') from exc
    tip = submit._run(['git', 'rev-parse', 'HEAD'], str(clone))
    if tip != lead['revision']:
        raise Invalid('checkout differs from current selected revision; preserve it and inspect, never reset')
    try:
        snapshot = evidence.capture(clone, tip, [])
    except evidence.StaleEvidence as exc:
        raise Invalid(f'checkout changed; preserve it and inspect: {exc}') from exc
    data = load(cfg)
    # Deterministic local hints come first. They save broad source reads, but
    # empty output is not proof that the repo has no defects. No AI is invoked.
    findings = audit.scan_tree(clone)
    hints = [asdict(f) | {'snippet': hunt.snippet(clone, f.path, f.line, 2)} for f in findings[:8]]
    data['lead'] = {**lead, 'status': 'investigating', 'clone': str(clone.resolve()),
                    'base': tip, 'checkout': snapshot, 'hints': hints,
                    'scan': {'method': 'builtin Python AST candidate scan', 'found': len(findings),
                             'shown': len(hints), 'coverage': 'finite detectors, not semantic bug completeness'},
                    'next': 'review compact deterministic hints first; use targeted IDE reasoning for unresolved diagnosis, not a whole-repo dump'}
    _save(cfg, data)
    return data['lead']


def propose(cfg: Config, path: str, line: int, detail: str) -> dict:
    """An IDE's source-reviewed hypothesis, not a verified bug or publication.

    Deliberately for new code findings only. Existing issue adoption uses the
    existing fresh vet route; age or textual similarity is not an exemption.
    """
    safety.kill_switch(cfg)
    data = load(cfg)
    lead = data['lead']
    if not lead or lead['status'] != 'investigating':
        raise Invalid('begin a policy-reviewed repo investigation before proposing code work')
    if not detail.strip() or len(detail) > 4000 or '\x00' in detail or line < 1:
        raise Invalid('a specific bounded candidate description and positive line are required')
    rel = Path(path)
    root = Path(lead['clone'])
    file = root / rel
    if (rel.is_absolute() or '..' in rel.parts or not file.is_file()
            or file.is_symlink() or not file.resolve().is_relative_to(root.resolve())):
        raise Invalid('candidate path must be a real file inside the selected checkout')
    if line > len(file.read_text(errors='replace').splitlines()):
        raise Invalid('candidate line is outside the selected file')
    try:
        current = evidence.capture(root, lead['base'], [])
    except evidence.StaleEvidence as exc:
        raise Invalid(f'investigation checkout changed; preserve it and inspect: {exc}') from exc
    if any(current[k] != lead['checkout'][k] for k in ('tree', 'branch', 'base')):
        raise Invalid('investigation checkout changed; preserve it and refresh before proposing')
    why = policy_review.check(cfg, lead['repo'])
    if why:
        raise Invalid(why)
    blocked = safety.repo_allowed(cfg, lead['repo'], safety.effective_history(safety.Audit(cfg.path('audit.jsonl')).read()))
    if blocked:
        raise Invalid(blocked)
    with gh.read_budget(cfg.discovery_read_budget_seconds):
        restriction = repo_access.pr_restriction(lead['repo'])
        if restriction:
            raise Invalid(restriction)
        tip = gh.api(f"repos/{lead['repo']}/commits/{lead['default_branch']}", fresh=True)
        if tip.get('sha') != lead['revision']:
            raise Invalid('upstream changed during investigation; preserve checkout and refresh before proposing')
        matches = dedupe.find_matches(lead['repo'], detail, detail, path, [], strict=True)
        commits = dedupe.recent_commit_hits(lead['repo'], path, dedupe.evidence_terms(detail, detail), strict=True)
    if matches or commits:
        raise Invalid('possible existing work needs source review before coding; no automatic duplicate clearance or issue-age exemption')
    queue = Queue(cfg.path('queue.json'))
    id_ = item_id(lead['repo'], path, 'ide-hypothesis', line)
    if id_ in queue.items:
        raise Invalid('candidate already exists; inspect its current state instead of replacing it')
    item = Item(id_, lead['repo'], path, line, 'ide-hypothesis', detail.strip(),
                status='clean', clone=str(root), notes=['IDE source-reviewed hypothesis, not bug proof',
                                                     lead['revision_url']], snippet=hunt.snippet(root, path, line))
    queue.add(item)
    queue.save()
    return {'status': 'candidate', 'id': id_, 'warning': 'must check current issues/PRs/commits and reproduce before editing; submit independently rechecks duplicates'}


def checkpoint(cfg: Config, prefix: list[str]) -> dict:
    data = load(cfg)
    if not data['lead'] and data.get('exhausted', {}).get('scope') == _selection_scope(cfg):
        return {'schema': 1, 'local_only': True, **data['exhausted']}
    if data['lead']:
        # Checkpoint is routing context, not a repeated dump of all documents.
        lead = dict(data['lead'])
        if lead.get('policy'):
            lead['policy'] = {**lead['policy'], 'docs': [
                {k: d[k] for k in ('path', 'url', 'sha')} for d in lead['policy']['docs']]}
        data = {**data, 'lead': lead}
    if data['lead'] and data['lead']['status'] == 'investigating':
        return {'schema': 1, 'status': 'repo_investigation', 'local_only': True, 'lead': data['lead'],
                'next': 'IDE: inspect selected code for a useful defect; research-propose PATH LINE --detail HYPOTHESIS, or research-repo --defer REASON',
                'warning': 'no bug is confirmed; do not edit before current duplicate/claim/policy review and reproduction'}
    return {'schema': 1, 'status': 'repo_research', 'local_only': True,
            'lead': data['lead'], 'next_argv': prefix + ['research-repo'] if not data['lead'] else
            prefix + ['research-repo', '--refresh'],
            'after_source_review_argv': prefix + ['research-repo', '--begin'] if data['lead'] else None,
            'warning': 'repository research, not a code task or permission; inspect sources and policy before proceeding'}
