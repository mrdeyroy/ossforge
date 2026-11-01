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
