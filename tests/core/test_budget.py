import pytest

from rewardbench.contracts import BudgetExceeded, BudgetLimits, BudgetSnapshot, ConfigError
from rewardbench.core.budget import BudgetLimiter


def test_limiter_blocks_the_next_call_at_the_cap() -> None:
    limiter = BudgetLimiter(BudgetLimits(max_model_calls=1, max_tokens=20, max_cost_usd=1))
    limiter.charge(model_calls=1, tokens=10, cost_usd=0.4)
    with pytest.raises(BudgetExceeded) as caught:
        limiter.ensure_can_start(model_call=True)
    assert caught.value.resource == "max_model_calls"


def test_charge_that_crosses_the_token_cap_is_kept() -> None:
    limiter = BudgetLimiter(BudgetLimits(max_tokens=10))
    with pytest.raises(BudgetExceeded) as caught:
        limiter.charge(tokens=12)
    assert limiter.tokens == 12
    assert caught.value.resource == "max_tokens"


def test_wall_clock_uses_the_injected_clock_and_restored_elapsed() -> None:
    clock = {"now": 0.0}

    def read() -> float:
        return clock["now"]

    limiter = BudgetLimiter(BudgetLimits(max_wall_seconds=5), clock=read)
    clock["now"] = 4.0
    limiter.ensure_can_start()
    clock["now"] = 5.0
    with pytest.raises(BudgetExceeded) as caught:
        limiter.ensure_can_start()
    assert caught.value.resource == "max_wall_seconds"
    restored = BudgetLimiter(BudgetLimits(max_wall_seconds=5), clock=read)
    restored.restore(BudgetSnapshot(0, 0, 0, 0, 0, 4.5))
    clock["now"] = 6.0
    with pytest.raises(BudgetExceeded):
        restored.ensure_can_start()


def test_negative_charge_is_rejected() -> None:
    limiter = BudgetLimiter(BudgetLimits())
    with pytest.raises(ConfigError):
        limiter.charge(cost_usd=-1)


def test_dollar_cap_does_not_block_an_already_purchased_episode() -> None:
    limiter = BudgetLimiter(BudgetLimits(max_cost_usd=1, max_episodes=2))
    limiter.charge(cost_usd=1)
    limiter.ensure_can_start(episode=True)
    with pytest.raises(BudgetExceeded) as caught:
        limiter.ensure_can_start(model_call=True)
    assert caught.value.resource == "max_cost_usd"


def test_recorded_spend_is_counted_once() -> None:
    limiter = BudgetLimiter(BudgetLimits(max_cost_usd=1))
    limiter.commit_once("attempt-1", cost_usd=0.4, tokens=5, model_calls=1)
    limiter.commit_once("attempt-1", cost_usd=0.4, tokens=5, model_calls=1)
    assert limiter.cost_usd == pytest.approx(0.4)
    assert limiter.model_calls == 1
    assert limiter.tokens == 5


def test_zero_or_negative_limits_are_rejected() -> None:
    with pytest.raises(ConfigError):
        BudgetLimits(max_episodes=0)
