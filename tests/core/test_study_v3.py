"""Study v3: shared fixed starts, matched blocks, free seeding, exact pricing, predeclared analysis.

Only the HTTP transport is fake (no request leaves the process, no key is used); the run CLI, live preflight,
AggregateCeilingGate, autopilot, ledger and Node physics are real. Episodes are shortened for speed.
"""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import yaml

from rewardbench import autopilot, study, study_v3
from rewardbench.contracts import ConfigError
from rewardbench.core.ids import experiment_id
from rewardbench.environments.apollolander.schema import GUIDANCE_BOUNDS
from rewardbench.prompts import PROMPT_TEMPLATE_ID
from rewardbench.run.ceiling import ledger_spent_usd
from rewardbench.run.cli import main as real_run_main
from rewardbench.run.factory import prepare_config

from tests.core.test_autopilot import ArmTransport, guidance, ok
from tests.core.test_live_cli import TEST_KEY

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")

STARTS = study_v3.load_starts()
MISSION_010_IDS = {"no_feedback": "exp_ffa3fae153ea49e5284e", "reward_only": "exp_42eb966934fd53052f36",
                   "numerical_reward": "exp_424436e7f1700e3e7cfa"}


def short_block(tmp_path: Path, start: str = "crash1", *, seeds: int = 2, steps: int = 300,
                controller: dict | None = None) -> list[Path]:
    """One real v3 block (three arms), shortened so physics stays fast."""
    paths = []
    for condition in study_v3.CONDITIONS:
        config = study_v3.v3_config("pilot", condition, start, 1, STARTS)
        config.update(development_seeds=list(range(seeds)), episodes_per_revision=seeds, max_episode_steps=steps)
        config["metadata"]["adapter_kwargs"]["max_steps"] = steps
        if controller is not None:
            config["metadata"]["initial_controller"]["controller"] = controller
        config["budget"] = {"max_cost_usd": 1.0, "max_tokens": 10_000_000, "max_wall_seconds": 3600,
                            "max_revisions": study_v3.NUM_REVISIONS, "max_episodes": study_v3.NUM_REVISIONS * seeds,
                            "max_model_calls": study_v3.NUM_REVISIONS}
        path = tmp_path / "configs" / f"{condition}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        paths.append(path)
    return paths


def rows(database: Path, sql: str) -> list[tuple]:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        return db.execute(sql).fetchall()


@pytest.fixture
def block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def make(reply, **settings):
        transport = ArmTransport(reply)
        monkeypatch.setattr(autopilot, "run_main", lambda argv: real_run_main(
            argv, _api_key=TEST_KEY, _transport=transport, _sleeper=lambda _s: None))
        root = tmp_path / "ledger"
        out = root / "v3-pilot"
        root.mkdir()
        arms = autopilot.load_arms(short_block(tmp_path), out)
        values = {"ceiling_usd": 1.0, "max_total_calls": 100, "ledger_root": root, "out": out, **settings}
        return transport, arms, autopilot.Settings(**values)

    return make


def seed_all(arms) -> list[dict]:
    return [study_v3.seed(arm.path, database=arm.database) for arm in arms]


# ---------------------------------------------------------------- fixed start, seeding, paid rounds


def test_every_arm_starts_from_the_same_fixed_controller_without_a_model_call(block) -> None:
    transport, arms, settings = block(lambda arm, rev: ok(guidance(0.3 + 0.1 * rev)))
    seeded = seed_all(arms)
    assert transport.calls == [] and all(s["cost_usd"] == 0 and s["status"] == "interrupted" for s in seeded)
    assert ledger_spent_usd(settings.ledger_root)[0] == 0.0
    start = STARTS["starts"]["crash1"]["controller"]
    for arm in arms:
        attempts = rows(arm.database, "SELECT revision_index, provider, model_id, estimated_cost_usd, parameters_json "
                                      "FROM attempts")
        assert [(a[0], a[1], a[2], a[3]) for a in attempts] == [(0, "scripted", "fixed-start", 0.0)]
        assert json.loads(attempts[0][4]) == start
    rewards = {tuple(r[0] for r in rows(a.database, "SELECT total_reward FROM episodes ORDER BY seed")) for a in arms}
    assert len(rewards) == 1 and len(next(iter(rewards))) == 2  # identical flights in every arm
    assert seed_all(arms)[0]["revisions_completed"] == 1  # idempotent: nothing new recorded
    assert transport.calls == []


