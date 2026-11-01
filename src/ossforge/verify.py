"""Verification: a candidate is only real if a new test FAILS without the fix and PASSES with it.

Runs repo commands in a per-repo venv with a scrubbed environment (no GitHub or
cloud tokens). That is hygiene, not isolation: set ``docker: true`` style
isolation up separately for untrusted repos.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import predictor

SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "PYTHONIOENCODING")


def scrubbed_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV_KEYS}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "CI": "1", **(extra or {})})
    return env


def _run(cmd: list[str], cwd: Path, timeout: int = 600, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env or scrubbed_env())
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    return p.returncode, (p.stdout + p.stderr)[-4000:]


def venv_python(work: Path, repo: str) -> Path:
    v = work / "venvs" / repo.replace("/", "__")
    py = v / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        subprocess.run([sys.executable, "-m", "venv", str(v)], check=True, capture_output=True)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "pytest", "ruff"], capture_output=True)
    return py


def install_project(py: Path, clone: Path, extras: list[str] | None = None) -> tuple[int, str]:
    targets = extras or ["."]
    cmd = [str(py), "-m", "pip", "install", "-q"]
    for t in targets:
        cmd += ["-e", t]
    return _run(cmd, clone, timeout=900)


def changed_files(clone: Path, base: str) -> list[str]:
    _, out = _run(["git", "diff", "--name-only", f"{base}..HEAD"], clone)
    return [x for x in out.splitlines() if x.strip()]


@dataclass
class VerifyResult:
    failed_without_fix: bool = False
    passed_with_fix: bool = False
    lint_ok: bool = True
    fix_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed_without_fix and self.passed_with_fix and self.lint_ok and bool(self.fix_files) and bool(self.test_files)


def verify_fix(clone: Path, base: str, py: Path, test_args: list[str], timeout: int = 600) -> VerifyResult:
    """The branch at HEAD holds fix + test. Revert only the non-test files to base, expect failure,
    restore, expect success, then lint the touched files."""
    r = VerifyResult()
    files = changed_files(clone, base)
    r.test_files = [f for f in files if predictor.is_test_path(f)]
    r.fix_files = [f for f in files if not predictor.is_test_path(f)]
    if not r.fix_files or not r.test_files:
        r.log.append("branch must change both a source file and a test file")
        return r
    pytest = [str(py), "-m", "pytest", "-q", "-x", *test_args]

    _run(["git", "checkout", base, "--", *r.fix_files], clone)
    try:
        rc, out = _run(pytest, clone, timeout)
        r.failed_without_fix = rc not in (0, 124)
        r.log.append(f"without fix rc={rc}: {out[-300:]}")
    finally:
        _run(["git", "checkout", "HEAD", "--", *r.fix_files], clone)

    rc, out = _run(pytest, clone, timeout)
    r.passed_with_fix = rc == 0
    r.log.append(f"with fix rc={rc}: {out[-300:]}")

    pyfiles = [f for f in files if f.endswith(".py")]
    if pyfiles and shutil.which(str(py)) is not None or py.exists():
        rc, out = _run([str(py), "-m", "ruff", "check", *pyfiles], clone, 120)
        r.lint_ok = rc == 0
        r.log.append(f"ruff rc={rc}: {out[-200:]}")
    return r
