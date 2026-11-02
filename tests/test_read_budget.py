import subprocess

import pytest

from ossforge import gh, loop
from ossforge.config import Config


def test_read_budget_clamps_subprocess_and_restores_scope(monkeypatch):
    gh.configure(None)
    now = [100.0]
    monkeypatch.setattr(gh.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(gh, '_budget', lambda path: None)
    monkeypatch.setattr(gh, 'PACING_S', 0)
    def read(cmd, **kw):
        assert kw['timeout'] == 5
        return subprocess.CompletedProcess(cmd, 0, '{"ok":true}', '')
    monkeypatch.setattr(gh.subprocess, 'run', read)
    with gh.read_budget(5):
        assert gh.api('user') == {'ok': True}
        now[0] = 106
        with pytest.raises(gh.ReadBudgetExceeded):
            gh.api('user')
    assert gh.read_remaining() == float('inf')


def test_pacing_does_not_sleep_past_read_budget(monkeypatch):
    monkeypatch.setattr(gh.time, 'sleep', lambda n: pytest.fail('must not sleep beyond budget'))
    with gh.read_budget(1):
        with pytest.raises(gh.ReadBudgetExceeded):
            gh._sleep(60)


def test_loop_records_budget_exhaustion_not_complete_no_find(tmp_path, monkeypatch):
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    def exhausted(*a, **kw):
        raise gh.ReadBudgetExceeded('controlled deadline')
    monkeypatch.setattr(loop.scout, 'scout', exhausted)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    notes = loop.run_once(cfg)
    import json
    assert json.loads((tmp_path/'run.json').read_text())['status'] == 'discovery_budget_exhausted'
    assert any('discovery stopped' in note for note in notes)
    assert 'controlled deadline' in (tmp_path/'digest.md').read_text()


def test_partial_feature_funnel_is_not_journaled_as_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.time, 'time', lambda: 86400)
    def empty(*a, **kw):
        loop.scout.LAST_FUNNEL.clear()
        return []
    def partial(*a, **kw):
        loop.scout.LAST_FUNNEL.update(stopped='controlled feature deadline')
        return []
    monkeypatch.setattr(loop.scout, 'scout', empty)
    monkeypatch.setattr(loop.scout, 'scout_features', partial)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    loop.run_once(cfg)
    import json
    assert json.loads((tmp_path/'run.json').read_text())['status'] == 'discovery_budget_exhausted'
