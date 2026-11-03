from ossforge import discovery, scout
from ossforge.config import Config
from ossforge.outcomes import Stats


def test_opt_in_epoch_covers_broad_before_repeating_small_history(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    stats = Stats(cfg.path('stats.json'))
    stats.set_history('org/prior', 1, 0)
    plans = [discovery.plan(cfg, stats, 'python', 'bug', 'breadth-first', n) for n in range(8)]
    assert [p.strategy for p in plans] == ['broad']*6 + ['history', 'broad']
    assert plans[6].repos == ['org/prior']


def test_affinity_windows_rotate_across_epochs_and_empty_pools(tmp_path):
    cfg = Config(state_dir=str(tmp_path), preferred_repos=[f'org/lib{i}' for i in range(8)])
    stats = Stats(cfg.path('stats.json'))
    stats.set_history('org/prior', 1, 0)
    first = discovery.plan(cfg, stats, 'python', 'bug', 'breadth-first', 6)
    second = discovery.plan(cfg, stats, 'python', 'bug', 'breadth-first', 14)
    assert set(first.repos+second.repos) == set(cfg.preferred_repos)
    assert discovery.plan(Config(), Stats(tmp_path/'none'), 'python', 'bug', 'breadth-first', 6).strategy == 'broad'


def test_experiment_cursor_separate_partial_retry_and_broad_pagination(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path))
    stats = Stats(cfg.path('stats.json'))
    stats.set_history('org/prior', 1, 0)
    discovery.issue_reviews._save(cfg.path('discovery.json'), {'cursor': 41, 'breadth_cursor': 7, 'recent': {}})
    turns=[]
    monkeypatch.setattr(discovery, 'discover_broad_repos', lambda cfg, lang, cursor: turns.append(cursor) or ['org/new'])
    def fake(*args, **kw):
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='partial')
        return []
    monkeypatch.setattr(scout, 'scout', fake)
    discovery.discover(cfg, stats, strategy='breadth-first')
    assert turns == [6]
    state=discovery.issue_reviews.load(cfg.path('discovery.json'))
    assert state['cursor'] == 41 and state['breadth_cursor'] == 7
    monkeypatch.setattr(scout, 'scout', lambda *a, **kw: scout.LAST_FUNNEL.update(stopped='') or [])
    discovery.discover(cfg, stats, strategy='breadth-first')
    state=discovery.issue_reviews.load(cfg.path('discovery.json'))
    assert state['cursor'] == 41 and state['breadth_cursor'] == 8


def test_defaults_and_existing_rotation_unchanged(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    assert cfg.discovery_strategy == 'broad'
    stats = Stats(cfg.path('stats.json'))
    stats.set_history('org/prior', 1, 0)
    assert [discovery.plan(cfg, stats, None, 'bug', 'rotate', n).strategy for n in range(4)] == ['broad', 'history']*2
    for n in (0, 1, 8, 1000):
        assert 'label:"bug"' in discovery.plan(cfg, stats, 'python', 'bug', 'breadth-first', n).query


def test_large_history_pool_windows_advance_and_wrap(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    stats = Stats(cfg.path('stats.json'))
    names = [f'org/repo{i:02d}' for i in range(13)]
    for repo in names:
        stats.set_history(repo, 1, 0)
    windows = [discovery.plan(cfg, stats, None, 'bug', 'breadth-first', epoch*7+6).repos for epoch in range(3)]
    assert set(sum(windows, [])) == set(names)
    assert all(len(w) == 5 for w in windows)
