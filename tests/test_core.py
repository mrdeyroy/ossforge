from ossforge.limiter import DailyLimiter
from ossforge.policy import scan_files, scan_text


def test_anti_ai_detected():
    r = scan_files({"CONTRIBUTING.md": "We require human-authored only changes."})
    assert r.anti_ai and r.source == "CONTRIBUTING.md"


def test_clean_repo():
    assert not scan_text("PRs welcome, please add tests.").anti_ai


def test_daily_cap(tmp_path):
    lim = DailyLimiter(tmp_path / "s.json", cap=2)
    assert lim.remaining() == 2
    lim.record()
    lim.record()
    assert lim.remaining() == 0