def test_paid_rounds_resume_after_the_fixed_start_one_call_per_invocation(block) -> None:
    transport, arms, settings = block(lambda arm, rev: ok(guidance(0.3 + 0.1 * rev)))
    seed_all(arms)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.PLANNED and "all arms completed 4 revisions" in outcome.stop_reason
    assert outcome.calls_made == 9 and outcome.rounds_completed == 3
    assert [rev for _arm, rev in transport.calls] == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert outcome.spent_after == pytest.approx(ledger_spent_usd(settings.ledger_root)[0]) and outcome.spent_after > 0
    prompts = {a.condition: (settings.out / "prompts" / a.name / "revision_01_call_00.txt").read_text(encoding="utf-8")
               for a in arms}
    start_json = json.dumps(STARTS["starts"]["crash1"]["controller"], sort_keys=True, separators=(",", ":"))
    assert all(f"revision 0: valid controller {start_json}" in p for p in prompts.values())
    assert "reward=" not in prompts["no_feedback"]
    assert "reward=" in prompts["reward_only"] and "success=" not in prompts["reward_only"]
    assert "success=" in prompts["numerical_reward"]
    result = study_v3.analyze(settings.out, search={})
    assert result["excluded_blocks"] == {} and list(result["blocks"]) == ["crash1-r1"]
    entry = result["blocks"]["crash1-r1"]
    assert {c: o["paid"] for c, o in entry["arms"].items()} == {c: 3 for c in study_v3.CONDITIONS}
    assert len({o["start_reward"] for o in entry["arms"].values()}) == 1
    assert result["summary"]["valid_fraction"] == 1.0


def test_autopilot_and_live_cli_refuse_an_unseeded_fixed_start(block, tmp_path: Path) -> None:
    transport, arms, settings = block(lambda arm, rev: ok(guidance()))
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.SAFETY and "study_v3 seed" in outcome.stop_reason
    assert outcome.calls_made == 0 and transport.calls == []
    code = real_run_main(["--config", str(arms[0].path), "--mode", "live", "--database", str(arms[0].database),
                          "--i-authorize-paid-api-calls"], _api_key=TEST_KEY, _transport=transport,
                         _sleeper=lambda _s: None)
    assert code == 2 and transport.calls == []


def test_whole_run_fit_refuses_a_block_that_could_be_cut_off(block) -> None:
    transport, arms, settings = block(lambda arm, rev: ok(guidance()))
    seed_all(arms)
    states = {a.name: autopilot.read_state(a) for a in arms}
    needed = autopilot.remaining_worst_case(arms, states, study.load_catalog())
    first_round = sum(autopilot.quote_next(a, 1, study.load_catalog()) for a in arms)
    assert first_round < needed
    tight = autopilot.Settings(**{**settings.__dict__, "ceiling_usd": needed - 0.001, "require_whole_run_fit": True})
    outcome = autopilot.run_autopilot(arms, tight, say=lambda _m: None)
    assert "--require-whole-run-fit" in outcome.stop_reason and outcome.calls_made == 0 and transport.calls == []
    enough = autopilot.Settings(**{**settings.__dict__, "ceiling_usd": needed + 0.001, "require_whole_run_fit": True})
    assert autopilot.run_autopilot(arms, enough, say=lambda _m: None).calls_made == 9


def test_an_invalid_fixed_start_fails_closed_before_anything_is_recorded(tmp_path: Path) -> None:
    bad = guidance()
    bad["parameters"]["hover_thrust"] = 5.0  # out of bounds
    path = short_block(tmp_path, controller=bad)[0]
    database = tmp_path / "bad.sqlite"
    with pytest.raises(ConfigError, match="initial_controller is not a valid controller"):
        study_v3.seed(path, database=database)
    assert rows(database, "SELECT COUNT(*) FROM experiments") == [(0,)]


