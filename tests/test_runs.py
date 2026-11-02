import json

import pytest

from ossforge.runs import Busy, Run


def test_live_progress_durable_before_callback_and_completed_archive(tmp_path):
    def emit(text):
        assert json.loads((tmp_path / 'run.json').read_text())['events'][-1]['message'] == text
    with Run(tmp_path, emit) as run:
        run.note('discovery starting')
    data = json.loads((tmp_path / 'run.json').read_text())
    assert data['status'] == 'completed'
    assert (tmp_path / 'runs' / f'{data["id"]}.json').exists()


def test_lock_prevents_duplicate_pass(tmp_path):
    with Run(tmp_path):
        with pytest.raises(Busy):
            with Run(tmp_path):
                pytest.fail('duplicate run entered')


def test_failed_run_and_interrupted_recovery(tmp_path):
    with pytest.raises(ValueError):
        with Run(tmp_path):
            raise ValueError('sensitive error not journaled')
    assert json.loads((tmp_path / 'run.json').read_text())['status'] == 'failed'
    assert 'sensitive' not in (tmp_path / 'run.json').read_text()
    (tmp_path / 'run.json').write_text(json.dumps({'id': 'prior', 'status': 'running'}))
    with Run(tmp_path):
        pass
    assert json.loads((tmp_path / 'runs' / 'prior.json').read_text())['status'] == 'interrupted'


def test_corrupt_old_snapshot_cannot_escape_archive(tmp_path):
    (tmp_path / 'run.json').write_text(json.dumps({'id': '../../escape', 'status': 'running'}))
    with Run(tmp_path):
        pass
    assert len(list((tmp_path / 'runs').glob('*.json'))) == 2
    assert not (tmp_path.parent / 'escape.json').exists()
