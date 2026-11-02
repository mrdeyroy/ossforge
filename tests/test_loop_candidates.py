from ossforge import loop, scout, vet
from ossforge.config import Config
from ossforge.queue import Queue


def test_loop_keeps_approved_issue_for_external_driver_when_static_scan_empty(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path/'state'), work_dir=str(tmp_path/'work'), kill_file=str(tmp_path/'STOP'))
    candidate = scout.Candidate('owner/repo', 42, 'Incorrect parser result', 'https://github.com/owner/repo/issues/42',
                                80, vet.Verdict(42, 'approve', ['policy clear']), updated_at='2026-11-01')
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: [candidate])
    monkeypatch.setattr(loop.scout, 'scout_features', lambda *a, **k: [])
    monkeypatch.setattr(loop.hunt, 'hunt', lambda *a: {'anti_ai': None, 'clean': 0, 'duplicate': 0})
    clone = tmp_path/'work'/'owner__repo'
    clone.mkdir(parents=True)
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: clone)
    loop.run_once(cfg)
    items = Queue(cfg.path('queue.json')).by_status('clean')
    assert len(items) == 1
    assert items[0].line == 42 and items[0].clone == str(clone)
    assert items[0].notes == [candidate.url]
    assert items[0].verification == {}  # approval is not bug proof


def test_local_policy_denial_does_not_enqueue_search_issue(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    candidate = scout.Candidate('owner/repo', 42, 'Candidate', 'https://github.com/owner/repo/issues/42',
                                80, vet.Verdict(42, 'approve', []))
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: [candidate])
    monkeypatch.setattr(loop.scout, 'scout_features', lambda *a, **k: [])
    monkeypatch.setattr(loop.hunt, 'hunt', lambda *a: {'anti_ai': 'CONTRIBUTING.md', 'clean': 0, 'duplicate': 0})
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('must not enqueue')))
    loop.run_once(cfg)
    assert Queue(cfg.path('queue.json')).by_status('clean') == []
