import pytest
from ossforge import repo_suitability as s


def test_curated_lists_are_not_assumed_native_code_targets(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [
        {'name': 'README.md', 'type': 'file'}, {'name': 'scripts', 'type': 'dir'}])
    result = s.assess('org/list', 'sha', {'docs': [{'path': 'README.md', 'text': 'A curated list of APIs'}]})
    assert result['status'] == 'collection_review_needed'
    assert result['revision'] == 'sha'


def test_collection_words_do_not_exclude_real_library_layout(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [
        {'name': 'pyproject.toml', 'type': 'file', 'html_url': 'observed-manifest'},
        {'name': 'src', 'type': 'dir'}, {'name': 'tests', 'type': 'dir'}])
    result = s.assess('org/library', 'sha', {'docs': [{'path': 'README.md', 'text': 'An awesome library'}]})
    assert result['status'] == 'native_candidate'
    assert result['sources'][0]['url'] == 'observed-manifest'


def test_nonstandard_layout_needs_review_not_claim_of_no_code(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [{'name': 'custom', 'type': 'dir'}])
    assert s.assess('org/code', 'sha', {})['status'] == 'native_feasibility_review_needed'


@pytest.mark.parametrize('listing', [None, {}, [{'type': 'file'}]])
def test_incomplete_listing_fails_closed(monkeypatch, listing):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: listing)
    with pytest.raises(s.gh.GhError):
        s.assess('org/code', 'sha', {})
