from ossforge import bench, config, contributing, external, loop, outcomes, patrol, scout
from ossforge.audit import Finding

CONTRIB = """
We use Conventional Commits. Sign off each commit with `git commit -s` (DCO).
On your first pull request, the CLA bot asks you to sign the CLA.
Run:

    pytest packages/core
    ruff check .

Please open an issue first for larger changes.
"""


def test_contributing_parse():
    c = contributing.parse(CONTRIB)
    assert c.dco and c.cla and c.conventional_commits and c.issue_first
    assert "pytest packages/core" in c.test_commands and any("ruff" in x for x in c.lint_commands)
    assert contributing.commit_message_ok("fix: x\n\nSigned-off-by: A <a@b>", c) == []
    assert contributing.commit_message_ok("did stuff", c)


def test_requires_assignment():
    assert contributing.parse("You must be assigned before opening a PR.").requires_assignment


def test_spam_filter():
    kw = config.Config().spam_keywords
    assert scout.is_spam("[BOUNTY] fix thing (Pool: 500 RTC)", "", kw)
    assert scout.is_spam("Fix parser", "pays $200 on merge", kw)
    assert not scout.is_spam("Fix off-by-one in parser", "Steps to reproduce...", kw)


def test_precision_learns(tmp_path):
    s = outcomes.Stats(tmp_path / "s.json")
    before = s.precision("eq-none")
    for _ in range(5):
        s.record_kind("eq-none", True)
    assert s.precision("eq-none") > before
    for _ in range(20):
        s.record_kind("pop0-in-loop", False)
    assert s.precision("pop0-in-loop") < 0.05


def test_rank_prefers_src_and_bugs(tmp_path):
    s = outcomes.Stats(tmp_path / "s.json")
    a = Finding("src/core/x.py", 1, "mutable-default", "d", "bug")
    b = Finding("scripts/x.py", 1, "mutable-default", "d", "perf")
    assert outcomes.rank([b, a], s)[0][1] is a


def test_repo_boost(tmp_path):
    s = outcomes.Stats(tmp_path / "s.json")
    s.record_repo("o/r", "merged")
    s.record_repo("x/y", "closed_unmerged")
    assert s.repo_boost("o/r") > 0 and s.repo_boost("x/y") == 0 and s.repo_boost("new/z") == 0  # closures never penalise


def _pr(**kw):
    base = {"number": 7, "state": "open", "merged": False, "mergeable_state": "clean",
            "base": {"repo": {"full_name": "o/r"}}}
    return {**base, **kw}


def U(login, typ="User"):
    return {"login": login, "type": typ}


def test_patrol_classify():
    me = "me"
    assert patrol.classify(_pr(merged=True, state="closed"), [], [], [], me)[0].kind == "merged"
    assert patrol.classify(_pr(state="closed"), [], [], [], me)[0].kind == "closed"
    checks = [{"name": "DCO", "conclusion": "failure"}, {"name": "build", "conclusion": "failure"}]
    kinds = {a.kind for a in patrol.classify(_pr(mergeable_state="dirty"), checks, [{"state": "CHANGES_REQUESTED"}], [], me)}
    assert {"dco", "ci", "conflict", "changes_requested"} <= kinds
    comments = [{"user": U("maint"), "body": "please add a test", "html_url": "u"}]
    assert any(a.kind == "feedback" for a in patrol.classify(_pr(), [], [], comments, me))
    assert patrol.classify(_pr(), [], [], [], me)[0].kind == "idle"


def test_js_detectors(tmp_path):
    (tmp_path / "a.js").write_text("xs.forEach(async (x) => { await f(x) });\ntry { g() } catch (e) {}\n")
    kinds = {f.kind for f in external.js_findings(tmp_path)}
    assert kinds == {"async-foreach", "empty-catch"}


def test_bench_rejects_wrong_results_and_measures():
    data = list(range(2000))
    r = bench.compare(lambda: 1999 in data, lambda: 1999 in set(data) or True)
    assert r["speedup"] > 0
    try:
        bench.compare(lambda: 1, lambda: 2)
    except ValueError:
        pass
    else:
        raise AssertionError("must reject differing results")


def test_loop_halts_on_kill_switch(tmp_path):
    stop = tmp_path / "STOP"
    stop.write_text("x")
    assert loop.run_once(config.Config(kill_file=str(stop), state_dir=str(tmp_path)))[0].startswith("halted")


def test_config_defaults_and_cap(tmp_path):
    assert config.load(tmp_path / "none.yaml").cap == 2
    p = tmp_path / "c.yaml"
    p.write_text("daily_cap: 9\nunknown: 1\nmin_stars: 100\n")
    c = config.load(p)
    assert c.cap == 2 and c.min_stars == 100


def test_loop_survives_rate_limit(tmp_path, monkeypatch):
    from ossforge import gh

    def boom(*a, **k):
        raise gh.RateLimited("secondary rate limit", 403)

    monkeypatch.setattr(loop, "_pass", boom)
    cfg = config.Config(state_dir=str(tmp_path), kill_file=str(tmp_path / "STOP"))
    notes = loop.run_once(cfg)
    assert "rate limit" in notes[-1] and (tmp_path / "digest.md").exists()
