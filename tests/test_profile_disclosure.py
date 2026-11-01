import pytest

from ossforge import config, policy, profile
from ossforge.outcomes import Stats


def test_classify_policy_statuses():
    assert policy.classify_text("Please disclose any use of AI tools in your PR.")[0] == "mandatory"
    assert policy.classify_text("No need to disclose AI tools you used.")[0] == "waived"
    assert policy.classify_text("We discuss AI disclosure on the forum.")[0] == "ambiguous"
    assert policy.classify_text("Run the tests before opening a PR.")[0] == "none"


def test_readme_policy_counts_as_scoped_evidence():
    d = policy.classify_disclosure({"README.md": "Contributors must disclose LLM assistance."})
    assert d.status == "mandatory" and d.source == "README.md"


def test_conflicting_docs_are_ambiguous():
    d = policy.classify_disclosure({"CONTRIBUTING.md": "You must disclose AI use.",
                                    "README.md": "No need to disclose AI use."})
    assert d.status == "ambiguous"


def test_decide_disclosure_matrix():
    must = {"CONTRIBUTING.md": "You must disclose AI use."}
    unclear = {"CONTRIBUTING.md": "AI disclosure is discussed in the wiki."}
    quiet = {"CONTRIBUTING.md": "Add tests."}
    assert policy.decide_disclosure("auto", must)[0] is True
    assert policy.decide_disclosure(True, must)[0] is True
    with pytest.raises(policy.NeedsReview):
        policy.decide_disclosure(False, must)  # explicit false never overrides a mandatory policy
    with pytest.raises(policy.NeedsReview):
        policy.decide_disclosure("auto", unclear)
    assert policy.decide_disclosure(False, unclear)[0] is False  # human decided
    assert policy.decide_disclosure(True, unclear)[0] is True
    assert policy.decide_disclosure("auto", quiet)[0] is False
    assert policy.decide_disclosure(True, quiet)[0] is True


def test_default_disclosure_is_auto():
    assert config.Config().disclosure == "auto"


def test_tally_skips_own_repos():
    items = [{"repository_url": "https://api.github.com/repos/pallets/click"},
             {"repository_url": "https://api.github.com/repos/pallets/click"},
             {"repository_url": "https://api.github.com/repos/Me/fork"}]
    assert profile.tally(items, "me", "merged") == {"pallets/click": 2}


def test_history_import_boosts_but_closed_never_penalises(tmp_path):
    s = Stats(tmp_path / "s.json")
    s.set_history("a/b", 2, 0)
    s.set_history("a/b", 2, 0)
    assert s.repo_boost("a/b") == 20
    s.set_history("c/d", 0, 5)
    assert s.repo_boost("c/d") == 0
    s.record_repo("c/d", "closed_unmerged")
    assert s.repo_boost("c/d") == 0
