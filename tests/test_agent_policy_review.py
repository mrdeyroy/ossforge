from ossforge import policy, vet


def test_observed_autonomous_restriction_requires_review_not_global_ai_ban():
    text = "We'd also ask autonomous agents not to open any PRs or issues for the moment.\nAI-assisted contributions are welcome."
    result = policy.scan_text(text, 'CONTRIBUTING.md')
    assert not result.anti_ai
    assert result.agent_review and result.source == 'CONTRIBUTING.md'
    decision, reasons = vet.decide(assigned=False, claimed=False, open_pr_count=0, clear=True,
                                   has_contributing=True, anti_ai=result, repo_ok=True)
    assert decision == 'skip' and 'policy needs review' in reasons[0]


def test_conditional_first_time_agent_restriction_is_review_not_blanket_ban():
    result = policy.scan_text('First-time contributors should not use code agents to submit PRs or issues.')
    assert result.agent_review and not result.anti_ai


def test_permission_negation_and_human_assistance_alone_do_not_trigger():
    for text in ['AI-assisted contributions are welcome.',
                 'Autonomous agents are not prohibited from opening PRs.',
                 'We do not prohibit code agents.',
                 'There is no restriction on autonomous agents opening issues.',
                 'Human submitters should review every AI-assisted contribution.']:
        result = policy.scan_text(text)
        assert not result.agent_review and not result.anti_ai


def test_hard_prohibition_still_wins_over_earlier_review_signal():
    result = policy.scan_files({'README.md': 'Autonomous agents should not submit issues.',
                                'CONTRIBUTING.md': 'human-authored only'})
    assert result.anti_ai and result.source == 'CONTRIBUTING.md'


def test_loop_local_policy_review_holds_issue_before_driver(monkeypatch, tmp_path):
    from ossforge import loop, scout
    from ossforge.config import Config
    from ossforge.queue import Queue
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'), work_kind='fix')
    candidate = scout.Candidate('org/repo', 42, 'Bug', 'https://github.com/org/repo/issues/42', 80,
                                vet.Verdict('org/repo#42', 'approve'))
    def discover(*a, **kw):
        scout.LAST_FUNNEL.clear()
        scout.LAST_FUNNEL.update(stopped='', fetched=1, kept=1, approved=1)
        return [candidate]
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [])
    monkeypatch.setattr(loop.scout, 'scout', discover)
    monkeypatch.setattr(loop.hunt, 'clone', lambda *a: tmp_path)
    monkeypatch.setattr(loop.hunt, 'policy_of', lambda *a: policy.scan_text('Autonomous agents should not submit issues.', 'AGENTS.md'))
    loop.run_once(cfg)
    q = Queue(cfg.path('queue.json'))
    assert not q.by_status('clean')
    assert q.items['org/repo#42:issue'].status == 'held'
    assert 'policy needs review' in q.items['org/repo#42:issue'].hold_reason


def test_hunt_review_signal_stops_before_scan(monkeypatch, tmp_path):
    from ossforge import hunt
    from ossforge.config import Config
    monkeypatch.setattr(hunt, 'clone', lambda *a: tmp_path)
    monkeypatch.setattr(hunt, 'policy_of', lambda *a: policy.scan_text('Autonomous agents should not submit issues.', 'README.md'))
    monkeypatch.setattr(hunt.audit_mod, 'scan_tree', lambda *a: (_ for _ in ()).throw(AssertionError('scan reached')))
    result = hunt.hunt(Config(), 'org/repo', None, None)
    assert result['policy_review_needed'] == 'README.md' and result['clean'] == 0


def test_vet_uncontested_issue_with_restriction_is_not_approved(monkeypatch):
    from ossforge import gh
    monkeypatch.setattr(vet.repo_access, 'pr_restriction', lambda r: '')
    monkeypatch.setattr(gh, 'api', lambda path, **kw: [] if path.endswith('/comments') else {
        'state': 'open', 'body': 'Steps to reproduce: invalid vector should retain the record but actual deletion occurs.', 'assignees': []})
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: [])
    monkeypatch.setattr(vet, 'policy_texts', lambda r: {'CONTRIBUTING.md': 'Autonomous agents should not submit issues.'})
    verdict = vet.vet_issue('org/repo', 1)
    assert verdict.decision == 'skip' and 'policy needs review' in verdict.reasons[0]


