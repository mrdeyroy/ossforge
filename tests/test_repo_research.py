import pytest
from ossforge import repo_research, agent_next, radar, acceptance, research_session
from ossforge.config import Config
from ossforge.queue import Queue


def prepare(cfg):
    if cfg.repo_first and not cfg.path('research_session.json').exists():
        research_session.start(cfg, 3600)
    return repo_research.prepare(cfg)


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
    lead = prepare(cfg)
    assert lead['repo'] == 'org/one' and lead['revision'] == 'exact-tip'
    assert lead['status'] == 'repo_review_needed' and lead['outside_contributions']['status'] == 'unknown'
    q = Queue(tmp_path/'queue.json')
    next_step = agent_next.next_step(cfg, q, 'cfg.yml')
    assert next_step['status'] == 'repo_research' and next_step['lead']['repo'] == lead['repo']
    assert not q.items and not (tmp_path/'queue.json').exists()
    assert (tmp_path/'discovery-resume.json').read_bytes() == original
    assert prepare(cfg) == lead
    repo_research.defer(cfg, 'linked guide requires invitation, none for this work')
    assert prepare(cfg)['repo'] == 'org/two'


def test_partial_collection_preserves_selected_repo(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r: (_ for _ in ()).throw(repo_research.gh.GhError('unavailable')))
    with pytest.raises(repo_research.gh.GhError):
        prepare(cfg)
    assert repo_research.load(cfg)['lead']['status'] == 'collecting'
    assert repo_research.load(cfg)['cursor'] == 0


def test_invalid_state_and_stop_do_not_search(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    (tmp_path/'repo_research.json').write_text('{broken')
    with pytest.raises(repo_research.Invalid):
        prepare(cfg)
    (tmp_path/'STOP').write_text('stop')
    with pytest.raises(repo_research.safety.Blocked):
        prepare(cfg)


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
    prepare(cfg)
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
    prepare(cfg)
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a: 'no policy review recorded')
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('clone reached')))
    with pytest.raises(repo_research.Invalid, match='policy review'):
        repo_research.begin(cfg)


def test_current_prohibition_remains_hold_not_permission(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r:
                        {'docs': [], 'anti_ai': False, 'agent_review': ['conditional restriction']})
    lead = prepare(cfg)
    assert 'agent-specific' in lead['holds'][0]
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: (_ for _ in ()).throw(AssertionError('clone reached')))
    with pytest.raises(repo_research.Invalid, match='restriction'):
        repo_research.begin(cfg)


def test_checkpoint_exposes_after_review_step_and_invalid_state(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    prepare(cfg)
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
    prepare(cfg)
    result = repo_research.checkpoint(cfg, ['ossforge'])
    assert 'text' not in result['lead']['policy']['docs'][0]
    assert repo_research.load(cfg)['lead']['policy']['docs'][0]['text'] == 'full source text'


def test_held_and_qualification_are_visible_without_blocking_independent_research(tmp_path, monkeypatch):
    from ossforge.queue import Item
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    q = Queue(cfg.path('queue.json'))
    q.add(Item('held', 'org/held', 'a.py', 1, 'bug', 'held work', status='held', hold_reason='permission missing'))
    step = agent_next.next_step(cfg, q, 'cfg')
    assert step['status'] == 'held_work'
    assert step['next_argv'][-1] == 'research-repo'
    # An explicit independent research command remains reachable, not an
    # automatic unhold or a review dismissal.
    setup_sources(monkeypatch)
    assert prepare(cfg)['status'] == 'repo_review_needed'
    assert agent_next.next_step(cfg, q, 'cfg')['status'] == 'held_work'
    q.items.clear()
    monkeypatch.setattr(agent_next.qualification, 'pending', lambda *a: [{'repo': 'org/review', 'number': 42}])
    step = agent_next.next_step(cfg, q, 'cfg')
    assert step['status'] == 'review_needed'
    assert step['review_argv'][-2:] == ['org/review', '42']
    assert step['next_argv'][-1] == 'research-repo'


def test_deferral_scope_and_exhaustion_do_not_reselect_rejections(tmp_path, monkeypatch):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), repo_first=True)
    prepare(cfg)
    repo_research.defer(cfg, 'no supported native reproduction')
    repo_research.prepare(cfg)
    repo_research.defer(cfg, 'contribution prerequisite unresolved')
    assert repo_research.prepare(cfg)['status'] == 'repo_pool_exhausted'
    assert repo_research.prepare(cfg)['status'] == 'repo_pool_exhausted'
    assert agent_next.next_step(cfg, Queue(cfg.path('queue.json')), 'cfg')['status'] == 'repo_pool_exhausted'
    assert len(repo_research.load(cfg)['deferred']) == 2
    cfg.min_stars += 1  # active session refuses scope changes before reassessment
    with pytest.raises(research_session.Invalid, match='configuration changed'):
        repo_research.prepare(cfg)


