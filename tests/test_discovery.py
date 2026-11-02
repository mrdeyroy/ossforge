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


def test_build_query_decouples_unsupported_stars_qualifier():
    q = scout.build_query('python', 'help wanted', 500)
    assert 'stars:' not in q
    assert 'language:python' in q
    assert 'label:"help wanted"' in q


def test_gh_search_repositories(monkeypatch):
    calls = []
    def fake_api(path, **kw):
        calls.append((path, kw))
        return {'items': [{'full_name': 'psf/requests', 'stargazers_count': 50000}]}
    monkeypatch.setattr(gh, 'api', fake_api)
    items = gh.search_repositories('stars:>=500 language:python')
    assert len(items) == 1 and items[0]['full_name'] == 'psf/requests'
    assert calls[0][0] == 'search/repositories'
    assert calls[0][1]['sort'] == 'stars'


def test_two_phase_broad_discovery(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), min_stars=500)
    stats = Stats(tmp_path / 'stats.json')
    repo_search_calls = []
    issue_search_calls = []

    def fake_search_repos(q, **kw):
        repo_search_calls.append(q)
        return [{'full_name': 'org/repo1'}, {'full_name': 'org/repo2'}]

    def fake_search_issues(q, **kw):
        issue_search_calls.append(q)
        return [{
            'title': 'Test bug',
            'body': 'Steps to reproduce: run x, expected y, got error traceback',
            'repository_url': 'https://api.github.com/repos/org/repo1',
            'number': 1,
            'html_url': 'https://github.com/org/repo1/issues/1',
            'updated_at': 'v1',
            'labels': [],
            'comments': 0,
        }]

    monkeypatch.setattr(gh, 'search_repositories', fake_search_repos)
    monkeypatch.setattr(gh, 'search_issues', fake_search_issues)
    monkeypatch.setattr(vet, 'clear_requirements', lambda b: True)
    monkeypatch.setattr(gh, 'api', lambda *a, **k: {'stargazers_count': 1000})
    monkeypatch.setattr(radar, 'analyze', lambda r: radar.RepoScore(r, 85, 'Good'))
    monkeypatch.setattr(vet, 'vet_issue', lambda *a, **k: vet.Verdict('org/repo1#1', 'approve'))
    monkeypatch.setattr(acceptance, 'evidence', lambda r: acceptance.Acceptance(r, 'unknown', ['sample limited']))

    results = discovery.discover(cfg, stats, language='python', strategy='broad')
    # Phase 1: searched repos with stars qualifier
    assert len(repo_search_calls) == 1
    assert 'stars:>=500' in repo_search_calls[0]
    # Phase 2: searched issues scoped to discovered repos without stars qualifier
    assert len(issue_search_calls) == 1
    assert 'repo:org/repo1' in issue_search_calls[0]
    assert 'repo:org/repo2' in issue_search_calls[0]
    assert 'stars:' not in issue_search_calls[0]
    assert len(results) == 1

