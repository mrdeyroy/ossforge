from ossforge import audit, critique, predictor

SRC = '''
def f(x, acc=[]):
    try:
        pass
    except Exception:
        pass
    if x == None:
        pass
    seen = []
    for i in range(10):
        if i in seen:
            continue
        q = [1, 2]
        q.pop(0)
'''


def kinds(src):
    return {f.kind for f in audit.scan_source(src)}


def test_detectors():
    k = kinds(SRC)
    assert {"mutable-default", "swallowed-exception", "eq-none", "list-membership-in-loop", "pop0-in-loop"} <= k


def test_clean_code_has_no_findings():
    assert audit.scan_source("def f(x=None):\n    s = set()\n    for i in x or []:\n        if i in s:\n            pass\n") == []


def test_added_lines_parse():
    patch = "@@ -1,3 +1,4 @@\n a\n+b\n c\n+d\n"
    assert critique._added_lines(patch) == {2, 4}


def test_predictor():
    good = predictor.PRSignals("APPROVED", False, False, False, 1, 10, True, 3)
    bad = predictor.PRSignals(None, True, True, True, 40, 2000, False, 100)
    assert predictor.score_pr(good).label == "likely"
    assert predictor.score_pr(bad).label == "unlikely"


def test_critique_handles_ghost_or_deleted_user(monkeypatch):
    monkeypatch.setattr(critique, "signals", lambda repo, number: (
        {"title": "Fix memory leak", "user": None},
        predictor.PRSignals("APPROVED", False, False, False, 1, 10, True, 3),
        [],
    ))
    monkeypatch.setattr(critique, "added_line_findings", lambda *a, **k: [])
    c = critique.critique("owner/repo", 42)
    assert c.author == "ghost"
    assert "Hi @ghost," in c.draft