def test_ordinary_code_advice_is_not_contribution_restriction():
    result = policy.scan_text('Code agents should not use global variables. Issues are tracked on GitHub.')
    assert not result.agent_review and not result.anti_ai


def test_submit_refuses_review_signal_before_publication(monkeypatch, tmp_path):
    import pytest
    from ossforge import submit
    from ossforge.config import Config
    from ossforge.queue import Item
    from ossforge.limiter import DailyLimiter
    item = Item('a', 'org/repo', 'a.py', 1, 'kind', 'detail', status='verified', issue_title='t', issue_body='b',
                pr_title='t', pr_body='b', branch='fix/x', clone='/not-used')
    cfg = Config(kill_file=str(tmp_path/'STOP'))
    monkeypatch.setattr(submit, '_publication_mode', lambda *a: 'issue_pr')
    monkeypatch.setattr(submit.safety, 'repo_allowed', lambda *a: '')
    for gate in ('_repo_access_gate', '_upstream_gate', '_source_work_gate'):
        monkeypatch.setattr(submit, gate, lambda *a: None)
    monkeypatch.setattr(submit, '_policy_files', lambda *a: {'CONTRIBUTING.md': 'Autonomous agents should not submit issues.'})
    monkeypatch.setattr(submit.policy_review, 'check', lambda *a: (_ for _ in ()).throw(AssertionError('review clearance reached')))
    with pytest.raises(submit.Refused, match='policy needs review'):
        submit.preflight(item, DailyLimiter(tmp_path/'daily.json'), cfg, [])


def test_exact_observed_policy_excerpt_with_conflicting_welcome():
    # Public CONTRIBUTING.md blob 972c62be912e12ffe795678b9b8c5d3230286f2d.
    # Preserve the conditional restriction and assistance welcome; neither is
    # automatically interpreted as permission or a global prohibition.
    text = """> **we ask that first-time contributors do not use code agents to create issues or PRs** at this time.
> We'd also ask autonomous agents not to open any PRs or issues for the moment.
We understand that code agents are extremely powerful tools, and many people at Hugging Face use them in their work.
"""
    result = policy.scan_text(text, 'CONTRIBUTING.md')
    assert len(result.agent_review) == 2 and not result.anti_ai
    assert any('first-time' in r for r in result.agent_review)
    assert any('for the moment' in r for r in result.agent_review)


def test_hard_ban_and_review_in_same_document_stays_hard_ban():
    result = policy.scan_files({'CONTRIBUTING.md': 'Human-authored only. Autonomous agents should not submit issues.'})
    assert result.anti_ai and not result.agent_review


def test_permission_in_separate_contrast_clause_does_not_suppress_restriction():
    result = policy.scan_text('We do not forbid human AI assistance, but autonomous agents should not submit PRs.')
    assert result.agent_review and not result.anti_ai


def test_markdown_line_wrap_preserves_agent_restriction():
    result = policy.scan_text('Autonomous agents should not\nsubmit PRs or issues.')
    assert result.agent_review and not result.anti_ai


def test_open_source_code_advice_is_not_publication_restriction():
    result = policy.scan_text('Autonomous agents should not open-source code without fixing all reported issues.')
    assert not result.agent_review and not result.anti_ai


def test_hunt_prioritizes_hard_ban_even_for_mixed_result(monkeypatch, tmp_path):
    from ossforge import hunt
    from ossforge.config import Config
    monkeypatch.setattr(hunt, 'clone', lambda *a: tmp_path)
    monkeypatch.setattr(hunt, 'policy_of', lambda *a: policy.PolicyResult(True, ['human-authored only'],
                                                                        'CONTRIBUTING.md', ['review']))
    result = hunt.hunt(Config(), 'org/repo', None, None)
    assert result['anti_ai'] == 'CONTRIBUTING.md' and not result.get('policy_review_needed')
