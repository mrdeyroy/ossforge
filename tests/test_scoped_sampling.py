import json

from ossforge import discovery, discovery_resume, scout
from ossforge.config import Config
from ossforge.outcomes import Stats


def setup(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), labels=['bug'])
    cfg.discovery_sampling = 'per-repo'
    stats = Stats(tmp_path/'stats.json')
    pool = ['org/a', 'org/b', 'org/c', 'org/d', 'org/dominant']
    monkeypatch.setattr(discovery, 'discover_broad_repos', lambda *a: list(pool))
    calls = []
    stopped = []
    def fake(cfg, stats, language, label, limit, **kw):
        calls.append((kw['query'], limit))
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='partial' if stopped else '', fetched=12, kept=0, approved=0)
        return []
    monkeypatch.setattr(scout, 'scout', fake)
    return cfg, stats, pool, calls, stopped


def test_one_query_per_repo_and_breadth_turn_advances_only_after_pool(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    for i, repo in enumerate(pool):
        discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
        assert calls[-1] == (scout.build_query('python', 'bug') + ' repo:' + repo, 12)
        assert scout.LAST_FUNNEL['repository_pool'] == pool
        state = json.loads((tmp_path/'discovery.json').read_text())
        assert state['scoped_breadth_cursor'] == int(i == 4)
        assert 'cursor' not in state and 'breadth_cursor' not in state
    assert len(calls) == 5


def test_partial_retry_same_scope_and_pool_change_resets(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    stopped.append(True)
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    assert calls[-1] == calls[-2] and 'repo:org/b' in calls[-1][0]
    stopped.clear()
    pool.reverse()
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    assert 'repo:org/dominant' in calls[-1][0]


def test_pending_original_combined_batch_must_finish_before_switch(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    discovery_resume.save(tmp_path/'discovery-resume.json', 'original combined query', 12,
                          [{'repo': 'org/a', 'number': 1}])
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    assert not calls
    assert 'original config' in scout.LAST_FUNNEL['stopped']
    assert not (tmp_path/'discovery.json').exists()


def test_combined_default_unchanged_and_empty_pool_never_unscoped(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    cfg.discovery_sampling = 'combined'
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    assert calls[-1][0].count('repo:') == 5
    assert json.loads((tmp_path/'discovery.json').read_text())['breadth_cursor'] == 1
    cfg.discovery_sampling = 'per-repo'
    pool.clear()
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    assert len(calls) == 1 and 'confirmed repository pool' in scout.LAST_FUNNEL['stopped']


def test_scoped_cursor_initializes_from_existing_but_never_changes_baseline(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    (tmp_path/'discovery.json').write_text(json.dumps({'breadth_cursor': 7, 'cursor': 42}))
    for _ in range(5):
        discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    state = json.loads((tmp_path/'discovery.json').read_text())
    assert state['scoped_breadth_cursor'] == 8
    assert state['breadth_cursor'] == 7 and state['cursor'] == 42


def test_scoped_public_loop_routes_discovery_even_with_broad_default(monkeypatch, tmp_path):
    from ossforge import loop, patrol
    cfg = Config(state_dir=str(tmp_path), work_dir=str(tmp_path/'work'), kill_file=str(tmp_path/'STOP'),
                 discovery_sampling='per-repo', discovery_strategy='broad', work_kind='fix', labels=['bug'])
    monkeypatch.setattr(patrol, 'patrol', lambda *a, **kw: [])
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='', fetched=0, kept=0, approved=0)
        return []
    monkeypatch.setattr(discovery, 'discover', fake)
    monkeypatch.setattr(scout, 'scout', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('unscoped legacy path')))
    loop.run_once(cfg)
    assert len(calls) == 1 and calls[0][5] == 'broad'


def test_query_limit_change_resets_subturn_without_touching_prior_cursor(monkeypatch, tmp_path):
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first')
    discovery.discover(cfg, stats, 'python', 'bug', 3, 'breadth-first')
    assert 'repo:org/a' in calls[-1][0] and calls[-1][1] == 3


def test_unsupported_multi_category_config_refuses_before_remote_effects(monkeypatch, tmp_path):
    from ossforge import loop, patrol
    cfg, stats, pool, calls, stopped = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(discovery, 'discover_broad_repos', lambda *a: (_ for _ in ()).throw(AssertionError('remote pool fetch')))
    monkeypatch.setattr(patrol, 'patrol', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('remote patrol')))
    for languages, labels in [(['python', 'go'], ['bug']), (['python'], ['bug', 'help wanted'])]:
        cfg.languages, cfg.labels = languages, labels
        assert discovery.discover(cfg, stats, 'python', 'bug', 12, 'breadth-first') == []
        assert 'exactly one' in scout.LAST_FUNNEL['stopped']
        assert any('exactly one' in note for note in loop.run_once(cfg))
    assert not calls


def test_combined_legacy_scout_cannot_abandon_expired_scoped_batch(monkeypatch, tmp_path):
    from ossforge import gh
    cfg = Config(state_dir=str(tmp_path), discovery_sampling='combined')
    discovery_resume.save(tmp_path/'discovery-resume.json', 'old scoped query', 12,
                          [{'repo': 'org/a', 'number': 1}], sampling='per-repo')
    data = json.loads((tmp_path/'discovery-resume.json').read_text())
    for row in data.values():
        row['saved_at'] = 0
    (tmp_path/'discovery-resume.json').write_text(json.dumps(data))
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('new scope fetched')))
    assert scout.scout(cfg, query='new combined query') == []
    assert 'original config' in scout.LAST_FUNNEL['stopped']
    assert json.loads((tmp_path/'discovery-resume.json').read_text()) == data
    cfg.discovery_sampling = 'per-repo'
    assert scout.scout(cfg, query='old scoped query', limit=12) == []
    assert 'expired' in scout.LAST_FUNNEL['stopped']
    assert json.loads((tmp_path/'discovery-resume.json').read_text()) == data
