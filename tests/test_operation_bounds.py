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
    monkeypatch.setattr(hunt.subprocess, 'run', lambda *a, **kw: pytest.fail('existing clone must not run'))
    assert hunt.clone(Config(work_dir=str(tmp_path)), 'example/project') == dest
    assert (dest / 'work').read_text() == 'keep'
