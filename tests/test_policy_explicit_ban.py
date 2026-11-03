from ossforge import policy


def test_actual_ytdlp_explicit_contribution_ban():
    text = '''# NO AI / NO LLM POLICY
This project strictly forbids the usage of LLMs, agents, or any other AI tools for any kind of contribution.
- No AI / no LLMs for issues or bug reports.
- No AI / no LLMs for patches or pull requests (including PR descriptions).
'''
    result = policy.scan_text(text, 'CONTRIBUTING.md')
    assert result.anti_ai and result.source == 'CONTRIBUTING.md'


def test_wrapped_usage_ban_without_heading():
    assert policy.scan_text('This project strictly forbids the usage of\nLLMs, agents, or any other AI tools for any kind of contribution.').anti_ai


def test_no_ban_or_quoted_title_is_not_a_prohibition():
    for text in ('We do not forbid the usage of LLMs for contributions.', 'There is no AI ban here.',
                 'We discuss a "NO AI / NO LLM POLICY" adopted by other projects.',
                 '# AI policy\nAI assistance is allowed with disclosure.'):
        assert not policy.scan_text(text).anti_ai


def test_disclosure_and_limited_tool_policy_not_blanket_bans():
    for text in ('The project requires disclosure of AI use for contributions.',
                 'This project forbids the use of AI tools for legal attestations, not contributions.',
                 'This project does not strictly forbid the usage of LLMs for contributions.'):
        assert not policy.scan_text(text).anti_ai
