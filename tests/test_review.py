from ossforge import review


def d(*lines):
    return "\n".join(["+++ b/x.py", *lines])


def test_code_without_test_warns_but_does_not_block():
    f = review.review_diff(["src/a.py"], d("+x = 1"))
    assert not review.blocking(f) and "no test file changed" in f[0].msg


def test_config_and_docs_changes_need_no_test_note():
    assert review.review_diff([".github/workflows/ci.yml", "pyproject.toml", "README.md"], d("+x")) == []


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
