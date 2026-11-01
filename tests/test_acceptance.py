from datetime import datetime, timedelta, timezone

from ossforge import acceptance as ac

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _pr(n, author, assoc, merged_days=None, closed_days=5, bot=False):
    closed = (NOW - timedelta(days=closed_days)).isoformat()
    return {"number": n, "user": {"login": author, "type": "Bot" if bot else "User"}, "author_association": assoc,
            "closed_at": closed, "merged_at": closed if merged_days is not None else None}


def test_outside_merges_count_and_bots_do_not():
    prs = [_pr(1, "dependabot[bot]", "NONE", 1, bot=True), _pr(2, "alice", "CONTRIBUTOR", 1, 10), _pr(3, "bob", "NONE", 1, 20),
           _pr(4, "maint", "MEMBER", 1, 3)]
    a = ac.summarize("o/r", prs, NOW, merged_by=lambda p: "maint")
    assert a.status == "accepting" and {m["author"] for m in a.external_merged} == {"alice", "bob"}


def test_author_merging_own_pr_is_not_acceptance():
    prs = [_pr(2, "alice", "CONTRIBUTOR", 1, 10)]
    a = ac.summarize("o/r", prs, NOW, merged_by=lambda p: "alice")
    assert a.status != "accepting" and any("own author" in r for r in a.reasons)


def test_old_outside_merge_is_not_current_evidence():
    a = ac.summarize("o/r", [_pr(2, "alice", "NONE", 1, 150)], NOW, merged_by=lambda p: "maint")
    assert a.status == "unknown"


def test_thin_data_is_unknown_not_negative():
    a = ac.summarize("o/r", [_pr(i, "maint", "MEMBER", 1) for i in range(3)], NOW)
    assert a.status == "unknown" and "not negative" in a.reasons[0]
    assert ac.summarize("o/r", [], NOW).status == "unknown"


def test_enough_human_prs_and_no_outside_merge_is_none():
    prs = [_pr(i, "maint", "MEMBER", 1, 3) for i in range(12)] + [_pr(99, "eve", "NONE", None, 8)]
    a = ac.summarize("o/r", prs, NOW)
    assert a.status == "none" and a.external_closed_unmerged == 1


def test_full_sample_covering_weeks_with_no_outside_merge_is_none():
    prs = [_pr(i, "maint", "MEMBER", 1, 3 + i) for i in range(30)] + [_pr(100 + i, "x", "NONE", None, 5 + i) for i in range(10)]
    a = ac.summarize("o/r", prs, NOW)
    assert a.status == "none" and a.covered_days >= 30 and a.external_closed_unmerged == 10


def test_full_sample_covering_days_only_is_unknown():
    prs = [_pr(i, "maint", "MEMBER", 1, 1) for i in range(40)]
    assert ac.summarize("o/r", prs, NOW).status == "unknown"
