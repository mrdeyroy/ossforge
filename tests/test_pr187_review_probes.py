"""Independent review probes for ossforge PR #187 (repo-first research)."""
import subprocess
from ossforge import repo_research, agent_next, radar, acceptance, policy_review, gh, research_session
from ossforge.config import Config
from ossforge.queue import Queue, Item, item_id


def setup_sources(monkeypatch):
    monkeypatch.setattr(repo_research.discovery, 'discover_broad_repos', lambda *a: ['org/one', 'org/two'])
    monkeypatch.setattr(repo_research.repo_access, 'pr_restriction', lambda *a: '')
    monkeypatch.setattr(repo_research.radar, 'analyze', lambda r: radar.RepoScore(r, 80, 'Go'))
    monkeypatch.setattr(repo_research.acceptance, 'evidence', lambda r: acceptance.Acceptance(r, 'unknown'))
    monkeypatch.setattr(repo_research.policy_review, 'snapshot', lambda r, **kw: {'docs': [], 'anti_ai': False, 'agent_review': [], 'scanned_locations': [], 'extra_paths': []})
    monkeypatch.setattr(repo_research.gh, 'api', lambda path, **kw:
                        {'default_branch': 'main', 'html_url': 'https://github.com/org/one'} if '/commits/' not in path else
                        {'sha': 'exact-tip', 'html_url': 'https://github.com/org/one/commit/exact-tip'})


def make_checkout(tmp_path):
    root = tmp_path / 'checkout'
    root.mkdir(exist_ok=True)
    subprocess.run(['git', 'init', '-b', 'main', str(root)], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=root, check=True)
    (root / 'source.py').write_text('def example():\n    return 1\n')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-qm', 'fixture'], cwd=root, check=True)
    return root, subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def begin_ready(monkeypatch, tmp_path):
    setup_sources(monkeypatch)
    root, tip = make_checkout(tmp_path)
    monkeypatch.setattr(repo_research.gh, 'api', lambda path, **kw:
                        {'default_branch': 'main', 'html_url': 'https://github.com/org/one'} if '/commits/' not in path else
                        {'sha': tip, 'html_url': 'https://github.com/org/one/commit/fixture'})
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a, **kw: '')
    monkeypatch.setattr(repo_research.policy_review, 'publication_route', lambda *a: 'issue_pr')
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: root)
    monkeypatch.setattr(repo_research.dedupe, 'find_matches', lambda *a, **kw: [])
    monkeypatch.setattr(repo_research.dedupe, 'recent_commit_hits', lambda *a, **kw: [])
    cfg = Config(state_dir=str(tmp_path / 'state'), kill_file=str(tmp_path / 'STOP'), repo_first=True)
    research_session.start(cfg, 3600) if cfg.repo_first and not cfg.path('research_session.json').exists() else None
    repo_research.prepare(cfg)
    repo_research.begin(cfg)
    return cfg, root


def test_begin_with_issue_first_route_raises_bare_ValueError_not_Invalid(monkeypatch, tmp_path):
    """CLI catches repo_research.Invalid but publication_route raises plain ValueError."""
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path / 'state'), kill_file=str(tmp_path / 'STOP'))
    research_session.start(cfg, 3600) if cfg.repo_first and not cfg.path('research_session.json').exists() else None
    repo_research.prepare(cfg)
    monkeypatch.setattr(repo_research.policy_review, 'check', lambda *a, **kw: '')
    # Restore the REAL publication_route with a recorded issue_first route.
    monkeypatch.setattr(repo_research.policy_review, 'publication_route', policy_review.publication_route)
    monkeypatch.setattr(policy_review, 'snapshot', lambda r, **kw: {'docs': [], 'anti_ai': False, 'agent_review': [], 'scanned_locations': [], 'extra_paths': []})
    policy_review.record(cfg, 'org/one', {'docs': [], 'scanned_locations': [], 'extra_paths': []},
                         'guide wants an issue discussion first', publication_route='issue_first')
    try:
        repo_research.begin(cfg)
        raised = None
    except Exception as exc:
        raised = exc
    print('\nraised:', type(raised).__module__, type(raised).__name__, '->', raised)
    assert isinstance(raised, repo_research.Invalid), f'CLI would crash with uncaught {type(raised).__name__}: {raised}'


