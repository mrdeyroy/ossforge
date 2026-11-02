import subprocess

import pytest

from ossforge import hunt
from ossforge.config import Config


def test_existing_checkout_without_index_is_preserved_and_refused(tmp_path, monkeypatch):
    cfg = Config(work_dir=str(tmp_path / 'work'))
    root = tmp_path / 'work' / 'org__lib'
    root.mkdir(parents=True)
    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=root, text=True).strip()
    git('init', '-qb', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (root / 'source.py').write_text('value = 1\n')
    git('add', '.')
    git('commit', '-qm', 'seed')
    git('remote', 'add', 'origin', 'https://github.com/org/lib')
    (root / '.git' / 'index').unlink()
    monkeypatch.setattr(hunt.identity, 'check_upstream', lambda *a: [])
    before = (root / 'source.py').read_bytes()
    with pytest.raises(RuntimeError, match='checkout|index|incomplete'):
        hunt.clone(cfg, 'org/lib')
    assert not (root / '.git' / 'index').exists()
    assert (root / 'source.py').read_bytes() == before


def test_unexamined_count_uses_current_position_not_kept_count(tmp_path, monkeypatch):
    from ossforge import gh, radar, scout
    cfg = Config(state_dir=str(tmp_path / 'state'))
    def item(n, title='Parser crash'):
        return {'number': n, 'title': title, 'body': 'Steps to reproduce expected traceback error. ' * 4,
                'repository_url': 'https://api.github.com/repos/org/lib', 'html_url': f'https://example.invalid/{n}'}
    monkeypatch.setattr(gh, 'search_issues', lambda *a, **k: [item(1, 'Bounty $50'), item(2), item(3)])
    monkeypatch.setattr(gh, 'api', lambda *a, **k: {'stargazers_count': 1000})
    monkeypatch.setattr(radar, 'analyze', lambda *a: (_ for _ in ()).throw(gh.ReadBudgetExceeded('deadline')))
    scout.scout(cfg)
    assert '2 issues not examined' in scout.LAST_FUNNEL['stopped']


def test_complete_clean_checkout_reused_but_dirty_content_preserved(tmp_path, monkeypatch):
    cfg = Config(work_dir=str(tmp_path))
    root = tmp_path / 'org__lib'
    root.mkdir()
    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=root, text=True).strip()
    git('init', '-qb', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (root / 'source.py').write_text('value = 1\n')
    git('add', '.')
    git('commit', '-qm', 'seed')
    monkeypatch.setattr(hunt.identity, 'check_upstream', lambda *a: [])
    assert hunt.clone(cfg, 'org/lib') == root
    (root / 'source.py').write_text('unfinished user work\n')
    with pytest.raises(RuntimeError, match='dirty'):
        hunt.clone(cfg, 'org/lib')
    assert (root / 'source.py').read_text() == 'unfinished user work\n'
