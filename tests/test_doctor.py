import sys

from ossforge import doctor, external
from ossforge.config import Config


def test_doctor_and_scanner_use_same_python_with_no_ruff_on_path(monkeypatch, tmp_path):
    calls = []
    original = doctor._out
    def out(cmd):
        calls.append(cmd)
        if cmd[0] == sys.executable:
            return original(cmd)
        return (0, 'configured')
    monkeypatch.setattr(doctor, '_out', out)
    monkeypatch.setattr(doctor.shutil, 'which', lambda tool: None)
    monkeypatch.setenv('PATH', str(tmp_path))
    result = doctor.check(Config())
    ruff = [row for row in result if row[0].startswith('ruff')]
    assert ruff and ruff[0][1], ruff
    assert [sys.executable, '-m', 'ruff', '--version'] in calls
    (tmp_path / 'sample.py').write_text('print(undefined_name)\n')
    found = external.ruff_findings(tmp_path)
    assert any(f.kind == 'ruff-F821' for f in found)


def test_doctor_does_not_pass_unrelated_path_ruff(monkeypatch):
    monkeypatch.setattr(doctor.shutil, 'which', lambda tool: '/unrelated/' + tool)
    monkeypatch.setattr(doctor, '_out', lambda cmd: (1, 'No module named ruff') if cmd[0] == sys.executable else (0, 'configured'))
    monkeypatch.setattr(doctor.identity, 'check_worktree', lambda *a: [])
    monkeypatch.setattr(doctor.identity, 'check_login', lambda *a: [])
    result = doctor.check(Config())
    assert not next(row[1] for row in result if row[0].startswith('ruff'))


def test_ruff_findings_discards_external_paths_safely(monkeypatch, tmp_path):
    import json
    import subprocess
    fake_payload = json.dumps([
        {"filename": "/external/path/other.py", "location": {"row": 1}, "code": "F821", "message": "msg"},
        {"filename": str(tmp_path / "valid.py"), "location": {"row": 5}, "code": "B006", "message": "mutable def"},
    ])
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=fake_payload, stderr="")
    monkeypatch.setattr(external.subprocess, "run", fake_run)
    found = external.ruff_findings(tmp_path)
    assert len(found) == 1
    assert found[0].path == "valid.py"
    assert found[0].kind == "ruff-B006"
