import pytest

from ossforge import cli, gh, issue_reviews, scout
from ossforge.config import Config


def test_review_is_snapshot_scoped_and_reversible(tmp_path):
    path = tmp_path / "reviews.json"
    issue_reviews.record(path, "Acme/Lib", 1, "yesterday", "not reproducible")
    data = issue_reviews.load(path)
    assert issue_reviews.unchanged_reason(data, "acme/lib", 1, "yesterday") == "not reproducible"
    assert not issue_reviews.unchanged_reason(data, "acme/lib", 1, "today")
    assert not issue_reviews.unchanged_reason(data, "acme/lib", 1, None)
    assert not issue_reviews.unchanged_reason(data, "acme/other", 1, "yesterday")
    issue_reviews.reconsider(path, "acme/lib", 1)
    assert not issue_reviews.load(path)
    with pytest.raises(ValueError):
        issue_reviews.record(path, "acme/lib", 1, "yesterday", "  ")


def test_scout_skips_only_unchanged_issue_before_remote_vetting(monkeypatch, tmp_path):
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path / "STOP"))
    issue = {"title": "crash", "body": "Steps: reproduce expected failure " * 5,
             "repository_url": "https://api.github.com/repos/acme/lib", "number": 1,
             "updated_at": "yesterday"}
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: [issue])
    calls = []
    monkeypatch.setattr(gh, "api", lambda path, **k: calls.append(path) or {"stargazers_count": 1})
    issue_reviews.record(cfg.path("issue_reviews.json"), "acme/lib", 1, "yesterday", "scope too broad")
    assert scout.scout(cfg) == []
    assert not calls  # reviewed issues must not spend remote vetting calls
    assert scout.LAST_FUNNEL["reviewed_unchanged"] == 1
    assert "reviewed_unchanged" in scout.explain_funnel(scout.LAST_FUNNEL)
    issue["updated_at"] = "today"
    assert scout.scout(cfg) == []
    assert scout.LAST_FUNNEL["reviewed_unchanged"] == 0 and len(calls) == 1
    issue_reviews.reconsider(cfg.path("issue_reviews.json"), "acme/lib", 1)
    issue["updated_at"] = "yesterday"
    scout.scout(cfg)
    assert len(calls) == 2


def test_cli_review_persists_for_shared_state_not_other_configs(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(f"state_dir: {tmp_path}/shared\n")
    monkeypatch.setattr(gh, "api", lambda *a, **k: {"updated_at": "today"})
    assert cli.main(["--config", str(cfg), "review-issue", "o/r", "1", "--reason", "too broad"]) == 0
    path = tmp_path / "shared" / "issue_reviews.json"
    assert issue_reviews.unchanged_reason(issue_reviews.load(path), "o/r", 1, "today") == "too broad"
    assert not issue_reviews.load(tmp_path / "other" / "issue_reviews.json")
    assert cli.main(["--config", str(cfg), "reconsider-issue", "o/r", "1"]) == 0
    assert not issue_reviews.load(path)


def test_cli_does_not_record_pr_or_empty_reason(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(f"state_dir: {tmp_path}/state\n")
    monkeypatch.setattr(gh, "api", lambda *a, **k: {"updated_at": "today", "pull_request": {}})
    assert cli.main(["--config", str(cfg), "review-issue", "o/r", "1", "--reason", "reason"]) == 2
    monkeypatch.setattr(gh, "api", lambda *a, **k: {"updated_at": "today"})
    assert cli.main(["--config", str(cfg), "review-issue", "o/r", "1", "--reason", "  "]) == 2
    assert not (tmp_path / "state" / "issue_reviews.json").exists()
