from ossforge import gh, vet


def test_foreign_dependency_changelog_is_not_target_issue_work(monkeypatch):
    monkeypatch.setattr(vet.repo_access, 'pr_restriction', lambda r: '')
    monkeypatch.setattr(gh, 'api', lambda path, **kw: [] if path.endswith('/comments') else {
        'state': 'open', 'body': 'Steps to reproduce: existing buffer should accumulate data but actual behavior loses records.', 'assignees': []})
    monkeypatch.setattr(vet, 'policy_texts', lambda r: {'CONTRIBUTING.md': 'Contributions welcome'})
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: [{
        'state': 'closed', 'title': 'chore: bump dependencies',
        'body': '<li>Fix playback <a href="https://redirect.github.com/yt-dlp/yt-dlp/issues/15278">#15278</a></li>'}])
    assert vet.vet_issue('Significant-Gravitas/AutoGPT', 15278).decision == 'approve'


def test_reference_disambiguation_keeps_local_and_unknown_hits():
    from ossforge.references import may_reference
    foreign = '<a href="https://redirect.github.com/other/repo/pull/42">#42</a>'
    for body in [foreign, '[#42](https://github.com/other/repo/issues/42)',
                 'other/repo#42', 'https://github.com/other/repo/issues/42']:
        assert not may_reference({'body': body}, 'org/repo', 42)
    for body in [foreign + ' Fixes #42', foreign + ' org/repo#42',
                 foreign + ' https://github.com/org/repo/issues/42',
                 foreign + ' unknown issue 42', 'Fixes #420', '',
                 '<a href="https://github.com/ORG/REPO/issues/42">#42</a>']:
        assert may_reference({'body': body}, 'org/repo', 42)
    assert may_reference({'body': foreign, 'title': 'Fix #42'}, 'org/repo', 42)
    assert may_reference({'state': 'closed'}, 'org/repo', 42)


def test_foreign_closed_hit_does_not_hide_real_open_competition(monkeypatch):
    monkeypatch.setattr(vet.repo_access, 'pr_restriction', lambda r: '')
    monkeypatch.setattr(gh, 'api', lambda path, **kw: [] if path.endswith('/comments') else {
        'state': 'open', 'body': 'Steps to reproduce: invalid data should be retained; actual behavior deletes it.', 'assignees': []})
    monkeypatch.setattr(vet, 'policy_texts', lambda r: {})
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: [
        {'state': 'closed', 'body': '[#42](https://github.com/other/repo/issues/42)'},
        {'state': 'open', 'body': 'Fixes #42'}])
    verdict = vet.vet_issue('org/repo', 42)
    assert verdict.decision == 'skip'
    assert verdict.reasons == ['1 open PR(s) reference it']


def test_publication_reference_filter_keeps_timeline_and_local_work(monkeypatch):
    import pytest
    from ossforge import submit
    from ossforge.queue import Item
    item = Item('x', 'org/repo', '', 0, 'issue', 'lead', source_issue=42)
    foreign = {'pull_request': {}, 'state': 'closed',
               'body': '<a href="https://github.com/other/repo/issues/42">#42</a>'}
    activity = []
    monkeypatch.setattr(gh, 'api', lambda path, **kw: activity if path.endswith('/timeline') else
                        [] if path.endswith('/comments') else
                        {'state': 'open', 'html_url': 'https://github.com/org/repo/issues/42'})
    refs = [foreign]
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **kw: refs)
    submit._source_work_gate(item)
    refs.append({'pull_request': {}, 'body': 'Fixes #42', 'state': 'open'})
    with pytest.raises(submit.Refused, match='referenced PR'):
        submit._source_work_gate(item)
    refs.pop()
    activity.append({'event': 'cross-referenced', 'source': {'issue': {'pull_request': {}}}})
    with pytest.raises(submit.Refused, match='referenced PR'):
        submit._source_work_gate(item)