def test_seed_refuses_a_config_without_a_fixed_start() -> None:
    with pytest.raises(ConfigError, match="no metadata.initial_controller"):
        study_v3.seed(study.config_path("pilot", "no_feedback"), database=Path("unused.sqlite"))


# ---------------------------------------------------------------- identity and matching


def test_v2_identities_and_evidence_are_untouched() -> None:
    for condition, expected in MISSION_010_IDS.items():
        assert experiment_id(prepare_config(study.config_path("pilot", condition))) == expected
    study.write_configs("pilot", study.CONFIG_DIR, check=True)


def test_configs_are_current_matched_and_reference_no_reserved_seed() -> None:
    paths = study_v3.write_configs(check=True)
    tiers = {tier: study_v3.blocks(tier, STARTS) for tier in study_v3.TIERS}
    assert tiers["pilot"] == [("crash1", 1), ("timeout1", 1)]
    assert len(tiers["study"]) == 12 and len(paths) == 3 * (2 + 12)
    ids = set()
    for tier, members in tiers.items():
        for start, replicate in members:
            raw = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
                   for p in study_v3.block_configs(tier, start, replicate)}
            study.check_matched(raw)
            for data in raw.values():
                assert data["num_revisions"] == study_v3.NUM_REVISIONS
                assert data["metadata"]["prompt_template"] == PROMPT_TEMPLATE_ID
                assert data["metadata"]["initial_controller"]["controller"] == STARTS["starts"][start]["controller"]
                assert data["database_path"].startswith(f"{study_v3.RUNS_ROOT}/v3-{tier}/")
                assert not set(data["development_seeds"] + data["held_out_seeds"]) & set(study.RESERVED_FINAL_SEEDS)
                assert data["max_model_retries"] == 0
            ids |= {experiment_id(prepare_config(p)) for p in study_v3.block_configs(tier, start, replicate)}
    assert len(ids) == len(paths) and not ids & set(MISSION_010_IDS.values())


def test_blocks_differ_only_in_start_replicate_and_names() -> None:
    a = yaml.safe_load(study_v3.config_path("study", "reward_only", "crash1", 1).read_text(encoding="utf-8"))
    b = yaml.safe_load(study_v3.config_path("study", "reward_only", "timeout2", 2).read_text(encoding="utf-8"))
    assert study.arm_differences(a, b) == {"experiment_name", "database_path", "metadata", "notes", "seed"}
    meta = study.arm_differences(a["metadata"], b["metadata"])
    assert meta == {"initial_controller", "block", "replicate"}


# ---------------------------------------------------------------- starts and references


def test_start_rule_is_mechanical() -> None:
    def outcome(landed=0, crashed=0, timeout=0):
        return {"landed_on_pad": landed, "crashed": crashed, "timeout": timeout}

    pool = [outcome(crashed=8), outcome(timeout=8), outcome(landed=1, crashed=7), outcome(crashed=5, timeout=3),
            outcome(crashed=6, timeout=2), outcome(timeout=6)]
    assert [study_v3.failure_type(o) for o in pool] == ["crash", "timeout", None, None, "crash", "timeout"]
    assert study_v3.select_starts(pool, 2) == [("crash1", 0), ("crash2", 4), ("timeout1", 1), ("timeout2", 5)]
    with pytest.raises(ConfigError):
        study_v3.select_starts(pool, 3)


def test_committed_starts_follow_the_rule_and_reproduce() -> None:
    pool = study_v3.start_pool()
    outcomes = STARTS["pool"]["outcomes"]
    chosen = study_v3.select_starts(outcomes, max(t["starts_per_type"] for t in study_v3.TIERS.values()))
    assert {label: index for label, index in chosen} == {k: v["pool_index"] for k, v in STARTS["starts"].items()}
    assert STARTS["direction_step"] == study_v3.DIRECTION_STEP
    evaluate = study_v3.evaluator()
    for label in ("crash1", "timeout1"):  # re-fly two of them; physics is deterministic
        entry = STARTS["starts"][label]
        assert entry["controller"] == pool[entry["pool_index"]]
        flown = evaluate(entry["controller"])
        assert flown["rewards"] == entry["rewards"]
        assert study_v3.failure_type(flown) == entry["type"]
    for entry in STARTS["starts"].values():
        for key, value in entry["controller"]["parameters"].items():
            lo, hi = GUIDANCE_BOUNDS[key]
            assert lo <= value <= hi and value == float(f"{value:.3g}")


