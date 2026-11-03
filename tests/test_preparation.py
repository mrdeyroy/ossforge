import subprocess
from pathlib import Path

import pytest

from ossforge import preparation, policy_review, repo_research, driver
from ossforge.config import Config
from ossforge.queue import Queue, Item


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'user.email', 'test@example.invalid')
    (root / '.git' / 'config').write_text((root / '.git' / 'config').read_text() + '\n[remote \"origin\"]\n\turl = https://github.com/org/repo.git\n')
    (root / 'a.py').write_text('def value(): return 0\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'base')
    base = git(root, 'rev-parse', 'HEAD')
    cfg = Config(state_dir=str(tmp_path / 'state'), work_dir=str(tmp_path / 'work'), kill_file=str(tmp_path / 'STOP'), github_user='test', git_name='Test', git_email='test@example.invalid')
    snap = {'repo': 'org/repo', 'docs': [{'path': 'LICENSE', 'sha': 'pinned', 'url': 'https://example.test/LICENSE', 'text': 'modification allowed'}], 'scanned_locations': ['LICENSE'], 'anti_ai': True, 'agent_review': []}
    rec = policy_review.record(cfg, 'org/repo', snap, 'Independent local modification licensed; no upstream contribution.', prohibited=True, local_preparation='allowed')
    monkeypatch.setattr(policy_review, 'snapshot', lambda *a, **kw: snap)
    from ossforge import identity
    monkeypatch.setattr(identity, 'check_login', lambda *a: [])
    monkeypatch.setattr(preparation, 'marker_path', preparation.marker_path)
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: root)
    lead = {'repo': 'org/repo', 'revision': base, 'policy': snap}
    preparation.begin(cfg, lead, rec)
    return cfg, root, base, snap


def test_separate_journal_and_public_guard(prepared):
    cfg, root, base, snap = prepared
    assert not Queue(cfg.path('queue.json')).items
    assert preparation.task(cfg)['status'] == 'local_investigation'
    with pytest.raises(ValueError, match='publication-held'):
        preparation.public_guard(root)
    other = root.parent / 'worktree'
    git(root, 'worktree', 'add', '-b', 'other', str(other))
    with pytest.raises(ValueError, match='publication-held'):
        preparation.public_guard(other)
    q = Queue(cfg.path('queue.json'))
    q.add(Item('a', 'org/repo', 'a.py', 1, 'bug', 'candidate', status='clean', clone=str(root)))
    with pytest.raises(driver.Invalid, match='publication-held'):
        driver.task(q)


def test_policy_change_and_generic_accept_dont_clear_hold(prepared):
    cfg, root, base, snap = prepared
    policy_review.record(cfg, 'org/repo', snap, 'owner approved', prohibited=False)
    with pytest.raises(ValueError, match='scope unresolved'):
        preparation.task(cfg)
    with pytest.raises(ValueError, match='publication-held'):
        preparation.public_guard(root)


def test_native_verification_stays_outside_public_queue(prepared, monkeypatch):
    cfg, root, base, snap = prepared
    git(root, 'checkout', '-b', 'fix')
    (root / 'a.py').write_text('def value(): return 1\n')
    (root / 'test_value.py').write_text('from a import value\nassert value() == 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'fix and regression')
    import sys
    result = dict(schema=1, id='local-preparation:org/repo', base=base, branch='fix', test_command=[sys.executable, 'test_value.py'], check_commands=[], failure_code=1, issue_title='bug', issue_body='repro', pr_title='fix', pr_body='test', consent_issue=0)
    # Native lint must be a real command, not an unavailable auto install.
    result['check_commands'] = [[sys.executable, '-c', 'pass']]
    out = preparation.complete(cfg, result)
    assert out['status'] == 'awaiting_owner_review' and out['publication_hold']
    assert out['verification']['failed_without_fix'] and out['verification']['passed_with_fix']
    assert Path(out['artifacts'], 'change.patch').read_text().startswith('diff --git')
    assert not Queue(cfg.path('queue.json')).items
    from ossforge import agent_next
    checkpoint = agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'cfg.yml')
    assert checkpoint['status'] == 'awaiting_owner_review'
    assert 'STOP' in preparation.task(cfg)['next']
    assert 'result_schema' not in preparation.task(cfg)


