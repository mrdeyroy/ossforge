from ossforge.config import Config
from ossforge.scout import is_spam


def test_default_filter_does_not_discard_authentication_token_bug():
    cfg = Config()
    assert not is_spam(
        'asyncio ConnectionPool: deferred re-auth in release() runs after connection is available',
        'With a streaming credential provider, a token rotation calls ConnectionPool.re_auth_callback(token). '
        'AUTH reply races another command and the original result is lost. Steps: run the standalone local Redis reproducer.',
        cfg.spam_keywords,
    )


def test_crypto_rewards_and_explicit_custom_token_filter_remain_blocked():
    cfg = Config()
    for title, body in [('Token giveaway', 'claim token'), ('Reward pool', 'token campaign'),
                        ('Token payment', 'we pay $100 for a token fix'), ('Payment', 'reward 5 USDT')]:
        assert is_spam(title, body, cfg.spam_keywords)
    assert is_spam('Token rotation', 'credential token error', ['token'])
