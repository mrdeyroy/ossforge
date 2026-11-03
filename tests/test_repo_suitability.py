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


def test_native_monorepo_feature_list_is_not_resource_collection(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [
        {'name': 'package.json', 'type': 'file'}, {'name': 'api', 'type': 'dir'},
        {'name': 'web', 'type': 'dir'}, {'name': 'packages', 'type': 'dir'}])
    result = s.assess('org/app', 'sha', {'docs': [{'path': 'README.md',
        'text': "An awesome application. Here's a list of the core features: workflows and APIs."}]})
    assert result['status'] == 'native_feasibility_review_needed'
    assert not result['collection_signal']
    assert result['manifests'] == ['package.json']


def test_public_resource_identity_remains_collection_evidence(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [{'name': 'scripts', 'type': 'dir'}])
    for text in ('It includes an extensive list of public APIs from many domains.',
                 '# List of Free Learning Resources In Many Languages',
                 '# [Awesome Python](https://example.invalid)',
                 '# The System Design Primer',
                 'A list of programming tutorials in which developers learn.'):
        assert s.assess('org/resources', 'sha', {'docs': [{'path': 'README.md', 'text': text}]})['status'] == 'collection_review_needed'


def test_marketing_collection_mentions_do_not_establish_repo_identity(monkeypatch):
    monkeypatch.setattr(s.gh, 'api', lambda *a, **kw: [{'name': 'package.json', 'type': 'file'}])
    for text in ('An awesome platform with a collection of tools.',
                 'See the list of supported models and list of features.',
                 'We curated our API docs for an awesome developer experience.'):
        result = s.assess('org/platform', 'sha', {'docs': [{'path': 'README.md', 'text': text}]})
        assert not result['collection_signal']
        assert result['status'] == 'native_feasibility_review_needed'
