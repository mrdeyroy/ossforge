import json

import pytest

from ossforge import driver
from ossforge.queue import Item, Queue


def result():
    return dict(schema=1, id='a', base='base', branch='fix', test_command=['python', 'test.py'],
                check_commands=[], failure_code=1, issue_title='bug', issue_body='repro',
                pr_title='fix', pr_body='tests', consent_issue=0)


def test_result_exact_schema_and_argv(tmp_path):
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(result()))
    assert driver.parse(path)['test_command'] == ['python', 'test.py']
    for bad in [dict(result(), schema=True), dict(result(), test_command='sh -c bad'),
                dict(result(), verification={'trusted': True}), dict(result(), failure_code=True),
                dict(result(), check_commands=[[]]), dict(result(), consent_issue=-1)]:
        path.write_text(json.dumps(bad))
        with pytest.raises(driver.Invalid):
            driver.parse(path)


def test_task_no_work_is_explicit(tmp_path):
    assert driver.task(Queue(tmp_path / 'queue.json'))['status'] == 'no_work'


def test_result_cannot_mark_verified_or_publish_without_tests(tmp_path, monkeypatch):
    q = Queue(tmp_path / 'q.json')
    q.add(Item('a', 'owner/repo', 'x.py', 1, 'bug', 'candidate', status='clean', clone=str(tmp_path)))
    monkeypatch.setattr(driver.submit, '_base', lambda *a: 'base')
    monkeypatch.setattr(driver.evidence, 'capture', lambda *a: {'branch': 'fix'})
    monkeypatch.setattr(driver.verify, 'verify_fix', lambda *a, **k: driver.verify.VerifyResult(log=['failed']))
    assert driver.complete(q, result())['status'] == 'verification_failed'
    assert q.items['a'].status == 'clean'
    monkeypatch.setattr(driver.verify, 'verify_fix', lambda *a, **k: pytest.fail('must not run stale task'))
    with pytest.raises(driver.Invalid, match='base changed'):
        driver.complete(q, dict(result(), base='old'))


def test_uncloned_lead_does_not_hide_ready_lower_ranked_candidate(tmp_path, monkeypatch):
    q = Queue(tmp_path / 'q.json')
    q.add(Item('uncloned', 'owner/one', '', 1, 'feature', 'lead', status='clean', rank=20))
    q.add(Item('ready', 'owner/two', 'm.py', 1, 'issue', 'lead', status='clean', rank=10, clone=str(tmp_path)))
    monkeypatch.setattr(driver.submit, '_base', lambda *a: 'base')
    monkeypatch.setattr(driver.evidence, 'capture', lambda *a: {})
    assert driver.task(q)['id'] == 'ready'
