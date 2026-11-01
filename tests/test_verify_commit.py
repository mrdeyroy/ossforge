import subprocess
from pathlib import Path

from ossforge import identity, verify
from ossforge.config import Config


def sh(cwd, *c):
    return subprocess.run(c, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path, monkeypatch):
    g = tmp_path / "gc"
    g.write_text("[user]\n name = Default\n email = d@example.invalid\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(g))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    (r / "m.py").write_text("def f():\n    return 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    return r


def test_verify_reverts_files_the_fix_added(tmp_path, monkeypatch):
    """A fix that adds a new source file must still be reverted for the 'without fix' run."""
    r = _repo(tmp_path, monkeypatch)
    base = sh(r, "git", "rev-parse", "HEAD")
    sh(r, "git", "checkout", "-qb", "fix")
    (r / "m.py").write_text("from helper import val\n\ndef f():\n    return val\n")
    (r / "helper.py").write_text("val = 2\n")
    (r / "test_m.py").write_text("from m import f\n\ndef test_f():\n    assert f() == 2\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "fix")
    import sys
    res = verify.verify_fix(r, base, Path(sys.executable), ["test_m.py"])
    assert res.failed_without_fix and res.passed_with_fix
    assert (r / "helper.py").read_text() == "val = 2\n"  # restored


def test_verify_reports_when_revert_is_impossible(tmp_path, monkeypatch):
    r = _repo(tmp_path, monkeypatch)
    res = verify.verify_fix(r, "deadbeef", Path("python3"), ["x"])
    assert not res.ok


def test_commit_gate_and_artifacts_not_staged(tmp_path, monkeypatch):
    r = _repo(tmp_path, monkeypatch)
    cfg = Config(github_user="me", git_name="Owner", git_email="o@example.invalid")
    monkeypatch.setattr(identity, "check_login", lambda c: [])
    (r / "m.py").write_text("def f():\n    return 2\n")
    (r / "pkg.egg-info").mkdir()
    (r / "pkg.egg-info" / "PKG-INFO").write_text("x")
    try:
        identity.commit(cfg, str(r), "fix: f")
        raise AssertionError("default identity must be refused")
    except identity.IdentityError as e:
        assert "effective git author" in str(e)
    assert sh(r, "git", "log", "--oneline").count("\n") == 0  # nothing committed
    assert not identity.apply_local(cfg, str(r))
    identity.commit(cfg, str(r), "fix: f")
    assert sh(r, "git", "log", "-1", "--format=%an|%ae|%cn|%ce") == "Owner|o@example.invalid|Owner|o@example.invalid"
    assert "egg-info" not in sh(r, "git", "show", "--stat", "--format=", "HEAD")
