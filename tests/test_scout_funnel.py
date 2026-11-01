from ossforge import gh, radar, scout, vet
from ossforge.config import Config


def _issue(n, body="Steps: run x, expected y, got z. Reproduce with `foo`.", title="crash on empty input"):
    return {"title": title, "body": body, "repository_url": "https://api.github.com/repos/acme/lib", "number": n,
            "html_url": f"https://github.com/acme/lib/issues/{n}", "updated_at": "2099-01-01T00:00:00Z", "labels": [],
            "comments": 1}


def _cfg(tmp_path):
    return Config(kill_file=str(tmp_path / "STOP"))


def test_no_matches_is_distinct_from_filtered(monkeypatch, tmp_path):
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: [])
    assert scout.scout(_cfg(tmp_path)) == []
    assert scout.explain_funnel(scout.LAST_FUNNEL).startswith("NO MATCHES")
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: [_issue(1, title="Bounty $50 for fix")])
    assert scout.scout(_cfg(tmp_path)) == []
    msg = scout.explain_funnel(scout.LAST_FUNNEL)
    assert msg.startswith("ALL FILTERED") and "'spam': 1" in msg


def test_rate_limit_reports_partial_not_silence(monkeypatch, tmp_path):
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: [_issue(1), _issue(2)])
    monkeypatch.setattr(vet, "clear_requirements", lambda b: True)

    def boom(repo):
        raise gh.RateLimited("secondary limit (retry in ~60s)", 429, 60)

    monkeypatch.setattr(radar, "analyze", boom)
    assert scout.scout(_cfg(tmp_path)) == []
    msg = scout.explain_funnel(scout.LAST_FUNNEL)
    assert msg.startswith("STOPPED EARLY") and "rate limit" in msg
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: (_ for _ in ()).throw(gh.RateLimited("cooldown", 429, 30)))
    scout.scout(_cfg(tmp_path))
    assert scout.explain_funnel(scout.LAST_FUNNEL).startswith("STOPPED EARLY")


def test_kept_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(gh, "search_issues", lambda *a, **k: [_issue(1)])
    monkeypatch.setattr(vet, "clear_requirements", lambda b: True)
    monkeypatch.setattr(radar, "analyze", lambda r: radar.RepoScore(r, 80, "Good"))
    monkeypatch.setattr(vet, "vet_issue", lambda *a, **k: vet.Verdict("acme/lib#1", "approve"))
    out = scout.scout(_cfg(tmp_path))
    assert len(out) == 1 and scout.LAST_FUNNEL["approved"] == 1
    assert scout.explain_funnel(scout.LAST_FUNNEL).startswith("1 of 1")


def test_unknown_queue_id_is_a_clean_error(tmp_path, capsys):
    from ossforge import cli
    cfgf = tmp_path / "c.yaml"
    cfgf.write_text(f"kill_file: {tmp_path}/STOP\nstate_dir: {tmp_path}/.state\n")
    rc = cli.main(["--config", str(cfgf), "submit", "nope"])
    assert rc == 2 and "unknown queue id" in capsys.readouterr().err
