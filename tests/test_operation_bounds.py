import math
import subprocess

import pytest

from ossforge import cli, gh, hunt, loop
from ossforge.config import Config


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '-inf', '0.000001'])
def test_cli_rejects_unusable_loop_interval(value):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(['loop', f'--interval-hours={value}'])


def test_cli_accepts_positive_loop_interval():
    assert cli.build_parser().parse_args(['loop', '--interval-hours', '0.5']).interval_hours == 0.5


@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf])
def test_library_rejects_interval_before_work(monkeypatch, value):
    monkeypatch.setattr(loop, 'run_once', lambda cfg: pytest.fail('must not run a pass'))
    with pytest.raises(ValueError, match='interval'):
        loop.run_forever(Config(), value)


def test_gh_read_timeout_has_bounded_error(monkeypatch):
    calls = []

    def stalled(cmd, **kw):
        calls.append(kw)
        assert 0 < kw['timeout'] <= 120
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])

    gh.configure(None)
    monkeypatch.setattr(gh, '_budget', lambda path: None)
    monkeypatch.setattr(gh, 'subprocess', type('Process', (), {'run': staticmethod(stalled), 'TimeoutExpired': subprocess.TimeoutExpired}))
    with pytest.raises(gh.GhError, match='timed out'):
        gh.api('repos/example/project')
    assert len(calls) == 1


def test_clone_timeout_does_not_apply_identity(tmp_path, monkeypatch):
    def stalled(cmd, **kw):
        assert 0 < kw['timeout'] <= 300
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])

    monkeypatch.setattr(hunt, 'subprocess', type('Process', (), {'run': staticmethod(stalled), 'TimeoutExpired': subprocess.TimeoutExpired}))
    monkeypatch.setattr(hunt.identity, 'apply_local', lambda *a: pytest.fail('clone did not finish'))
    with pytest.raises(RuntimeError, match='clone timed out'):
        hunt.clone(Config(work_dir=str(tmp_path)), 'example/project')


def test_clone_timeout_removes_only_new_partial_checkout(tmp_path, monkeypatch):
    dest = tmp_path / 'example__project'

    def stalled(cmd, **kw):
        dest.mkdir()
        (dest / 'partial').write_text('incomplete')
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])

    monkeypatch.setattr(hunt.subprocess, 'run', stalled)
    with pytest.raises(RuntimeError, match='clone timed out'):
        hunt.clone(Config(work_dir=str(tmp_path)), 'example/project')
    assert not dest.exists()


def test_existing_clone_is_never_deleted_or_recloned(tmp_path, monkeypatch):
    dest = tmp_path / 'example__project'
    dest.mkdir()
    (dest / 'work').write_text('keep')
    (dest / '.git').mkdir()
    (dest / '.git' / 'index').write_bytes(b'controlled index placeholder')
    def probe(cmd, **kw):
        assert cmd[:2] != ['git', 'clone']
        out = str(dest) + '\n' if '--show-toplevel' in cmd else '.git/index\n' if '--git-path' in cmd else ''
        return subprocess.CompletedProcess(cmd, 0, out, '')
    monkeypatch.setattr(hunt.subprocess, 'run', probe)
    monkeypatch.setattr(hunt.identity, 'check_upstream', lambda *a: [])
    assert hunt.clone(Config(work_dir=str(tmp_path)), 'example/project') == dest
    assert (dest / 'work').read_text() == 'keep'


@pytest.mark.parametrize('wrong_remote', [False, True])
def test_unrelated_existing_directory_refused_and_preserved(tmp_path, wrong_remote):
    dest = tmp_path / 'example__project'
    dest.mkdir()
    (dest / 'work').write_text('keep existing bytes')
    if wrong_remote:
        subprocess.run(['git', 'init', '-q'], cwd=dest, check=True)
        subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/other/repo.git'], cwd=dest, check=True)
    with pytest.raises(RuntimeError, match='checkout|origin'):
        hunt.clone(Config(work_dir=str(tmp_path)), 'example/project')
    assert (dest / 'work').read_text() == 'keep existing bytes'


def test_existing_correct_root_incomplete_work_refused_without_rewriting(tmp_path):
    dest = tmp_path / 'example__project'
    dest.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=dest, check=True)
    subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/example/project.git'], cwd=dest, check=True)
    (dest / 'work').write_text('uncommitted existing work')
    with pytest.raises(RuntimeError, match='index|incomplete'):
        hunt.clone(Config(work_dir=str(tmp_path)), 'example/project')
    assert (dest / 'work').read_text() == 'uncommitted existing work'


def test_nested_directory_cannot_impersonate_parent_checkout(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/example/project.git'], cwd=tmp_path, check=True)
    dest = tmp_path / 'example__project'
    dest.mkdir()
    with pytest.raises(RuntimeError, match='Git root'):
        hunt.clone(Config(work_dir=str(tmp_path)), 'example/project')
    assert dest.is_dir()