def test_edit_alignment() -> None:
    before = guidance(0.5)
    directions = {k: 0 for k in GUIDANCE_BOUNDS} | {"descent_low": -1, "hover_thrust": 1}
    lower = {**before, "parameters": {**before["parameters"], "descent_low": 0.05}}
    assert study_v3.edit_alignment(before, lower, directions) == pytest.approx(1.0)
    worse = {**before, "parameters": {**before["parameters"], "descent_low": 0.15}}
    assert study_v3.edit_alignment(before, worse, directions) == pytest.approx(-1.0)
    mixed = {**lower, "parameters": {**lower["parameters"], "vy_gain": 20 + 0.25 * 40}}
    assert study_v3.edit_alignment(before, mixed, directions) == pytest.approx(0.5)
    assert study_v3.edit_alignment(before, before, directions) is None


def test_random_search_references_are_deterministic_and_matched() -> None:
    def fake(controller):
        return {"mean_reward": -sum(abs(v - (lo + hi) / 2) / (hi - lo)
                                    for v, (lo, hi) in zip(controller["parameters"].values(), GUIDANCE_BOUNDS.values()))}

    start = guidance(0.9)
    base = fake(start)["mean_reward"]
    climb = study_v3.random_search(start, base, fake, random.Random("x"), use_reward=True)
    again = study_v3.random_search(start, base, fake, random.Random("x"), use_reward=True)
    walk = study_v3.random_search(start, base, fake, random.Random("x"), use_reward=False)
    assert climb == again and len(climb["proposals"]) == study_v3.PAID_REVISIONS
    assert climb["final_reward"] == max([base] + climb["proposals"]) and climb["delta"] >= 0
    assert walk["final_reward"] == walk["proposals"][-1]


# ---------------------------------------------------------------- price and rules


def test_price_is_the_sum_of_exact_worst_case_quotes() -> None:
    p = study_v3.price(STARTS)
    for condition, arm in p["per_arm_per_block"].items():
        assert [c["revision"] for c in arm["calls"]] == [1, 2, 3]
        config = study_v3.v3_config("pilot", condition, "crash1", 1, STARTS)
        quotes = study.worst_case_calls(config, study._spec(config), study.load_catalog())[1:]
        assert arm["worst_case_usd"] == pytest.approx(sum(q["usd"] for q in quotes))
    block_ = p["block"]
    assert block_["paid_calls"] == 9 and sum(block_["round_worst_case_usd"]) == pytest.approx(block_["worst_case_usd"])
    assert p["tiers"]["pilot"]["paid_calls"] == 18
    assert p["tiers"]["pilot"]["worst_case_usd"] == pytest.approx(2 * block_["worst_case_usd"])
    budget = yaml.safe_load(study_v3.config_path("pilot", "numerical_reward", "crash1", 1).read_text())["budget"]
    assert budget["max_cost_usd"] >= p["per_arm_per_block"]["numerical_reward"]["worst_case_usd"]


def test_pilot_go_rule() -> None:
    def summary(valid, delta_ro, delta_num, align_ro=None, align_num=None):
        return {"valid_fraction": valid, "contrasts": {
            "reward_only_minus_no_feedback": {"mean_delta_difference": delta_ro, "mean_alignment_difference": align_ro},
            "numerical_reward_minus_no_feedback": {"mean_delta_difference": delta_num,
                                                   "mean_alignment_difference": align_num}}}

    assert study_v3.pilot_go(summary(1.0, 12.0, -5.0))["go_to_study_tier"]
    assert study_v3.pilot_go(summary(1.0, 0.0, 0.0, align_num=0.3))["go_to_study_tier"]
    assert not study_v3.pilot_go(summary(1.0, 9.9, 9.9, 0.2, 0.2))["go_to_study_tier"]
    assert not study_v3.pilot_go(summary(0.8, 50.0, 50.0))["go_to_study_tier"]
