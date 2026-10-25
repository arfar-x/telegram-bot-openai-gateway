from telegram_bot_gateway.domain import oidc

# Covers: FR-LNK-12, FR-LNK-14


def test_slow_down_adds_five_seconds_and_nothing_else_changes_the_interval():
    assert oidc.next_interval(5, slow_down=True) == 10
    assert oidc.next_interval(10, slow_down=True) == 15
    assert oidc.next_interval(5, slow_down=False) == 5


def test_a_token_is_usable_while_it_has_a_minute_left():
    assert oidc.token_usable(1000.0 + 60, 1000.0)
    assert not oidc.token_usable(1000.0 + 59, 1000.0)
    assert not oidc.token_usable(900.0, 1000.0)


def test_minutes_left_never_shows_zero():
    assert oidc.minutes_left(600, 0) == 10
    assert oidc.minutes_left(10, 0) == 1
