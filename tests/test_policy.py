from ossforge import policy


def test_explicit_unsupervised_agent_ban_with_markdown_emphasis():
    text = 'We do not police how you author changes. Absolutely **no** unsupervised agentic tools like ExampleBot.'
    result = policy.scan_files({'.github/AI_POLICY.md': text})
    assert result.anti_ai and result.source == '.github/AI_POLICY.md'


def test_ordinary_agent_tool_discussion_is_not_a_ban():
    assert not policy.scan_text('We allow supervised agentic tools and discuss unsupervised agentic tools.').anti_ai
