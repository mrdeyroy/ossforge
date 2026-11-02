import json
import subprocess
import sys
from pathlib import Path

import pytest

from ossforge import agent_run, driver
from ossforge.config import Config
from ossforge.queue import Item, Queue


def fixture(tmp_path):
    clone = tmp_path / 'clone'
    clone.mkdir()
    def git(*args):
        return subprocess.run(['git', *args], cwd=clone, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (clone / 'calc.py').write_text('def f(n): return n+1\n')
    git('add', '.')
    git('commit', '-m', 'baseline')
    base = git('rev-parse', 'HEAD')
    git('update-ref', 'refs/remotes/origin/main', base)
    git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    git('switch', '-c', 'fix')
    (clone / 'calc.py').write_text('def f(n): return n*2\n')
    (clone / 'test_calc.py').write_text('from calc import f\nassert f(3)==6\n')
    git('add', '.')
    git('commit', '-m', 'fix and test')
    cfg = Config(state_dir=str(tmp_path / 'state'), kill_file=str(tmp_path / 'STOP'))
    q = Queue(cfg.path('queue.json'))
    q.add(Item('a', 'owner/repo', 'calc.py', 1, 'controlled', 'fixture', status='clean', clone=str(clone)))
    q.save()
    script = tmp_path / 'driver.py'
    script.write_text('''import json,os,sys
from pathlib import Path
t=json.loads(Path(os.environ['OSSFORGE_TASK_FILE']).read_text())
r=t['result_schema'];r.update(branch='fix',test_command=[sys.executable,'test_calc.py'],check_commands=[])
Path(os.environ['OSSFORGE_RESULT_FILE']).write_text(json.dumps(r))
''')
    return cfg, [sys.executable, str(script)]


def test_controlled_process_to_actual_verifier_retains_patch_no_publication(tmp_path, monkeypatch):
    cfg, command = fixture(tmp_path)
    monkeypatch.setattr(agent_run.submit, 'submit', lambda *a, **k: pytest.fail('publication disabled'))
    out = agent_run.run(cfg, command, discover=False)
    assert out['status'] == 'verified_not_submitted'
    q = Queue(cfg.path('queue.json'))
    assert q.items['a'].verification['tree'] and q.items['a'].status == 'verified'
    assert json.loads(cfg.path('driver-attempts.json').read_text())['count'] == 1
    # Resume verified without another driver invocation, even at attempt limit.
    assert agent_run.run(cfg, ['missing-driver'], attempts=1, discover=False)['status'] == 'verified_not_submitted'


def test_driver_failure_reserves_attempt_and_blocks_retry(tmp_path):
    cfg, _ = fixture(tmp_path)
    assert agent_run.run(cfg, [sys.executable, '-c', 'raise SystemExit(3)'], discover=False, attempts=1)['status'] == 'driver_failed'
    assert agent_run.run(cfg, ['missing'], discover=False, attempts=1)['status'] == 'attempt_limit'


def test_timeout_consumes_attempt_and_records_outcome(tmp_path):
    cfg, _ = fixture(tmp_path)
    assert agent_run.run(cfg, [sys.executable, '-c', 'import time;time.sleep(30)'], discover=False, timeout=1)['status'] == 'driver_timeout'
    assert json.loads(cfg.path('run.json').read_text())['status'] == 'driver_timeout'
    assert Queue(cfg.path('queue.json')).items['a'].status == 'clean'


def test_explicit_publication_still_uses_existing_refusal_gate(tmp_path, monkeypatch):
    cfg, command = fixture(tmp_path)
    def refuse(*a, **kw):
        assert kw['execute'] is True
        raise agent_run.submit.Refused('policy not approved')
    monkeypatch.setattr(agent_run.submit, 'submit', refuse)
    out = agent_run.run(cfg, command, discover=False, execute=True)
    assert out['status'] == 'publication_refused'
    assert Queue(cfg.path('queue.json')).items['a'].status == 'verified'


def test_invalid_limits_do_not_start_work(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    for args in [dict(timeout=0), dict(timeout=float('nan')), dict(attempts=0), dict(attempts=True)]:
        with pytest.raises(driver.Invalid):
            agent_run.run(cfg, ['driver'], **args)


def test_partial_discovery_without_candidate_is_incomplete_not_no_work(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path / 'state'), kill_file=str(tmp_path / 'STOP'))
    def partial(cfg, journal):
        journal.data['outcome'] = 'discovery_budget_exhausted'
        return []
    monkeypatch.setattr(agent_run.loop, '_run_once', partial)
    out = agent_run.run(cfg, ['must-not-start'])
    assert out['status'] == 'discovery_incomplete'
    assert not cfg.path('driver-attempts.json').exists()


def test_dirty_candidate_refuses_before_driver_attempt_or_launch(tmp_path, monkeypatch):
    from ossforge import evidence
    cfg, command = fixture(tmp_path)
    q = Queue(cfg.path('queue.json'))
    (Path(q.items['a'].clone) / 'calc.py').write_text('uncommitted user work\n')
    monkeypatch.setattr(agent_run, 'invoke', lambda *a: pytest.fail('dirty checkout must not launch driver'))
    with pytest.raises(evidence.StaleEvidence, match='dirty'):
        agent_run.run(cfg, command, discover=False)
    assert not cfg.path('driver-attempts.json').exists()
