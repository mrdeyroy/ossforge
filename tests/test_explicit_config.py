from ossforge import cli


def test_explicit_missing_config_refuses_before_default_state_or_network(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, '_ctx', lambda *a: (_ for _ in ()).throw(AssertionError('wrong default workflow state opened')))
    assert cli.main(['--config', str(tmp_path/'typo.yaml'), 'agent-next']) == 2
    assert 'config' in capsys.readouterr().err.lower()
    assert not (tmp_path/'.state').exists()


def test_no_explicit_config_keeps_fresh_clone_defaults(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(['agent-next']) == 0
    assert 'no_work' in capsys.readouterr().out


def test_explicit_directory_and_equals_form_refuse_without_stop_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for args in [['--config', str(tmp_path), 'stop'], ['--config=absent.yaml', 'resume']]:
        assert cli.main(args) == 2
    assert not (tmp_path/'.state').exists()


def test_explicit_valid_config_keeps_selected_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = tmp_path/'selected.yaml'
    config.write_text(f'state_dir: {tmp_path}/selected\nkill_file: {tmp_path}/selected/STOP\n')
    assert cli.main(['--config', str(config), 'agent-next']) == 0
    assert str(config) in capsys.readouterr().out
    assert not (tmp_path/'.state').exists()


def test_missing_explicit_config_never_removes_default_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = tmp_path/'.state'
    state.mkdir()
    stop = state/'STOP'
    stop.write_text('preserve owner stop\n')
    assert cli.main(['--config', 'missing.yaml', 'resume']) == 2
    assert stop.read_text() == 'preserve owner stop\n'


def test_omitted_config_uses_existing_default_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'ossforge.yaml').write_text(f'state_dir: {tmp_path}/custom\nkill_file: {tmp_path}/custom/STOP\n')
    assert cli.main(['stop']) == 0
    assert (tmp_path/'custom/STOP').exists()
    assert not (tmp_path/'.state').exists()
