"""Local preparation origin guard, not an external permission or tamper boundary.

Absence of this marker never establishes permission. Public effects must still
check current policy, identity and owner authority independently.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MARKER = 'ossforge-local-preparation.json'


def marker_path(clone: Path) -> Path:
    dot = clone.resolve() / '.git'
    if dot.is_dir():
        common = dot
    elif dot.is_file():
        text = dot.read_text().strip()
        if not text.startswith('gitdir: '):
            raise ValueError('unreadable git directory; preserve checkout')
        gitdir = Path(text[8:])
        common = gitdir if gitdir.is_absolute() else clone / gitdir
    else:
        raise ValueError('cannot inspect preparation origin; preserve checkout')
    commondir = common / 'commondir'
    if commondir.is_file():
        target = Path(commondir.read_text().strip())
        common = target if target.is_absolute() else common / target
    return common.resolve() / MARKER


def public_guard(clone: str | Path) -> None:
    """Refuse accidental promotion of a preparation checkout into public work."""
    try:
        marker = marker_path(Path(clone))
    except (ValueError, FileNotFoundError):
        # Other existing evidence/identity checks own invalid checkout rejection.
        # No marker is never policy permission.
        return
    if marker.exists():
        raise ValueError('local-preparation checkout is publication-held; owner review cannot clear source restrictions')


def _load(cfg):
    import json
    try:
        record = json.loads(cfg.path('local_preparation.json').read_text())
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        raise ValueError('preparation journal unreadable; preserve it') from exc
    if (not isinstance(record, dict) or record.get('schema') != 1 or record.get('publication_hold') is not True
            or record.get('status') not in {'local_investigation', 'awaiting_owner_review'}
            or any(not isinstance(record.get(k), str) or not record[k] for k in ('id', 'repo', 'clone', 'base'))
            or not isinstance(record.get('policy_review'), dict)):
        raise ValueError('preparation journal invalid; preserve it')
    return record


def _save(cfg, record):
    import json
    path = cfg.path('local_preparation.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record, indent=2))
    tmp.replace(path)


def begin(cfg, lead, review):
    """Create a separate preparation checkout, never a public queue item."""
    import dataclasses
    import json
    from . import evidence, hunt, safety, submit
    safety.kill_switch(cfg)
    previous = _load(cfg)
    if previous:
        if previous['repo'] != lead['repo'] or previous['base'] != lead['revision']:
            raise ValueError('existing preparation must be inspected; never overwrite it')
        return task(cfg)
    local_cfg = dataclasses.replace(cfg, work_dir=str(Path(cfg.work_dir) / 'local-preparation'))
    root = hunt.clone(local_cfg, lead['repo'])
    tip = submit._run(['git', 'rev-parse', 'HEAD'], str(root))
    if tip != lead['revision']:
        raise ValueError('preparation revision differs; preserve checkout')
    receipt = evidence.capture(root, tip, [])
    record = {'schema': 1, 'id': 'local-preparation:' + lead['repo'], 'repo': lead['repo'],
              'clone': str(root.resolve()), 'base': tip, 'checkout': receipt,
              'status': 'local_investigation', 'publication_hold': True,
              'policy_review': review, 'policy': lead['policy'],
              'scope': 'local preparation only; no fork, push, issue, comment or PR'}
    marker = marker_path(root)
    if marker.exists():
        raise ValueError('preparation origin already present without journal; inspect it')
    marker.write_text(json.dumps({'schema': 1, 'publication_hold': True, 'repo': lead['repo']}))
    _save(cfg, record)
    return task(cfg)


def task(cfg):
    record = _load(cfg)
    if not record:
        return {'status': 'no_local_preparation'}
    from . import policy_review
    if not policy_review.preparation_review(cfg, record['repo'], policy_review.snapshot(
            record['repo'], extra_paths=record['policy_review'].get('extra_paths', []))):
        raise ValueError('local preparation policy changed or scope unresolved; preserve work')
    if not marker_path(Path(record['clone'])).exists():
        raise ValueError('preparation origin missing; preserve work and inspect')
    return {**record, 'result_schema': {'schema': 1, 'id': record['id'], 'base': record['base'],
            'branch': 'local-fix-branch', 'test_command': ['native-test', 'regression'],
            'check_commands': [['native-check']], 'failure_code': 1, 'consent_issue': 0,
            'issue_title': 'specific bug', 'issue_body': 'repro evidence', 'pr_title': 'specific fix',
            'pr_body': 'fix and actual native test results'}, 'next': 'inspect a genuine defect; use preparation-commit and preparation-verify; never agent-verify or submit',
            'warning': 'local preparation is not public permission or confirmed bug evidence'}


def commit(cfg, message):
    from . import identity
    record = task(cfg)
    if record.get('status') != 'local_investigation':
        raise ValueError('no active local investigation')
    return {'commit': identity.commit(cfg, record['clone'], message), 'publication_hold': True}


def complete(cfg, result):
    from . import evidence, verify
    import dataclasses
    import json
    record = task(cfg)
    if record.get('status') != 'local_investigation' or result['id'] != record['id']:
        raise ValueError('result must target the active local preparation, not a public item')
    if result.get('outcome') == 'hold' or result['base'] != record['base']:
        raise ValueError('preparation result needs the pinned base and a patch proposal')
    root = Path(record['clone'])
    current = evidence.capture(root, record['base'], [])
    if current['branch'] != result['branch']:
        raise ValueError('result branch differs from preparation checkout')
    outcome = verify.verify_fix(root, record['base'], Path('unused'), [],
        test_command=result['test_command'], check_commands=result['check_commands'], failure_code=result['failure_code'],
        isolation_mode=cfg.verification_isolation, readonly_paths=cfg.verification_readonly_paths)
    if not outcome.ok:
        return {'status': 'local_verification_failed', 'log': outcome.log, 'publication_hold': True}
    evidence.check(root, record['base'], result['branch'], outcome.evidence)
    patch = subprocess.run(['git', 'diff', '--binary', record['base'], 'HEAD'], cwd=root,
                           capture_output=True, check=True).stdout
    artifacts = cfg.path('local-preparation-artifacts')
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / 'change.patch').write_bytes(patch)
    (artifacts / 'drafts.json').write_text(json.dumps({k: result[k] for k in (
        'issue_title', 'issue_body', 'pr_title', 'pr_body')}, indent=2))
    record.update(status='awaiting_owner_review', verification=dataclasses.asdict(outcome),
                  artifacts=str(artifacts.resolve()))
    _save(cfg, record)
    return {**record, 'next': 'STOP this contribution before public effects; retain provenance and exact source restrictions. Independent eligible research may continue.'}
