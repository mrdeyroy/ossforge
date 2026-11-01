from ossforge import config, policy, profile
from ossforge.outcomes import Stats


def test_requires_disclosure_detects_both_orders():
    assert policy.requires_disclosure("Please disclose any use of AI tools in your PR.")
    assert policy.requires_disclosure("If you used an LLM, you must mention it in the description.")
    assert not policy.requires_disclosure("Run the tests before opening a PR.")


def test_auto_mode_only_when_repo_asks():
    quiet = {"CONTRIBUTING.md": "Be kind. Add tests."}
    asks = {"CONTRIBUTING.md": "Contributors must disclose AI assistance."}
    assert not policy.want_disclosure("auto", quiet)
    assert policy.want_disclosure("auto", asks)
    assert policy.want_disclosure(True, quiet)
    assert not policy.want_disclosure(False, asks)


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
    s.record_repo("c/d", "closed_unmerged")  # an outcome ossforge recorded itself still counts
    s.set_history("c/d", 0, 5)
    assert s.repo_boost("c/d") == -15


def test_only_contributor_docs_set_disclosure():
    agents = {"AGENTS.md": "Agents must disclose AI use.", "README.md": "Please mention AI assistance."}
    assert not policy.want_disclosure("auto", agents)
    assert policy.want_disclosure("auto", {"CONTRIBUTING.md": "You must disclose AI assistance in the PR."})
    assert not policy.want_disclosure("auto", {"CONTRIBUTING.md": "No need to disclose AI tools you used."})
    assert not policy.want_disclosure("auto", {"CONTRIBUTING.md": "AI is great. Disclose your test results."})
