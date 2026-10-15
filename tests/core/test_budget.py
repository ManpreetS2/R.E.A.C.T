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


def test_zero_or_negative_limits_are_rejected() -> None:
    with pytest.raises(ConfigError):
        BudgetLimits(max_episodes=0)
