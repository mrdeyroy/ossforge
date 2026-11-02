from ossforge import policy, radar, vet


def test_claim_detection():
    assert vet.comment_claims_issue("I'll take this one")
    assert not vet.comment_claims_issue("Thanks for the report")


def test_decide_anti_ai_wins():
    pol = policy.scan_text("human-authored only", "README.md")
    code, _ = vet.decide(assigned=False, claimed=False, open_pr_count=0, clear=True,
                         has_contributing=True, anti_ai=pol, repo_ok=True)
    assert code == "anti_ai"


def test_decide_approve_and_skip():
    ok = policy.PolicyResult(False)
    base = dict(assigned=False, claimed=False, clear=True, has_contributing=True, anti_ai=ok, repo_ok=True)
    assert vet.decide(open_pr_count=0, **base)[0] == "approve"
    assert vet.decide(open_pr_count=1, **base)[0] == "skip"


def test_radar_scoring():
    good = radar.RepoSignals(40, 10, 0.1, 3, 0.6, 5000, 2)
    dead = radar.RepoSignals(0, 120, 0.6, None, None, 100, 200)
    assert radar.score_repo(good)[0] >= 75
    assert radar.score_repo(dead)[0] < 45


def test_publication_policy_listing_error_is_unknown_not_missing(monkeypatch):
    import pytest
    from ossforge import gh, submit
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (_ for _ in ()).throw(gh.GhError('service unavailable', 503)))
    with pytest.raises(submit.Refused, match='policy'):
        submit._policy_files('owner/repo')


def test_fresh_file_read_bypasses_negative_and_content_cache(monkeypatch):
    import base64
    from ossforge import gh
    gh._MISSING.add(('owner/repo', 'AI_POLICY.md', None))
    calls = []
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (calls.append(k) or {'encoding': 'base64', 'content': base64.b64encode(b'no AI-generated contributions').decode()}))
    assert gh.file_text('owner/repo', 'AI_POLICY.md', fresh=True) == 'no AI-generated contributions'
    assert calls[0]['fresh'] is True


def test_strict_policy_listing_allows_missing_optional_directory_not_missing_root(monkeypatch):
    import pytest
    from ossforge import gh
    def api(path, **kw):
        if path.endswith('/.github'):
            raise gh.GhError('not found', 404)
        return []
    monkeypatch.setattr(gh, 'api', api)
    assert gh.existing_files('owner/repo', ('README.md', '.github/AI_POLICY.md'), fresh=True, strict=True) == []
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (_ for _ in ()).throw(gh.GhError('not found', 404)))
    with pytest.raises(gh.GhError):
        gh.existing_files('owner/repo', ('README.md',), fresh=True, strict=True)
