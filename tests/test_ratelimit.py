import pytest

from ossforge import gh


def test_split_response_parses_headers_and_body():
    out = "HTTP/2.0 403 Forbidden\r\nRetry-After: 30\r\nX-Ratelimit-Remaining: 12\r\n\r\n{\"message\":\"x\"}"
    h, body = gh.split_response(out)
    assert h["status"] == "403" and h["retry-after"] == "30" and body == '{"message":"x"}'
    assert gh.split_response('{"a":1}') == ({}, '{"a":1}')


def test_secondary_limit_detected_without_status_text():
    assert gh.is_rate_limited(403, {"retry-after": "5"}, "")
    assert gh.is_rate_limited(429, {}, "")
    assert gh.is_rate_limited(403, {}, "You have exceeded a secondary rate limit")
    assert not gh.is_rate_limited(403, {}, "Resource not accessible by integration")
    assert not gh.is_rate_limited(404, {}, "Not Found")


def test_retry_wait_follows_documented_order():
    assert gh.retry_wait({"retry-after": "30"}) == 31
    h = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1100"}
    assert gh.retry_wait(h, now=1000) == 101
    assert gh.retry_wait({}, 0) == 60 and gh.retry_wait({}, 1) == 120


def test_cooldown_blocks_next_call(tmp_path):
    gh.configure(tmp_path / ".state" / "cache")
    try:
        gh._set_cooldown(120)
        with pytest.raises(gh.RateLimited) as e:
            gh._guard_cooldown()
        assert e.value.retry_after > 100
    finally:
        gh.configure(None)


def _worker(state, n, q):
    import time
    from ossforge import gh as g
    g.configure(state / "cache")
    t = []
    for _ in range(n):
        g.pace_write()
        t.append(time.time())
    q.put(t)


def test_write_pacing_is_shared_across_processes(tmp_path):
    import multiprocessing as mp
    q = mp.Queue()
    ps = [mp.Process(target=_worker, args=(tmp_path / ".state", 3, q)) for _ in range(3)]
    [p.start() for p in ps]
    times = sorted(t for _ in ps for t in q.get(timeout=30))
    [p.join() for p in ps]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) == 9 and min(gaps) >= gh.WRITE_GAP_S - 0.05


def test_corrupt_cooldown_marker_fails_closed(tmp_path):
    gh.configure(tmp_path / ".state" / "cache")
    try:
        (tmp_path / ".state").mkdir()
        (tmp_path / ".state" / "ratelimit_until").write_text("garbage")
        with pytest.raises(gh.RateLimited):
            gh._guard_cooldown()
    finally:
        gh.configure(None)


def test_set_cooldown_never_shortens(tmp_path):
    gh.configure(tmp_path / ".state" / "cache")
    try:
        gh._set_cooldown(300)
        gh._set_cooldown(10)
        with pytest.raises(gh.RateLimited) as e:
            gh._guard_cooldown()
        assert e.value.retry_after > 250
    finally:
        gh.configure(None)
