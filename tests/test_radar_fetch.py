from ossforge import gh, radar


def test_inactive_repo_costs_no_search_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(gh, "api", lambda path, **k: {"pushed_at": "2022-01-01T00:00:00Z", "archived": False})
    monkeypatch.setattr(gh, "search_page", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(gh, "search_count", lambda *a, **k: calls.append(1))
    r = radar.analyze.__wrapped__("o/r") if hasattr(radar.analyze, "__wrapped__") else radar._analyze("o/r", 90, 14)
    assert r.score == 0 and "inactive" in r.flags and not calls


def test_active_repo_uses_three_searches_not_four(monkeypatch):
    n = {"search": 0}
    monkeypatch.setattr(gh, "api", lambda path, **k: {"pushed_at": "2999-01-01T00:00:00Z", "stargazers_count": 900})

    def page(q, **k):
        n["search"] += 1
        return {"total_count": 10, "items": []}
    monkeypatch.setattr(gh, "search_page", page)
    monkeypatch.setattr(gh, "search_count", lambda q, **k: n.__setitem__("search", n["search"] + 1) or 2)
    radar._analyze("o/r", 90, 14)
    assert n["search"] == 3
