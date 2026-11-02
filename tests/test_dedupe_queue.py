import pytest

from ossforge import dedupe, queue, safety, submit
from ossforge.config import Config
from ossforge.limiter import DailyLimiter


def test_similarity():
    a = "swallowed exception in telemetry flush"
    assert dedupe.similarity(a, "Telemetry flush swallowed exception hides errors") > 0.4
    assert dedupe.similarity(a, "add dark mode to dashboard") < 0.1


def M(state, score):
    return dedupe.Match(1, "t", "u", state, False, score, "r")


def test_is_duplicate():
    assert dedupe.is_duplicate([M("open", 0.26)])
    assert dedupe.is_duplicate([M("closed", 0.6)])
    assert not dedupe.is_duplicate([M("closed", 0.3)])
    assert not dedupe.is_duplicate([])


def test_queue_roundtrip(tmp_path):
    q = queue.Queue(tmp_path / "q.json")
    it = queue.Item("a", "o/r", "x.py", 3, "k", "d")
    assert q.add(it) and not q.add(it)
    q.set("a", status="clean")
    q.save()
    assert queue.Queue(tmp_path / "q.json").items["a"].status == "clean"


def _verified(**kw):
    base = dict(status="verified", issue_title="t", issue_body="b", pr_title="t", pr_body="b", branch="fix/x", clone="/c")
    return queue.Item("a", "o/r", "x.py", 3, "k", "d", **{**base, **kw})


def test_submit_refuses_unverified(tmp_path):
    it = queue.Item("a", "o/r", "x.py", 3, "k", "d", status="clean")
    cfg = Config(kill_file=str(tmp_path / "STOP"))
    with pytest.raises(submit.Refused, match="verified"):
        submit.preflight(it, DailyLimiter(tmp_path / "d.json"), cfg, [])


def test_submit_refuses_over_cap(tmp_path):
    lim = DailyLimiter(tmp_path / "d.json", cap=1)
    lim.record()
    cfg = Config(kill_file=str(tmp_path / "STOP"))
    with pytest.raises(submit.Refused, match="cap"):
        submit.preflight(_verified(), lim, cfg, [])


def test_submit_refuses_when_kill_switch_on(tmp_path):
    stop = tmp_path / "STOP"
    stop.write_text("x")
    with pytest.raises(submit.Refused, match="kill switch"):
        submit.preflight(_verified(), DailyLimiter(tmp_path / "d.json"), Config(kill_file=str(stop)), [])


def test_safety_blocks_protected_and_secrets():
    bad = safety.check_diff([".github/workflows/ci.yml", "a.py"], "+key = 'AKIAABCDEFGHIJKLMNOP'\n")
    assert any("protected" in b for b in bad) and any("secret" in b for b in bad)
    assert safety.check_diff(["src/a.py"], "+x = 1\n") == []


def test_repo_limits():
    cfg = Config()
    open_pr = [{"event": "pr_opened", "repo": "o/r", "state": "open"}]
    assert "already open" in safety.repo_allowed(cfg, "o/r", open_pr)
    closed = [{"event": "pr_opened", "repo": "o/r", "state": "closed_unmerged", "ts": 1000}]
    assert safety.repo_allowed(cfg, "o/r", closed, now=1000 + 86400) is not None
    assert safety.repo_allowed(cfg, "o/r", closed, now=1000 + 86400 * 30) is None
    assert safety.repo_allowed(cfg, "other/x", open_pr) is None


def test_effective_history_folds_state():
    recs = [{"event": "pr_opened", "repo": "o/r", "pr": 5, "state": "open"},
            {"event": "pr_state", "repo": "o/r", "pr": 5, "state": "merged"}]
    assert safety.effective_history(recs)[0]["state"] == "merged"


def test_snippet_marks_the_finding_line(tmp_path):
    from ossforge import hunt
    (tmp_path / "m.py").write_text("\n".join(f"line{i}" for i in range(1, 21)))
    out = hunt.snippet(tmp_path, "m.py", 10, radius=2)
    assert out.splitlines()[2].startswith("   10>") and "line8" in out and "line12" in out and "line13" not in out
    assert hunt.snippet(tmp_path, "missing.py", 3) == ""


def test_publication_duplicate_search_cannot_treat_unavailable_as_empty(monkeypatch):
    from ossforge import gh
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **k: (_ for _ in ()).throw(gh.GhError('unavailable')))
    with pytest.raises(dedupe.Incomplete):
        dedupe.find_matches('o/r', 'parser regression', 'reproduction', 'x.py', [], strict=True)


def test_publication_commits_cannot_treat_unavailable_as_empty(monkeypatch):
    from ossforge import gh
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (_ for _ in ()).throw(gh.GhError('unavailable')))
    with pytest.raises(dedupe.Incomplete):
        dedupe.recent_commit_hits('o/r', 'x.py', ['parser'], strict=True)


def test_strict_search_requires_fresh_complete_results(monkeypatch):
    from ossforge import gh
    calls = []
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (calls.append(k) or {'items': [], 'total_count': 1, 'incomplete_results': False}))
    with pytest.raises(dedupe.Incomplete):
        dedupe.find_matches('o/r', 'parser crash', '', 'x.py', [], strict=True)
    assert calls and calls[0]['fresh'] is True


def test_strict_search_rejects_incomplete_even_when_empty(monkeypatch):
    from ossforge import gh
    monkeypatch.setattr(gh, 'api', lambda *a, **k: {'items': [], 'total_count': 0, 'incomplete_results': True})
    with pytest.raises(dedupe.Incomplete):
        dedupe.find_matches('o/r', 'parser crash', '', 'x.py', [], strict=True)
