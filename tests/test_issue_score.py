from datetime import datetime, timezone

from ossforge import scout

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def issue(**kw):
    base = {"updated_at": "2026-10-30T00:00:00Z", "labels": [{"name": "bug"}], "comments": 2,
            "author_association": "MEMBER"}
    return {**base, **kw}


def test_fresh_maintainer_bug_beats_stale_crowded_issue():
    good, g_why = scout.score_issue(issue(), 80, NOW)
    bad, b_why = scout.score_issue(issue(updated_at="2025-01-01T00:00:00Z", comments=30, labels=[],
                                         author_association="NONE"), 80, NOW)
    assert good > bad + 30
    assert "bug label" in g_why and any("crowded" in w for w in b_why)


def test_score_is_clamped_and_tolerates_missing_fields():
    s, _ = scout.score_issue({}, 100, NOW)
    assert 0 <= s <= 100
