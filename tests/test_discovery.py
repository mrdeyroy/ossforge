from ossforge import discovery, gh, scout, vet, radar, acceptance
from ossforge.config import Config
from ossforge.outcomes import Stats


def test_plans_rotate_and_cover_affinity(tmp_path):
    cfg = Config(preferred_repos=[f"org/lib{i}" for i in range(7)] + ['bad OR repo:hijack'], state_dir=str(tmp_path))
    stats = Stats(tmp_path / 'stats.json')
    stats.set_history('trusted/lib', 2, 0)
    stats.set_history('closed/lib', 0, 4)
    plans = [discovery.plan(cfg, stats, 'python', 'bug', 'rotate', n) for n in range(6)]
    assert [p.strategy for p in plans] == ['broad', 'preferred', 'history'] * 2
    assert set(plans[1].repos + plans[4].repos) == {f'org/lib{i}' for i in range(7)}
    assert plans[2].repos == ['trusted/lib']
    assert 'hijack' not in plans[1].query
    assert all(len(p.repos) <= 5 for p in plans)


def test_recent_expiry_and_update():
    data = {'org/lib#1': {'updated_at': 'v1', 'seen_at': 1000}}
    assert discovery.recent_reason(data, 'ORG/lib', 1, 'v1', 7, 1001)
    for stamp, days, now in [('v2', 7, 1001), (None, 7, 1001), ('v1', 0, 1001), ('v1', 7, 999), ('v1', 7, 1000+7*86400)]:
        assert not discovery.recent_reason(data, 'org/lib', 1, stamp, days, now)


def test_saved_results_skip_unchanged_and_can_be_included(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), skills=['go', 'python'])
    stats = Stats(tmp_path / 'stats.json')
    issue = dict(title='Python empty input error in django', body='Steps: run `test`, expected value, got error',
                 repository_url='https://api.github.com/repos/org/lib', number=1,
                 html_url='https://github.com/org/lib/issues/1', updated_at='v1', labels=[], comments=0)
    monkeypatch.setattr(vet, 'clear_requirements', lambda b: True)
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **k: [issue])
    monkeypatch.setattr(gh, 'api', lambda *a, **k: {'stargazers_count': 501})
    monkeypatch.setattr(radar, 'analyze', lambda r: radar.RepoScore(r, 80, 'Good'))
    monkeypatch.setattr(vet, 'vet_issue', lambda *a, **k: vet.Verdict('org/lib#1', 'approve'))
    monkeypatch.setattr(acceptance, 'evidence', lambda r: acceptance.Acceptance(r, 'unknown', ['sample limited']))
    first = discovery.discover(cfg, stats)
    assert len(first) == 1 and any('skill terms: python ' in w for w in first[0].why)
    assert discovery.discover(cfg, stats) == []
    assert scout.LAST_FUNNEL['recently_surfaced'] == 1
    assert len(discovery.discover(cfg, stats, include_recent=True)) == 1
    issue['updated_at'] = 'v2'
    assert len(discovery.discover(cfg, stats)) == 1
    assert len(scout.scout(cfg, stats)) == 1  # legacy path not hidden
    other = Config(state_dir=str(tmp_path / 'other'))
    assert len(discovery.discover(other, Stats(tmp_path / 'other-stats'))) == 1


def test_rate_limit_keeps_turn_and_explicit_empty_is_not_broad(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    stats = Stats(tmp_path / 'stats.json')
    calls = []
    def stop(*args, **kw):
        calls.append(1)
        raise gh.RateLimited('cooldown', 429, 30)
    monkeypatch.setattr(gh, 'search_issues', stop)
    assert discovery.discover(cfg, stats) == []
    assert not (tmp_path / 'discovery.json').exists()
    assert scout.LAST_FUNNEL['stopped']
    discovery.discover(cfg, stats, strategy='preferred')
    assert len(calls) == 1 and scout.LAST_FUNNEL['strategy'] == 'preferred'


def test_cli_routes_discover_and_serializes(monkeypatch, tmp_path, capsys):
    from ossforge import cli
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(f'state_dir: {tmp_path}/state\n')
    def fake(*args):
        assert args[2:] == ('python', 'bug', 3, 'preferred', True)
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(fetched=0, kept=0, approved=0, stopped='', strategy='preferred')
        return []
    monkeypatch.setattr(discovery, 'discover', fake)
    assert cli.main(['--config', str(cfg), '--json', 'discover', '--language', 'python', '--label', 'bug',
                     '--limit', '3', '--strategy', 'preferred', '--include-recent']) == 0
    assert '"strategy": "preferred"' in capsys.readouterr().out


def test_unapproved_results_are_not_recently_hidden(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    stats = Stats(tmp_path / 'stats.json')
    def fake(*args, **kwargs):
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='')
        return [scout.Candidate('org/lib', 1, 'title', 'url', 70, vet.Verdict('org/lib#1', 'skip'), updated_at='v1')]
    monkeypatch.setattr(scout, 'scout', fake)
    discovery.discover(cfg, stats)
    assert not discovery.issue_reviews.load(cfg.path('discovery.json'))['recent']
