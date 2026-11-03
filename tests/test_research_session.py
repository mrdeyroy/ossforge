import pytest
from ossforge import research_session as session
from ossforge.config import Config


def test_resume_does_not_extend_budget_or_mutate_issue_state(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path))
    saved = tmp_path/'discovery-resume.json'
    saved.write_text('{"saved-five": [1,2,3,4,5]}')
    original = saved.read_bytes()
    monkeypatch.setattr(session.time, 'time', lambda: 1000.)
    assert session.status(cfg)['status'] == 'search_session_needed'
    assert session.start(cfg, 3600)['deadline'] == 4600
    raw = cfg.path('research_session.json').read_bytes()
    monkeypatch.setattr(session.time, 'time', lambda: 4500.)
    assert session.allowance(cfg) == 100
    with pytest.raises(session.Invalid, match='already exists'):
        session.start(cfg, 3600)
    assert cfg.path('research_session.json').read_bytes() == raw
    monkeypatch.setattr(session.time, 'time', lambda: 4600.)
    assert session.status(cfg)['status'] == 'search_budget_exhausted'
    with pytest.raises(session.Invalid, match='exhausted'):
        session.allowance(cfg)
    assert saved.read_bytes() == original


@pytest.mark.parametrize('value', [True, 0, -1, float('inf'), float('nan'), '3600'])
def test_invalid_budget_is_not_persisted(tmp_path, value):
    cfg = Config(state_dir=str(tmp_path))
    with pytest.raises(session.Invalid):
        session.start(cfg, value)
    assert not cfg.path('research_session.json').exists()


def test_configuration_or_clock_change_blocks_resume(tmp_path, monkeypatch):
    cfg = Config(state_dir=str(tmp_path))
    monkeypatch.setattr(session.time, 'time', lambda: 1000.)
    session.start(cfg, 120)
    cfg.languages = ['rust']
    with pytest.raises(session.Invalid, match='configuration changed'):
        session.status(cfg)
    cfg.languages = ['python']
    monkeypatch.setattr(session.time, 'time', lambda: 999.)
    with pytest.raises(session.Invalid, match='clock'):
        session.status(cfg)


def test_malformed_session_not_reset(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    cfg.path('research_session.json').write_text('{broken')
    with pytest.raises(session.Invalid, match='unreadable'):
        session.start(cfg, 120)
    assert cfg.path('research_session.json').read_text() == '{broken'


def test_explicit_new_only_after_exhaustion_preserves_history(tmp_path, monkeypatch):
    import json
    cfg = Config(state_dir=str(tmp_path))
    monkeypatch.setattr(session.time, 'time', lambda: 1000.)
    session.start(cfg, 60)
    with pytest.raises(session.Invalid, match='already exists'):
        session.start(cfg, 60, new=True)
    monkeypatch.setattr(session.time, 'time', lambda: 1060.)
    assert session.start(cfg, 120, new=True)['deadline'] == 1180
    prior = json.loads(cfg.path('research_session_history.jsonl').read_text())
    assert prior['deadline'] == 1060


def test_expired_search_does_not_query_or_hide_investigation(tmp_path, monkeypatch):
    from ossforge import repo_research, agent_next
    from ossforge.queue import Queue
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    q = Queue(cfg.path('queue.json'))
    assert agent_next.next_step(cfg, q, 'cfg')['status'] == 'search_session_needed'
    monkeypatch.setattr(session.time, 'time', lambda: 1000.)
    session.start(cfg, 60)
    monkeypatch.setattr(session.time, 'time', lambda: 1060.)
    monkeypatch.setattr(repo_research.discovery, 'discover_broad_repos',
                        lambda *a: (_ for _ in ()).throw(AssertionError('query reached')))
    with pytest.raises(session.Invalid, match='exhausted'):
        repo_research.prepare(cfg)
    assert agent_next.next_step(cfg, q, 'cfg')['status'] == 'search_budget_exhausted'
    repo_research._save(cfg, {'schema': 1, 'cursor': 0, 'lead': {
        'repo': 'org/repo', 'status': 'investigating', 'clone': '/fixture',
        'base': 'sha', 'checkout': {'tree': 'sha'}, 'revision': 'sha',
        'revision_url': 'fixture', 'default_branch': 'main'}})
    assert agent_next.next_step(cfg, q, 'cfg')['status'] == 'repo_investigation'


def test_cli_budget_error_is_a_controlled_refusal(tmp_path, monkeypatch, capsys):
    from ossforge import cli, gh, repo_research
    cfgfile = tmp_path/'config.yml'
    cfgfile.write_text(f'state_dir: {tmp_path}/state\nkill_file: {tmp_path}/STOP\nrepo_first: true\n')
    assert cli.main(['--config', str(cfgfile), 'research-session', '--seconds', '60']) == 0
    monkeypatch.setattr(repo_research.discovery, 'discover_broad_repos',
                        lambda *a: (_ for _ in ()).throw(gh.ReadBudgetExceeded('partial read')))
    assert cli.main(['--config', str(cfgfile), 'research-repo']) == 1
    assert 'REFUSED: partial read' in capsys.readouterr().err


def test_cli_new_requires_budget_and_stop_blocks_start(tmp_path, capsys):
    from ossforge import cli
    cfgfile = tmp_path/'config.yml'
    cfgfile.write_text(f'state_dir: {tmp_path}/state\nkill_file: {tmp_path}/STOP\nrepo_first: true\n')
    assert cli.main(['--config', str(cfgfile), 'research-session', '--new']) == 1
    assert '--new requires' in capsys.readouterr().err
    (tmp_path/'STOP').touch()
    assert cli.main(['--config', str(cfgfile), 'research-session', '--seconds', '60']) == 1
    assert not (tmp_path/'state'/'research_session.json').exists()
