import pytest
from ossforge import loop, scout, vet, agent_next, radar
from ossforge.config import Config
from ossforge.queue import Queue


def test_approved_lead_survives_interrupt_before_first_clone(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'), work_kind='fix')
    candidate = scout.Candidate('org/lib', 42, 'real lead', 'https://github.com/org/lib/issues/42', 80,
                                vet.Verdict('org/lib#42', 'approve'))
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: [candidate])
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        loop.run_once(cfg)
    queue = Queue(cfg.path('queue.json'))
    item = queue.items['org/lib#42:issue']
    assert item.status == 'found' and not item.clone and not item.verification
    checkpoint = agent_next.next_step(cfg, queue, 'c.yaml')
    assert checkpoint['status'] == 'recover_issue_handoff'
    assert checkpoint['pending'][0]['source_issue'] == 42
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: (_ for _ in ()).throw(AssertionError('new discovery before recovery')))
    monkeypatch.setattr(vet, 'vet_issue', lambda *a, **k: vet.Verdict('org/lib#42', 'approve'))
    monkeypatch.setattr(radar, 'analyze', lambda *a: type('Health', (), {'score': 90})())
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: tmp_path)
    monkeypatch.setattr(loop.hunt, 'policy_of', lambda *a: loop.hunt.policy.PolicyResult(False, '', []))
    loop.run_once(cfg)
    recovered = Queue(cfg.path('queue.json')).items[item.id]
    assert recovered.status == 'clean' and recovered.clone == str(tmp_path)
    assert not recovered.verification


def test_resumed_lead_rechecks_current_vet_before_clone(tmp_path, monkeypatch):
    from ossforge.queue import Item
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'), work_kind='fix')
    queue = Queue(cfg.path('queue.json'))
    queue.add(Item('org/lib#42:issue', 'org/lib', '', 42, 'issue', 'old lead', source_issue=42))
    queue.save()
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: (_ for _ in ()).throw(AssertionError('new discovery')))
    monkeypatch.setattr(vet, 'vet_issue', lambda *a, **k: vet.Verdict('org/lib#42', 'skip', ['source now resolved']))
    monkeypatch.setattr(radar, 'analyze', lambda *a: type('Health', (), {'score': 90})())
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('clone after failed vet')))
    loop.run_once(cfg)
    recovered = Queue(cfg.path('queue.json')).items['org/lib#42:issue']
    assert recovered.status == 'held' and 'source now resolved' in recovered.hold_reason


def test_pending_checkout_refusal_preserves_lead_and_existing_queue(tmp_path, monkeypatch):
    from ossforge.queue import Item
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'))
    q = Queue(cfg.path('queue.json'))
    q.add(Item('org/lib#42:issue', 'org/lib', '', 42, 'issue', 'lead', source_issue=42))
    q.add(Item('existing', 'other/lib', '', 1, 'issue', 'prior', status='held', hold_reason='owner hold'))
    q.save()
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(vet, 'vet_issue', lambda *a, **k: vet.Verdict('org/lib#42', 'approve'))
    monkeypatch.setattr(radar, 'analyze', lambda *a: type('Health', (), {'score': 90})())
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: (_ for _ in ()).throw(RuntimeError('incomplete checkout preserved')))
    loop.run_once(cfg)
    saved = Queue(cfg.path('queue.json'))
    assert saved.items['org/lib#42:issue'].status == 'found'
    assert not saved.items['org/lib#42:issue'].clone
    assert saved.items['existing'].hold_reason == 'owner hold'
    assert agent_next.next_step(cfg, saved, 'c.yaml')['status'] == 'recover_issue_handoff'


def test_pending_handoff_respects_cooldown(tmp_path):
    import time
    from ossforge.queue import Item
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    q = Queue(cfg.path('queue.json'))
    q.add(Item('org/lib#42:issue', 'org/lib', '', 42, 'issue', 'lead', source_issue=42))
    cfg.path('ratelimit_until').write_text(str(time.time()+3600))
    assert agent_next.next_step(cfg, q, 'c.yaml')['status'] == 'wait_for_cooldown'


def test_pending_review_timeout_keeps_unverified_lead_without_clone(tmp_path, monkeypatch):
    from ossforge import gh
    from ossforge.queue import Item
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'))
    q = Queue(cfg.path('queue.json'))
    q.add(Item('org/lib#42:issue', 'org/lib', '', 42, 'issue', 'lead', source_issue=42))
    q.save()
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(radar, 'analyze', lambda *a: (_ for _ in ()).throw(gh.ReadBudgetExceeded('test deadline')))
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('must not clone')))
    loop.run_once(cfg)
    item = Queue(cfg.path('queue.json')).items['org/lib#42:issue']
    assert item.status == 'found' and not item.clone and not item.verification