def test_propose_dirty_checkout_raises_StaleEvidence_not_Invalid(monkeypatch, tmp_path):
    """The designed Invalid("investigation checkout changed") is unreachable for a dirty tree."""
    cfg, root = begin_ready(monkeypatch, tmp_path)
    (root / 'source.py').write_text('def example():\n    return 2  # IDE edit\n')  # uncommitted
    try:
        repo_research.propose(cfg, 'source.py', 1, 'source review hypothesis needing actual reproduction')
        raised = None
    except Exception as exc:
        raised = exc
    print('\nraised:', type(raised).__module__, type(raised).__name__, '->', raised)
    assert isinstance(raised, repo_research.Invalid), f'CLI would crash with uncaught {type(raised).__name__}: {raised}'


def test_begin_dirty_existing_clone_raises_RuntimeError(monkeypatch, tmp_path):
    """hunt.clone raises plain RuntimeError; CLI research branch does not catch it."""
    cfg, root = begin_ready(monkeypatch, tmp_path)
    repo_research.defer(cfg, 'done with one')
    research_session.start(cfg, 3600) if cfg.repo_first and not cfg.path('research_session.json').exists() else None
    repo_research.prepare(cfg)  # selects org/two
    monkeypatch.setattr(repo_research.hunt, 'clone', lambda *a: (_ for _ in ()).throw(RuntimeError('existing checkout is dirty or incomplete; preserve it and inspect before retry')))
    try:
        repo_research.begin(cfg)
        raised = None
    except Exception as exc:
        raised = exc
    print('\nraised:', type(raised).__module__, type(raised).__name__, '->', raised)
    assert isinstance(raised, repo_research.Invalid), f'CLI would crash with uncaught {type(raised).__name__}: {raised}'


def test_read_budget_exhaustion_escapes_research_cli(monkeypatch, tmp_path):
    """gh.ReadBudgetExceeded is a RuntimeError, not caught by the research branch in cli.main."""
    from ossforge import cli
    setup_sources(monkeypatch)
    monkeypatch.setattr(repo_research.discovery, 'discover_broad_repos',
                        lambda *a: (_ for _ in ()).throw(gh.ReadBudgetExceeded('budget exhausted')))
    cfgfile = tmp_path / 'cfg.yml'
    cfgfile.write_text(f'state_dir: {tmp_path}/state\nkill_file: {tmp_path}/STOP\nrepo_first: true\n')
    try:
        rc = cli.main(['--config', str(cfgfile), 'research-repo'])
        raised = None
    except Exception as exc:
        raised = exc
        rc = None
    print('\nrc:', rc, 'raised:', type(raised).__name__ if raised else None)
    assert raised is None, f'CLI crashed with uncaught {type(raised).__name__}: {raised}'


def test_repo_first_masks_pending_issue_handoff_and_held_work(tmp_path):
    """recover_issue_handoff / held_work are unreachable while repo_first is on."""
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path / 'STOP'), repo_first=True)
    q = Queue(tmp_path / 'queue.json')
    q.add(Item(item_id('org/x', 'a.py', 'bug', 3), 'org/x', 'a.py', 3, 'bug', 'real issue lead',
               status='found', source_issue=42))
    q.save()
    step = agent_next.next_step(cfg, Queue(tmp_path / 'queue.json'), 'cfg.yml')
    print('\nwith pending issue handoff ->', step['status'])
    assert step['status'] == 'recover_issue_handoff', f'masked by repo-first checkpoint: {step["status"]}'


def test_repo_first_masks_interrupted_issue_discovery_journal(tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path / 'STOP'), repo_first=True)
    cfg.path('run.json').write_text('{"status": "interrupted"}')
    step = agent_next.next_step(cfg, Queue(tmp_path / 'queue.json'), 'cfg.yml')
    print('\nwith interrupted journal ->', step['status'])
    assert step['status'] == 'review_incomplete_discovery', f'masked by repo-first checkpoint: {step["status"]}'


def test_deferred_repo_is_reproposed_after_cursor_wraps(monkeypatch, tmp_path):
    """defer records history but selection never consults it; a 2-repo pool alternates forever."""
    setup_sources(monkeypatch)
    cfg = Config(state_dir=str(tmp_path / 'state'), kill_file=str(tmp_path / 'STOP'))
    first = repo_research.prepare(cfg)['repo']
    repo_research.defer(cfg, 'unsuitable: no native tests')
    second = repo_research.prepare(cfg)['repo']
    repo_research.defer(cfg, 'unsuitable: policy forbids')
    third = repo_research.prepare(cfg)['status']
    print('\nselection sequence:', first, second, third)
    assert third == 'repo_pool_exhausted'
