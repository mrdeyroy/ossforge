from ossforge import review


def d(*lines):
    return "\n".join(["+++ b/x.py", *lines])


def test_source_without_test_blocks():
    f = review.review_diff(["src/a.py"], d("+x = 1"))
    assert review.blocking(f) == ["source changed but no test file changed"]


def test_docs_only_change_needs_no_test():
    assert review.blocking(review.review_diff(["README.md"], d("+hello"))) == []


def test_debug_leftovers_are_warnings():
    f = review.review_diff(["src/a.py", "tests/test_a.py"], d("+    breakpoint()", "+# TODO: later", "+print('DEBUG x')"))
    msgs = [x.msg for x in f]
    assert len(msgs) == 3 and not review.blocking(f)


def test_template_sections_and_changelog():
    tpl = "## Summary\n## Testing\n"
    f = review.review_diff(["src/a.py", "tests/t.py"], d("+x=1"), pr_body="## Summary\nok", pr_template=tpl,
                           repo_files={"CHANGELOG.md"})
    msgs = " | ".join(x.msg for x in f)
    assert "testing" in msgs and "changelog" in msgs
    ok = review.review_diff(["src/a.py", "tests/t.py", "CHANGELOG.md"], d("+x=1"), pr_body="## Summary\n## Testing",
                            pr_template=tpl, repo_files={"CHANGELOG.md"})
    assert ok == []
