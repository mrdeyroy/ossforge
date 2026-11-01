"""Write orchestration against local stand-ins only: bare git repos for upstream and fork, a fake `gh` that logs
calls and answers from fixtures. Nothing here reaches GitHub, and no CLA path exists to trigger."""
import json
import os
import stat
import subprocess
import textwrap

import pytest

from ossforge import gh, queue, safety, submit
from ossforge.config import Config
from ossforge.limiter import DailyLimiter

GH_SHIM = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    a = sys.argv[1:]
    open(os.environ["FAKE_GH_LOG"], "a").write(json.dumps(a) + "\\n")
    def reply(code, body):
        print(f"HTTP/2.0 {code} X\\n\\n" + json.dumps(body))
        sys.exit(0 if code < 400 else 1)
    if a[:1] == ["api"]:
        path = [x for x in a if "/" in x or x == "user"][-1] if len(a) > 4 else "user"
        path = a[a.index("GET") + 1]
        if path == "user":
            reply(200, {"login": os.environ["FAKE_GH_LOGIN"]})
        if path == "search/issues":
            reply(200, {"total_count": 0, "items": []})
        if path.endswith("/commits"):
            reply(200, [])
        reply(404, {"message": "Not Found"})
    if a[:2] == ["issue", "create"]:
        print("https://github.com/acme/lib/issues/11"); sys.exit(0)
    if a[:2] == ["pr", "create"]:
        print("https://github.com/acme/lib/pull/12"); sys.exit(0)
    if a[:2] == ["repo", "fork"]:
        sys.exit(0)
    sys.exit(0)
