"""Regression tests for the ch06 end-to-end timeout budget."""

from scripts.ch06_devmate_team import MAX_ATTEMPTS, TIMEOUT_S


def test_timeout_budget_balances_headroom_and_runaway_retries() -> None:
    """Keep a single attempt above observed runtimes but bounded overall."""
    assert 360 <= TIMEOUT_S <= 600
    assert TIMEOUT_S * MAX_ATTEMPTS <= 1200
