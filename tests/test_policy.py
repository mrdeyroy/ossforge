from ossforge import policy


def test_explicit_unsupervised_agent_ban_with_markdown_emphasis():
    text = 'We do not police how you author changes. Absolutely **no** unsupervised agentic tools like ExampleBot.'
    result = policy.scan_files({'.github/AI_POLICY.md': text})
    assert result.anti_ai and result.source == '.github/AI_POLICY.md'


def test_ordinary_agent_tool_discussion_is_not_a_ban():
    assert not policy.scan_text('We allow supervised agentic tools and discuss unsupervised agentic tools.').anti_ai


def test_readme_and_contributing_rst_are_policy_sources(tmp_path):
    from ossforge import hunt
    for name in ('README.rst', 'CONTRIBUTING.rst', '.github/CONTRIBUTING.rst', 'docs/CONTRIBUTING.rst'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('No AI-assisted contributions.')
        assert hunt.policy_of(tmp_path).anti_ai
        path.unlink()


def test_rst_restrictions_are_in_review_snapshot(monkeypatch):
    from ossforge import policy_review
    monkeypatch.setattr(policy_review.gh, 'existing_files', lambda repo, paths: [p for p in paths if p == 'README.rst'])
    import base64
    text = 'Automated issue reports need production examples, not contrived examples.'
    monkeypatch.setattr(policy_review.gh, 'api', lambda *a, **k: {
        'encoding': 'base64', 'content': base64.b64encode(text.encode()).decode(),
        'html_url': 'https://github.com/local/fixture/blob/main/README.rst', 'sha': 'fixture',
    })
    snap = policy_review.snapshot('local/fixture')
    assert snap['docs'][0]['text'] == text and snap['docs'][0]['path'] == 'README.rst'
