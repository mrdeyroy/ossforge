import pytest
from ossforge import repo_research, agent_next, radar, acceptance
from ossforge.config import Config
from ossforge.queue import Queue


def setup_sources(monkeypatch):
    monkeypatch.setattr(repo_research.discovery, 'discover_broad_repos', lambda *a: ['org/one', 'org/two'])
    monkeypatch.setattr(repo_research.repo_access, 'pr_restriction', lambda *a: '')
    monkeypatch.setattr(repo_research.radar, 'analyze', lambda r: radar.RepoScore(r, 80, 'Go'))
    monkeypatch.setattr(repo_research.acceptance, 'evidence', lambda r: acceptance.Acceptance(r, 'unknown'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r: {'docs': [], 'anti_ai': False, 'agent_review': []})
    monkeypatch.setattr(repo_research.gh, 'api', lambda path, **kw:
                        {'default_branch': 'main', 'html_url': 'https://github.com/org/one'} if '/commits/' not in path else
                        {'sha': 'exact-tip', 'html_url': 'https://github.com/org/one/commit/exact-tip'})


def test_repo_first_without_any_issue_or_queue_entry(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    (tmp_path/'discovery-resume.json').write_text('{"saved-five": {"remaining": [1,2,3,4,5]}}')
    original = (tmp_path/'discovery-resume.json').read_bytes()
    lead = repo_research.prepare(cfg)
    assert lead['repo'] == 'org/one' and lead['revision'] == 'exact-tip'
    assert lead['status'] == 'repo_review_needed' and lead['outside_contributions']['status'] == 'unknown'
    q = Queue(tmp_path/'queue.json')
    next_step = agent_next.next_step(cfg, q, 'cfg.yml')
    assert next_step['status'] == 'repo_research' and next_step['lead']['repo'] == lead['repo']
    assert not q.items and not (tmp_path/'queue.json').exists()
    assert (tmp_path/'discovery-resume.json').read_bytes() == original
    assert repo_research.prepare(cfg) == lead
    repo_research.defer(cfg, 'linked guide requires invitation, none for this work')
    assert repo_research.prepare(cfg)['repo'] == 'org/two'


def test_partial_collection_preserves_selected_repo(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r: (_ for _ in ()).throw(repo_research.gh.GhError('unavailable')))
    with pytest.raises(repo_research.gh.GhError):
        repo_research.prepare(cfg)
    assert repo_research.load(cfg)['lead']['status'] == 'collecting'
    assert repo_research.load(cfg)['cursor'] == 0


def test_invalid_state_and_stop_do_not_search(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    (tmp_path/'repo_research.json').write_text('{broken')
    with pytest.raises(repo_research.Invalid):
        repo_research.prepare(cfg)
    (tmp_path/'STOP').write_text('stop')
    with pytest.raises(repo_research.safety.Blocked):
        repo_research.prepare(cfg)


def test_existing_local_work_still_wins_over_repo_research(tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    q = Queue(tmp_path/'queue.json')
    (tmp_path/'STOP').write_text('stop')
    assert agent_next.next_step(cfg, q, 'cfg.yml')['status'] == 'stopped'


def test_begin_and_propose_public_path_is_hypothesis_not_verified(monkeypatch, tmp_path):
    import subprocess
    setup_sources(monkeypatch)
    root = tmp_path/'checkout'
    root.mkdir()
    subprocess.run(['git', 'init', '-b', 'main', str(root)], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=root, check=True)
    (root/'source.py').write_text('def example():\n    return 1\n')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-m', 'fixture'], cwd=root, check=True, capture_output=True)
    tip = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    monkeypatch.setattr(repo_research.gh, 'api', lambda path, **kw:
                        {'default_branch': 'main', 'html_url': 'https://github.com/org/one'} if '/commits/' not in path else
                        {'sha': tip, 'html_url': 'https://github.com/org/one/commit/fixture'})
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a: '')
    monkeypatch.setattr(repo_research.policy_review, 'publication_route', lambda *a: 'issue_pr')
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: root)
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [])
    monkeypatch.setattr(repo_research.dedupe, 'recent_commit_hits', lambda *a, **kw: [])
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'), repo_first=True)
    repo_research.prepare(cfg)
    lead = repo_research.begin(cfg)
    assert lead['status'] == 'investigating'
    assert agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'cfg')['status'] == 'repo_investigation'
    with pytest.raises(repo_research.Invalid, match='inside'):
        repo_research.propose(cfg, '../outside', 1, 'source review hypothesis')
    with pytest.raises(repo_research.Invalid, match='outside'):
        repo_research.propose(cfg, 'source.py', 99, 'source review hypothesis')
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw:
                        [repo_research.dedupe.Match(9, 'possible prior work', 'https://github.com/org/one/issues/9', 'open', False, .5, 'similar')])
    with pytest.raises(repo_research.Invalid, match='possible existing work'):
        repo_research.propose(cfg, 'source.py', 1, 'source review hypothesis needing actual reproduction')
    assert not cfg.path('queue.json').exists()
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [])
    result = repo_research.propose(cfg, 'source.py', 1, 'source review hypothesis needing actual reproduction')
    item = Queue(cfg.path('queue.json')).items[result['id']]
    assert item.status == 'clean' and not item.verification and not item.submitted
    assert item.source_issue == 0 and 'not bug proof' in item.notes[0]
    with pytest.raises(repo_research.Invalid, match='already exists'):
        repo_research.propose(cfg, 'source.py', 1, 'source review hypothesis needing actual reproduction')


def test_policy_prerequisite_refuses_before_clone(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    repo_research.prepare(cfg)
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a: 'no policy review recorded')
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('clone reached')))
    with pytest.raises(repo_research.Invalid, match='policy review'):
        repo_research.begin(cfg)


def test_current_prohibition_remains_hold_not_permission(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r:
                        {'docs': [], 'anti_ai': False, 'agent_review': ['conditional restriction']})
    lead = repo_research.prepare(cfg)
    assert 'agent-specific' in lead['holds'][0]
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('clone reached')))
    with pytest.raises(repo_research.Invalid, match='restriction'):
        repo_research.begin(cfg)


def test_checkpoint_exposes_after_review_step_and_invalid_state(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    repo_research.prepare(cfg)
    checkpoint = agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'chosen.yml')
    assert checkpoint['after_source_review_argv'][-2:] == ['research-repo', '--begin']
    cfg.path('repo_research.json').write_text('{broken')
    assert agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'chosen.yml')['status'] == 'inspect_local'


def test_research_shares_run_lock_without_rewriting_journal(tmp_path):
    cfg = Config(state_dir=str(tmp_path))
    cfg.path('run.json').write_text('{"status":"discovery_budget_exhausted"}')
    with repo_research.locked(cfg):
        with pytest.raises(repo_research.Invalid, match='another run'):
            with repo_research.locked(cfg):
                pass
    assert cfg.path('run.json').read_text() == '{"status":"discovery_budget_exhausted"}'


def test_checkpoint_compacts_policy_text_without_discarding_saved_source(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r:
                        {'docs': [{'path': 'README.md', 'url': 'https://github.com/org/one/blob/main/README.md',
                                   'sha': 'policy-sha', 'text': 'full source text'}],
                         'anti_ai': False, 'agent_review': []})
    repo_research.prepare(cfg)
    result = repo_research.checkpoint(cfg, ['ossforge'])
    assert 'text' not in result['lead']['policy']['docs'][0]
    assert repo_research.load(cfg)['lead']['policy']['docs'][0]['text'] == 'full source text'