''')

ME = ("Parijat Test", "owner@example.invalid")


def sh(*cmd, cwd=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "gh"
    shim.write_text(GH_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    up, fork = tmp_path / "up.git", tmp_path / "fork.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(up))
    sh("git", "init", "-q", "--bare", "-b", "main", str(fork))
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text(f"[user]\n name = {ME[0]}\n email = {ME[1]}\n"
                    f'[url "{up}"]\n insteadOf = https://github.com/acme/lib.git\n'
                    f'[url "{fork}"]\n insteadOf = https://github.com/me/lib.git\n')
    for k, v in {"PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log), "FAKE_GH_LOGIN": "me",
                 "GIT_CONFIG_GLOBAL": str(gcfg), "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    seed = tmp_path / "seed"
    sh("git", "clone", "-q", str(up), str(seed))
    (seed / "a.py").write_text("x = 1\n")
    sh("git", "add", "-A", cwd=seed)
    sh("git", "commit", "-qm", "init", cwd=seed)
    sh("git", "push", "-q", "origin", "HEAD:main", cwd=seed)
    clone = tmp_path / "clone"
    sh("git", "clone", "-q", str(up), str(clone))
    sh("git", "remote", "set-url", "origin", "https://github.com/acme/lib.git", cwd=clone)
    sh("git", "checkout", "-qb", "fix/x", cwd=clone)
    (clone / "a.py").write_text("x = 2\n")
    (clone / "test_a.py").write_text("def test_a():\n    assert True\n")
    sh("git", "add", "-A", cwd=clone)
    sh("git", "commit", "-qm", "fix: x", cwd=clone)
    monkeypatch.setattr(gh, "WRITE_GAP_S", 0.0)
    monkeypatch.setattr(gh, "PACING_S", 0.0)
    monkeypatch.setattr(gh, "SEARCH_PER_MIN", 10_000)
    gh._MEM_GATES.clear()
    gh.configure(None)
    cfg = Config(kill_file=str(tmp_path / "STOP"), state_dir=str(tmp_path / ".state"), github_user="me",
                 git_name=ME[0], git_email=ME[1])
    it = queue.Item("a", "acme/lib", "a.py", 1, "k", "d", status="verified", issue_title="t", issue_body="b",
                    pr_title="fix: x", pr_body="b", branch="fix/x", clone=str(clone))
    return dict(cfg=cfg, it=it, clone=clone, log=log, up=up, fork=fork, tmp=tmp_path, mp=monkeypatch,
                lim=DailyLimiter(tmp_path / "d.json", 2), audit=safety.Audit(tmp_path / "audit.jsonl"))


def writes(log):
    return [json.loads(x) for x in log.read_text().splitlines() if x and json.loads(x)[0] != "api"] if log.exists() else []


def run(w, execute=False):
    return submit.submit(w["it"], w["lim"], w["cfg"], w["audit"], execute=execute)


def test_dry_run_sends_nothing(world):
    r = run(world)
    assert r["dry_run"] and writes(world["log"]) == []


def test_happy_path_publishes_to_own_fork_with_correct_authorship(world):
    r = run(world, execute=True)
    assert r["pr"].endswith("/pull/12")
    w = writes(world["log"])
    assert [x[:2] for x in w] == [["issue", "create"], ["repo", "fork"], ["pr", "create"]]
    assert "me:fix/x" in w[2] and "acme/lib" in w[2]  # PR head is the operator's fork, target is upstream
    pushed = sh("git", "log", "--format=%an|%ae|%cn|%ce|%B", "-1", "fix/x", cwd=world["fork"])
    assert pushed.startswith(f"{ME[0]}|{ME[1]}|{ME[0]}|{ME[1]}")
    assert "Signed-off-by" not in pushed
    assert "fix/x" not in sh("git", "branch", cwd=world["up"])  # nothing was pushed to upstream


def test_wrong_gh_account_stops_before_any_write(world):
    world["mp"].setenv("FAKE_GH_LOGIN", "someone-else")
    with pytest.raises(submit.Refused, match="logged in as 'someone-else'"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_wrong_author_stops(world):
    sh("git", "-c", "user.email=other@example.invalid", "commit", "--amend", "--reset-author", "--no-edit", cwd=world["clone"])
    with pytest.raises(submit.Refused, match="author is"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_wrong_committer_stops(world):
    env = {**os.environ, "GIT_COMMITTER_EMAIL": "bot@example.invalid", "GIT_COMMITTER_NAME": "Bot"}
    sh("git", "commit", "--amend", "--no-edit", "-q", cwd=world["clone"], env=env)
    with pytest.raises(submit.Refused, match="committer is"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_env_override_of_identity_is_caught_for_new_commits(world):
    world["mp"].setenv("GIT_COMMITTER_EMAIL", "bot@example.invalid")
    with pytest.raises(submit.Refused, match="effective git committer"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_missing_identity_config_stops(world):
    world["cfg"].git_email = ""
    with pytest.raises(submit.Refused, match="git_email is not set"):
        run(world, execute=True)
    world["cfg"].git_email, world["cfg"].github_user = ME[1], ""
    with pytest.raises(submit.Refused, match="github_user is not set"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_wrong_upstream_clone_stops(world):
    sh("git", "remote", "set-url", "origin", "https://github.com/other/lib.git", cwd=world["clone"])
    with pytest.raises(submit.Refused, match="clone origin is other/lib"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_fork_destination_must_be_own_fork(world):
    # Preflight passes; at push time the fork remote the tool sets must be me/lib. Pre-set a hostile remote
    # name is overwritten, so verify the guard directly on a mismatching remote.
    from ossforge import identity
    sh("git", "remote", "add", "fork", "https://github.com/acme/lib.git", cwd=world["clone"])
    assert identity.check_fork(world["cfg"], str(world["clone"]), "acme/lib")
    sh("git", "remote", "set-url", "fork", "https://github.com/stranger/lib.git", cwd=world["clone"])
    assert "expected me/lib" in identity.check_fork(world["cfg"], str(world["clone"]), "acme/lib")[0]


def test_unverified_item_never_publishes(world):
    world["it"].status = "clean"
    with pytest.raises(submit.Refused, match="must be 'verified'"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_signoff_needs_explicit_per_repo_approval(world):
    sh("git", "commit", "--amend", "-q", "-s", "--no-edit", cwd=world["clone"])
    with pytest.raises(submit.Refused, match="Signed-off-by but sign-off is not approved"):
        run(world, execute=True)
    world["cfg"].signoff_repos = ["acme/lib"]
    assert run(world)["dry_run"]


def test_signoff_added_only_where_approved_and_under_verified_identity(world):
    world["cfg"].signoff_repos = ["acme/lib"]
    run(world, execute=True)
    tip = sh("git", "log", "-1", "--format=%an|%ae|%cn|%ce|%B", "fix/x", cwd=world["fork"])
    assert tip.startswith(f"{ME[0]}|{ME[1]}|{ME[0]}|{ME[1]}") and f"Signed-off-by: {ME[0]} <{ME[1]}>" in tip


def test_repo_that_asks_for_dco_is_refused_until_approved(world, monkeypatch):
    from ossforge import vet
    monkeypatch.setattr(vet, "policy_texts", lambda repo: {"CONTRIBUTING.md": "All commits need a Signed-off-by (DCO)."})
    with pytest.raises(submit.Refused, match="asks for a DCO"):
        run(world, execute=True)
    assert writes(world["log"]) == []


def test_repo_with_ai_policy_doc_stops_until_owner_reviews(world, monkeypatch):
    from ossforge import vet
    monkeypatch.setattr(vet, "policy_texts", lambda repo: {".github/AI_POLICY.md": "# Generative AI / LLM Policy\nBe responsible."})
    with pytest.raises(submit.Refused, match="has an AI/LLM policy"):
        run(world, execute=True)
    assert writes(world["log"]) == []
    world["cfg"].ai_policy_reviewed = ["acme/lib"]
    assert run(world)["dry_run"]