def test_begin_empty_checkout_returns_actionable_refusal(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'))
    repo_research.prepare(cfg)
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a: '')
    monkeypatch.setattr(repo_research.policy_review, 'publication_route', lambda *a: 'issue_pr')
    root = tmp_path/'empty'
    root.mkdir()
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: root)
    monkeypatch.setattr(repo_research.submit, '_run', lambda *a: (_ for _ in ()).throw(repo_research.submit.Refused('no HEAD')))
    with pytest.raises(repo_research.Invalid, match='no readable HEAD; preserve'):
        repo_research.begin(cfg)
    assert root.exists()
    assert repo_research.load(cfg)['lead']['repo'] == 'org/one'
@pytest.fixture
def adoption(monkeypatch, tmp_path):
    import subprocess
    from datetime import datetime, timedelta, timezone
    setup_sources(monkeypatch)
    root = tmp_path/'checkout'
    root.mkdir()
    for cmd in (['init', '-b', 'main'], ['config', 'user.name', 'Test'], ['config', 'user.email', 'test@example.invalid']):
        subprocess.run(['git', *cmd], cwd=root, check=True, capture_output=True)
    (root/'source.py').write_text('def example():\n    return 1\n')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-m', 'fixture'], cwd=root, check=True, capture_output=True)
    tip = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    source = {'state': 'open', 'html_url': 'https://github.com/org/one/issues/9',
              'created_at': (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}
    def api(path, **kw):
        if '/issues/' in path:
            return source
        return {'sha': tip, 'html_url': 'https://github.com/org/one/commit/fixture'} if '/commits/' in path else {
            'default_branch': 'main', 'html_url': 'https://github.com/org/one'}
    monkeypatch.setattr(repo_research.gh, 'api', api)
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a: '')
    monkeypatch.setattr(repo_research.policy_review, 'publication_route', lambda *a: 'issue_pr')
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: root)
    monkeypatch.setattr(repo_research.vet, 'vet_issue', lambda *a, **kw: repo_research.vet.Verdict('org/one#9', 'approve'))
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [
        repo_research.dedupe.Match(9, 'matching issue', source['html_url'], 'open', False, .8, 'similar')])
    monkeypatch.setattr(repo_research.dedupe, 'recent_commit_hits', lambda *a, **kw: [])
    cfg = Config(state_dir=str(tmp_path/'state'), kill_file=str(tmp_path/'STOP'), repo_first=True)
    prepare(cfg)
    repo_research.begin(cfg)
    return cfg, source


def test_eligible_old_issue_reused_as_unverified_candidate(adoption):
    cfg, _ = adoption
    result = repo_research.propose(cfg, 'source.py', 1, 'matching code defect hypothesis', 9)
    item = Queue(cfg.path('queue.json')).items[result['id']]
    assert item.source_issue == 9 and item.kind == 'issue' and item.status == 'clean'
    assert not item.verification and not item.submitted
    assert 'https://github.com/org/one/issues/9' in item.notes


@pytest.mark.parametrize('decision,reasons', [
    ('skip', ['claimed in comments']), ('skip', ['assigned']),
    ('skip', ['1 open PR(s) reference it']), ('skip', ['closed or merged PR reference requires review']),
    ('anti_ai', ['policy prohibition']), ('skip', ['comment coverage incomplete'])])
def test_old_age_never_bypasses_fresh_vetting(adoption, monkeypatch, decision, reasons):
    cfg, _ = adoption
    monkeypatch.setattr(repo_research.vet, 'vet_issue', lambda *a, **kw:
                        repo_research.vet.Verdict('org/one#9', decision, reasons))
    with pytest.raises(repo_research.Invalid, match='not eligible'):
        repo_research.propose(cfg, 'source.py', 1, 'matching code defect hypothesis', 9)
    assert not cfg.path('queue.json').exists()


@pytest.mark.parametrize('change', [
    {'state': 'closed'}, {'pull_request': {}}, {'created_at': 'bad'},
    {'created_at': '2999-01-01T00:00:00Z'}, {'created_at': None},
    {'html_url': 'https://github.com/other/repo/issues/9'}])
def test_issue_identity_time_and_open_state_required(adoption, change):
    cfg, source = adoption
    source.update(change)
    with pytest.raises(repo_research.Invalid):
        repo_research.propose(cfg, 'source.py', 1, 'matching code defect hypothesis', 9)
    assert not cfg.path('queue.json').exists()


def test_adoption_keeps_other_duplicates_and_requires_match(adoption, monkeypatch):
    cfg, _ = adoption
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [])
    with pytest.raises(repo_research.Invalid, match='does not match'):
        repo_research.propose(cfg, 'source.py', 1, 'unrelated candidate hypothesis', 9)
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [
        repo_research.dedupe.Match(n, 'prior work', f'https://github.com/org/one/issues/{n}', 'open', False, .8, 'similar') for n in (9,10)])
    with pytest.raises(repo_research.Invalid, match='possible existing work'):
        repo_research.propose(cfg, 'source.py', 1, 'matching code defect hypothesis', 9)
    assert not cfg.path('queue.json').exists()
