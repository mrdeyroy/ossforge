import base64

import pytest

from ossforge import admission, gh


def test_strict_manifest_parsing():
    good = dict(version=1, enabled=True, allowed_dirs=['src', 'tests/'])
    assert admission.parse(good)['allowed_dirs'] == ['src', 'tests']
    for bad in [{}, {**good, 'enabled': False}, {**good, 'version': True}, {**good, 'max_lines': True},
                {**good, 'max_files': 0}, {**good, 'allowed_dirs': ['../src']},
                {**good, 'allowed_dirs': ['src/**']}, {**good, 'unknown': 'typo'}]:
        with pytest.raises(admission.Denied):
            admission.parse(bad)


def test_live_consent_revocation_and_no_label_bypass(monkeypatch):
    calls = []
    content = ['version: 1\nenabled: true\nallowed_dirs: [src, tests]\n']
    def api(path, **kw):
        assert kw['fresh'] is True
        calls.append(path)
        return dict(encoding='base64', content=base64.b64encode(content[0].encode()).decode())
    monkeypatch.setattr(gh, 'api', api)
    assert admission.check('o/r', 5, ['src/a.py'], '1\t1\tsrc/a.py')['draft_only']
    content[0] = 'version: 1\nenabled: false\nallowed_dirs: [src]\n'
    with pytest.raises(admission.Denied):
        admission.inspect('o/r', 5)
    assert all('contents/' in p for p in calls)


def test_issue_label_and_read_errors(monkeypatch):
    issue = dict(state='open', labels=[{'name': admission.LABEL}])
    def api(path, **kw):
        if '/contents/' in path:
            raise gh.GhError('missing', 404)
        return issue
    monkeypatch.setattr(gh, 'api', api)
    assert admission.inspect('o/r', 3)['source'].startswith('issue#3')
    for key, value in [('state', 'closed'), ('labels', []), ('pull_request', {})]:
        old = issue.copy()
        issue[key] = value
        with pytest.raises(admission.Denied):
            admission.inspect('o/r', 3)
        issue.clear()
        issue.update(old)
    monkeypatch.setattr(gh, 'api', lambda *a, **k: (_ for _ in ()).throw(gh.GhError('forbidden', 403)))
    with pytest.raises(admission.Denied, match='cannot verify'):
        admission.inspect('o/r', 3)


def test_scope_and_size_fail_closed(monkeypatch):
    monkeypatch.setattr(admission, 'inspect', lambda *a: dict(max_files=2, max_lines=5, allowed_dirs=['src']))
    for paths, stat in [(['else/a'], '1\t0\telse/a'), (['src/../a'], '1\t0\tsrc/../a'),
                        (['src/a'], '-\t-\tsrc/a'), (['src/a'], '3\t3\tsrc/a'),
                        (['src/a'], ''), (['src/a'], '1\t1\tsrc/other')]:
        with pytest.raises(admission.Denied):
            admission.check('o/r', 0, paths, stat)


def test_duplicate_manifest_keys_rejected(monkeypatch):
    raw = 'version: 1\nenabled: false\nenabled: true\nallowed_dirs: [src]\n'
    monkeypatch.setattr(gh, 'api', lambda *a, **k: dict(encoding='base64', content=base64.b64encode(raw.encode()).decode()))
    with pytest.raises(admission.Denied, match='duplicate'):
        admission.inspect('o/r')


def test_cli_read_only_denial(monkeypatch, tmp_path, capsys):
    from ossforge import cli
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(f'state_dir: {tmp_path}/state\n')
    monkeypatch.setattr(admission, 'inspect', lambda *a: (_ for _ in ()).throw(admission.Denied('missing consent')))
    assert cli.main(['--config', str(cfg), '--json', 'consent-check', 'o/r']) == 1
    assert 'missing consent' in capsys.readouterr().out
