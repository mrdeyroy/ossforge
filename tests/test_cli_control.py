import pytest

from ossforge import cli


def test_stop_and_resume_ignore_corrupt_unrelated_queue(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    queue = state / 'queue.json'
    queue.write_text('{partial')
    stop = tmp_path / 'control' / 'STOP'
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(f'state_dir: {state}\nkill_file: {stop}\n')
    assert cli.main(['--config', str(cfg), 'stop']) == 0
    assert stop.read_text() == 'stopped\n'
    assert queue.read_text() == '{partial'
    assert cli.main(['--config', str(cfg), 'resume']) == 0
    assert not stop.exists() and queue.read_text() == '{partial'


@pytest.mark.parametrize('args', [
    ['agent-verify', 'result.json'], ['verify', 'missing', '--branch', 'fix', '--issue-title', 'bug',
     '--issue-body-file', 'issue.txt', '--pr-title', 'fix', '--pr-body-file', 'pr.txt'],
    ['prepare', 'missing'], ['commit', 'missing', '-m', 'fix'], ['hunt', 'org/repo'],
    ['hold', 'missing', '--reason', 'hold'], ['unhold', 'missing'], ['reject', 'missing'],
    ['research-repo', '--defer', 'hold'], ['research-session', '--seconds', '60'],
    ['policy-review', 'org/repo', '--accept', '--note', 'reviewed'],
    ['review-qualification', 'org/repo', '1', '--defer', 'hold'],
    ['submit', 'missing', '--yes'], ['loop', '--once'], ['discover'], ['bootstrap'], ['digest']])
def test_direct_mutating_commands_stop_before_state_or_execution(tmp_path, monkeypatch, capsys, args):
    state = tmp_path / 'state'
    state.mkdir()
    queue = state / 'queue.json'
    queue.write_text('{corrupt preserved')
    stop = tmp_path / 'STOP'
    stop.touch()
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(f'state_dir: {state}\nkill_file: {stop}\n')
    monkeypatch.setattr(cli, '_ctx', lambda *a: pytest.fail('STOP must precede state reads/execution'))
    assert cli.main(['--config', str(cfg), *args]) == 1
    assert 'REFUSED:' in capsys.readouterr().err
    assert queue.read_text() == '{corrupt preserved' and stop.exists()


def test_read_only_queue_remains_available_under_stop(tmp_path, capsys):
    state = tmp_path / 'state'
    stop = tmp_path / 'STOP'
    stop.touch()
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(f'state_dir: {state}\nkill_file: {stop}\n')
    assert cli.main(['--config', str(cfg), '--json', 'queue']) == 0
    assert capsys.readouterr().out.strip() == '[]'
    assert stop.exists()
