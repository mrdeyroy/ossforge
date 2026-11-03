import pytest

from ossforge import agent_next, gh, qualification, scout, vet
from ossforge.config import Config
from ossforge.queue import Queue


def lead():
    return scout.Candidate('org/repo', 42, 'Bug', 'https://github.com/org/repo/issues/42', 90,
                           vet.Verdict('org/repo#42', 'skip', ['closed reference'],
                                       [{'number': 9, 'html_url': 'https://github.com/org/repo/pull/9', 'state': 'closed'}]),
                           updated_at='v1')


def test_deferred_closed_work_becomes_readonly_checkpoint_not_clean(tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    q = Queue(tmp_path/'queue.json')
    qualification.record(cfg.path('qualification.json'), lead())
    result = agent_next.next_step(cfg, q, 'owner.yaml')
    assert result['status'] == 'review_needed'
    assert result['review_argv'] == ['ossforge', '--config', 'owner.yaml', 'review-qualification', 'org/repo', '42']
    assert result['next_argv'][-3:] == ['loop', '--once', '--prepare-only']
    assert not q.items
    qualification.defer(cfg.path('qualification.json'), 'org/repo', 42, 'maintainer decision pending')
    qualification.record(cfg.path('qualification.json'), lead())
    assert agent_next.next_step(cfg, q, 'owner.yaml')['status'] == 'no_work'
    changed = lead()
    changed.updated_at = 'v2'
    qualification.record(cfg.path('qualification.json'), changed)
    assert agent_next.next_step(cfg, q, 'owner.yaml')['status'] == 'review_needed'


def test_fresh_review_pins_pr_revisions_without_changing_queue(monkeypatch):
    calls = []
    ref = {'number': 9, 'html_url': 'https://github.com/org/repo/pull/9', 'pull_request': {}, 'state': 'closed'}
    def api(path, **kw):
        assert kw['fresh'] is True
        calls.append(path)
        if path.endswith('/comments') or path.endswith('/timeline'):
            return []
        if path.endswith('/pulls/9'):
            return {**ref, 'head': {'sha': 'old-fix-head'}, 'base': {'sha': 'old-fix-base'}, 'body': 'Only fixes another issue; not proof of eligibility'}
        return {'html_url': 'https://github.com/org/repo/issues/42', 'state': 'open', 'comments': 0}
    monkeypatch.setattr(gh, 'api', api)
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: [ref] if kw['fresh'] and kw['require_complete'] else pytest.fail('not fresh complete'))
    monkeypatch.setattr(vet, 'policy_texts', lambda *a, **kw: {} if kw['fresh'] else pytest.fail('not fresh policy'))
    result = qualification.inspect('org/repo', 42)
    assert result['status'] == 'review_needed'
    assert result['pull_requests'][0]['head']['sha'] == 'old-fix-head'
    assert 'No eligibility' in result['warning']
    assert len(calls) == 4


def test_incomplete_review_is_not_success(monkeypatch):
    monkeypatch.setattr(gh, 'api', lambda path, **kw: [{}]*100 if path.endswith('/comments') else
                        [] if path.endswith('/timeline') else
                        {'html_url': 'https://github.com/org/repo/issues/42', 'state': 'open'})
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: [])
    with pytest.raises(ValueError, match='coverage incomplete'):
        qualification.inspect('org/repo', 42)


def test_public_prepare_only_persists_closed_reference_review_without_clone(monkeypatch, tmp_path):
    from ossforge import loop
    cfg = Config(state_dir=str(tmp_path), work_kind='fix', kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    def discover(*a, **kw):
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='', fetched=1, kept=1, approved=0)
        return [lead()]
    monkeypatch.setattr(loop.scout, 'scout', discover)
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: pytest.fail('review must not clone/code'))
    loop.run_once(cfg)
    q = Queue(cfg.path('queue.json'))
    assert not q.items
    assert agent_next.next_step(cfg, q, 'owner.yaml')['status'] == 'review_needed'
