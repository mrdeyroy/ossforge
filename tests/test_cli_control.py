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
