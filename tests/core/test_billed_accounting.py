"""Billed failures must survive shutdown and resume without another call."""
import pytest

from rewardbench.contracts import BudgetExceeded, BudgetLimits, ExperimentStatus, ModelClientError
from rewardbench.core.budget import BudgetLimiter
from rewardbench.core.runner import ExperimentRunner
from rewardbench.storage import SqliteStore
from fakes import FakeEnv, FakeModel, make_config, proposal


@pytest.mark.parametrize("kind", ["model", "budget"])
def test_billed_failure_is_durable_and_restored_once(tmp_path, kind):
    response = proposal(None, usage={
        "prompt_template": "v1", "pricing_version": "test", "request_id": "request-1",
        "response_model_id": "resolved", "applied_settings": {"seed": 7},
        "retry_count": 1, "calls": [{"ok": False}, {"ok": True}],
    })
    error = (ModelClientError("billed failure", retryable=False, response=response)
             if kind == "model" else BudgetExceeded(
                 "billed overrun", resource="provider_cost_usd", spent=.01,
                 limit=.005, response=response))
    config = make_config(num_revisions=1, budget=BudgetLimits(max_cost_usd=.005))
    global_budget = BudgetLimiter(BudgetLimits(max_cost_usd=1))
    store = SqliteStore(tmp_path / "accounting.sqlite")
    env = FakeEnv()
    runner = ExperimentRunner(config, FakeModel([error]), env, store, global_budget=global_budget)
    summary = runner.run()
    assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert (summary.model_calls, summary.total_tokens, summary.total_cost_usd) == (1, 12, .01)
    attempt = store.fetch_attempts(summary.experiment_id)[0]
    assert attempt.latency_seconds == .2
    assert attempt.usage == response.usage
    assert not attempt.valid and attempt.error == str(error)
    assert env.episodes == []
    assert global_budget.snapshot().cost_usd == pytest.approx(.01)
    assert global_budget.snapshot().tokens == 12
    store.close()

    from rewardbench.analysis.export import export_jsonl
    from rewardbench.analysis.load import load_logs
    bundle = load_logs(tmp_path / "accounting.sqlite")
    assert bundle.attempts[0].usage == response.usage
    exported = export_jsonl(bundle, tmp_path / "accounting.jsonl")
    assert load_logs(exported).attempts[0].usage == response.usage

    with SqliteStore(tmp_path / "accounting.sqlite") as reopened:
        model = FakeModel([])
        resumed = ExperimentRunner(config, model, FakeEnv(), reopened, global_budget=global_budget)
        again = resumed.run()
        assert again.total_cost_usd == pytest.approx(.01)
        assert again.total_tokens == 12
        assert model.requests == []
        assert global_budget.snapshot().cost_usd == pytest.approx(.01)
        assert global_budget.snapshot().model_calls == 1
        assert reopened.fetch_attempts(summary.experiment_id)[0].usage == response.usage


def test_pre_call_budget_pause_records_no_attempt(tmp_path):
    model = FakeModel([BudgetExceeded("session pause", resource="paid_calls", spent=0, limit=1)])
    with SqliteStore(tmp_path / "pause.sqlite") as store:
        shared = BudgetLimiter(BudgetLimits(max_cost_usd=1))
        summary = ExperimentRunner(make_config(), model, FakeEnv(), store, global_budget=shared).run()
        assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
        assert summary.model_calls == summary.total_tokens == summary.total_cost_usd == 0
        assert store.fetch_attempts(summary.experiment_id) == []
        assert shared.snapshot().model_calls == 0
        assert shared.snapshot().cost_usd == 0


@pytest.mark.parametrize("failure", ["http", "quote", "budget"])
def test_mocked_transport_billed_failures_reach_runner_storage(tmp_path, failure):
    import json
    from tests.providers.conftest import CONTROLLER, FakeTransport, http_json
    from tests.providers.test_adapters import _chat, _client

    payload = ({"error": {"message": "billed failure"},
                "usage": {"prompt_tokens": 20, "completion_tokens": 11, "total_tokens": 31}}
               if failure == "http" else _chat(json.dumps(CONTROLLER), prompt=20, completion=100000))
    transport = FakeTransport([http_json(payload, status=400 if failure == "http" else 200,
                                        latency=.7)])
    client = _client("openai", "gpt-5.4-mini", transport, max_retries=0,
                     max_spend_usd=.01 if failure == "budget" else 50)
    config = make_config(provider=client.provider, model_id=client.model_id, num_revisions=1,
                         budget=BudgetLimits(max_cost_usd=.000001),
                         model_settings={"max_output_tokens": 10})
    with SqliteStore(tmp_path / "transport.sqlite") as store:
        shared = BudgetLimiter(BudgetLimits(max_cost_usd=10))
        env = FakeEnv()
        summary = ExperimentRunner(config, client, env, store, global_budget=shared).run()
        assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
        assert summary.model_calls == 1
        assert summary.total_cost_usd == pytest.approx(client._spending.spent_usd)
        assert shared.snapshot().cost_usd == pytest.approx(summary.total_cost_usd)
        attempt = store.fetch_attempts(summary.experiment_id)[0]
        assert attempt.latency_seconds == .7
        assert attempt.total_tokens == (31 if failure == "http" else 100020)
        assert attempt.usage["pricing_version"]
        assert len(attempt.usage["calls"]) == 1
        assert attempt.usage["requested_settings"] == dict(config.model_settings)
        assert env.episodes == []
        assert len(transport.requests) == 1
