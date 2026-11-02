from ossforge import loop, patrol
from ossforge.config import Config


def test_completed_loop_keeps_real_attention_in_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [patrol.Action('owner/repo', 7, 'changes_requested', 'a reviewer requested changes')])
    monkeypatch.setattr(loop.scout, 'scout', lambda *a, **k: [])
    monkeypatch.setattr(loop.scout, 'scout_features', lambda *a, **k: [])
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    loop.run_once(cfg)
    text = (tmp_path/'digest.md').read_text()
    assert 'a reviewer requested changes' in text
    assert 'owner/repo' in text


def test_rate_limited_discovery_keeps_already_fetched_attention(tmp_path, monkeypatch):
    from ossforge import gh
    monkeypatch.setattr(loop.patrol, 'patrol', lambda *a: [patrol.Action('owner/repo', 8, 'ci', 'test failed')])
    def limited(*a, **kw):
        raise gh.RateLimited('later read throttled', 403)
    monkeypatch.setattr(loop.scout, 'scout', limited)
    cfg = Config(state_dir=str(tmp_path), kill_file=str(tmp_path/'STOP'))
    loop.run_once(cfg)
    text = (tmp_path/'digest.md').read_text()
    assert 'test failed' in text and 'stopped early' in text