def test_missing_or_stale_scope_not_permission(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    snap = {'docs': [{'path': 'LICENSE', 'sha': '1', 'url': 'https://example.test/license'}], 'scanned_locations': []}
    assert policy_review.preparation_review(cfg, 'org/repo', snap) is None
    policy_review.record(cfg, 'org/repo', snap, 'local modification licensed', prohibited=True, local_preparation='allowed')
    assert policy_review.preparation_review(cfg, 'org/repo', snap)
    snap['docs'][0]['sha'] = '2'
    assert policy_review.preparation_review(cfg, 'org/repo', snap) is None


def test_conditional_begin_routes_only_source_reviewed_scope(prepared, monkeypatch):
    cfg, root, base, snap = prepared
    lead = {'repo': 'org/repo', 'revision': base, 'policy': snap,
            'holds': ['literal contribution prohibition; do not target'],
            'code_suitability': {'status': 'native_candidate'}}
    monkeypatch.setattr(repo_research, 'refresh', lambda *a: lead)
    assert repo_research.begin(cfg)['status'] == 'local_investigation'
    assert not Queue(cfg.path('queue.json')).items
    policy_review.record(cfg, 'org/repo', snap, 'unresolved local scope', prohibited=True)
    with pytest.raises(repo_research.Invalid, match='literal contribution prohibition'):
        repo_research.begin(cfg)
    policy_review.record(cfg, 'org/repo', snap, 'independent local modification allowed', prohibited=True, local_preparation='allowed')
    lead['holds'].append('repository health below configured threshold')
    with pytest.raises(repo_research.Invalid, match='health'):
        repo_research.begin(cfg)


def test_submit_guard_precedes_network_and_owner_approval(prepared, monkeypatch):
    from ossforge import submit, safety
    from ossforge.limiter import DailyLimiter
    cfg, root, base, snap = prepared
    item = Item('a', 'org/repo', 'a.py', 1, 'bug', 'candidate', status='verified', clone=str(root))
    monkeypatch.setattr(submit, '_publication_mode', lambda *a: pytest.fail('publication mode reached'))
    with pytest.raises(submit.Refused, match='publication-held'):
        submit.preflight(item, DailyLimiter(cfg.path('daily.json'), 2), cfg, [])
    Path(cfg.kill_file).write_text('STOP')
    with pytest.raises(safety.Blocked):
        preparation.begin(cfg, {'repo': 'org/repo'}, {})


def test_public_guard_malformed_marker_and_read_only_worktree(prepared):
    cfg, root, base, snap = prepared
    preparation.marker_path(root).write_text('malformed still held')
    with pytest.raises(ValueError, match='publication-held'):
        preparation.public_guard(root)


def test_bad_journal_and_missing_marker_preserve_work(prepared):
    cfg, root, base, snap = prepared
    original = (root / 'a.py').read_bytes()
    preparation.marker_path(root).unlink()
    with pytest.raises(ValueError, match='origin missing'):
        preparation.task(cfg)
    assert (root / 'a.py').read_bytes() == original
    cfg.path('local_preparation.json').write_text('{invalid')
    with pytest.raises(ValueError, match='journal unreadable'):
        preparation._load(cfg)


def test_orphan_history_not_an_actionable_task(prepared):
    cfg, root, base, snap = prepared
    git(root, 'checkout', '--orphan', 'unrelated')
    git(root, 'rm', '-rf', '.')
    (root / 'unrelated.py').write_text('x = 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'unrelated history')
    with pytest.raises(ValueError, match='pinned base'):
        preparation.task(cfg)


def test_wrong_commit_identity_cannot_export(prepared):
    from ossforge import identity
    cfg, root, base, snap = prepared
    git(root, 'checkout', '-b', 'fix')
    (root / 'a.py').write_text('def value(): return 1\n')
    (root / 'test_value.py').write_text('from a import value\nassert value() == 1\n')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Someone Else', '-c', 'user.email=else@example.invalid', 'commit', '-m', 'wrong identity')
    result = preparation.task(cfg)['result_schema']
    result.update(branch='fix', test_command=['python', 'test_value.py'])
    with pytest.raises(identity.IdentityError, match='identity check failed'):
        preparation.complete(cfg, result)
    assert not cfg.path('local-preparation-artifacts').exists()


def test_linked_review_sources_are_used_on_refresh(prepared, monkeypatch):
    from ossforge import radar, acceptance
    cfg, root, base, snap = prepared
    rec = policy_review._load(cfg)['org/repo']
    rec['extra_paths'] = ['docs/local-scope.md']
    allr = {'org/repo': rec}
    import json
    cfg.path('policy_reviews.json').write_text(json.dumps(allr))
    repo_research._save(cfg, {'schema': 1, 'cursor': 0, 'lead': {'repo': 'org/repo', 'status': 'repo_review_needed'}})
    monkeypatch.setattr(repo_research.repo_access, 'pr_restriction', lambda *a: '')
    monkeypatch.setattr(repo_research.radar, 'analyze', lambda r: radar.RepoScore(r, 80, 'Go'))
    monkeypatch.setattr(repo_research.acceptance, 'evidence', lambda r: acceptance.Acceptance(r, 'unknown'))
    monkeypatch.setattr(repo_research.repo_suitability, 'assess', lambda *a: {'status': 'native_candidate'})
    monkeypatch.setattr(repo_research.gh, 'api', lambda path, **kw: {'sha': base, 'html_url': 'https://example.test/commit'} if '/commits/' in path else {'default_branch': 'main', 'html_url': 'https://example.test/repo'})
    seen = []
    def snapshot(repo, extra_paths=None):
        seen.append(extra_paths)
        return snap
    monkeypatch.setattr(policy_review, 'snapshot', snapshot)
    assert repo_research.begin(cfg)['status'] == 'local_investigation'
    assert seen[0] == ['docs/local-scope.md']


def test_effective_identity_and_terminal_branch_change(prepared, monkeypatch):
    from ossforge import identity
    cfg, root, base, snap = prepared
    git(root, 'checkout', '-b', 'fix')
    (root / 'a.py').write_text('def value(): return 1\n')
    (root / 'test_value.py').write_text('from a import value\nassert value() == 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'fix')
    import sys
    result = preparation.task(cfg)['result_schema']
    result.update(branch='fix', test_command=[sys.executable, 'test_value.py'], check_commands=[[sys.executable, '-c', 'pass']])
    monkeypatch.setenv('GIT_COMMITTER_NAME', 'Wrong')
    with pytest.raises(identity.IdentityError, match='effective git committer'):
        preparation.complete(cfg, result)
    monkeypatch.delenv('GIT_COMMITTER_NAME')
    preparation.complete(cfg, result)
    git(root, 'checkout', 'main')
    with pytest.raises(ValueError):
        preparation.task(cfg)


def test_orphan_completion_refused_before_native_checks(prepared, monkeypatch):
    cfg, root, base, snap = prepared
    git(root, 'checkout', '--orphan', 'fix')
    git(root, 'rm', '-rf', '.')
    (root / 'a.py').write_text('def value(): return 1\n')
    (root / 'test_value.py').write_text('from a import value\nassert value() == 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'unrelated')
    from ossforge import verify
    monkeypatch.setattr(verify, 'verify_fix', lambda *a, **kw: pytest.fail('native checks reached'))
    with pytest.raises(ValueError, match='pinned base'):
        preparation.complete(cfg, {'id': 'local-preparation:org/repo'})
    assert not cfg.path('local-preparation-artifacts').exists()


def test_actual_origin_mismatch_refuses_task_and_completion(prepared, monkeypatch):
    from ossforge import identity, agent_next, verify
    cfg, root, base, snap = prepared
    conf = root / '.git' / 'config'
    conf.write_text(conf.read_text().replace('https://github.com/org/repo.git', 'https://github.com/wrong/target.git'))
    monkeypatch.setattr(verify, 'verify_fix', lambda *a, **kw: pytest.fail('native reached'))
    with pytest.raises(identity.IdentityError, match='clone origin'):
        preparation.task(cfg)
    with pytest.raises(identity.IdentityError, match='clone origin'):
        preparation.complete(cfg, {'id': 'local-preparation:org/repo'})
    assert agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'cfg.yml')['status'] == 'inspect_local'
