"""Controlled feedback study v3 (offline tooling only; docs/STUDY_V3_PROTOCOL.md).

v3 changes one thing relative to the v2 pilot: every arm of a block starts from the **same fixed controller**
(revision 0 is flown without a model call), chosen before any v3 model output exists by a mechanical rule
from the v2 uniform guidance pool. Task, prompt (v4), feedback conditions, seeds, steps and model settings are
the v2 ones. Outcomes are improvements over that shared start, so arms are never compared on unrelated
initial scores.

    python -m rewardbench.study_v3 starts --out docs/assets/study-v3/starts.json      # scripted, free
    python -m rewardbench.study_v3 random-search --out docs/assets/study-v3/random_search.json
    python -m rewardbench.study_v3 write-configs [--check]
    python -m rewardbench.study_v3 budget
    python -m rewardbench.study_v3 seed --config PATH [--config PATH ...]          # fly revision 0, free
    python -m rewardbench.study_v3 analyze --out runs/first-llm-study/v3-pilot [--json FILE]
    python -m rewardbench.study_v3 rehearse --out runs/v3-rehearsal                # scripted mock, free

Nothing here opens a provider socket, reads a credential or flies a held-out seed. Paid calls go through
``rewardbench.autopilot`` and ``rewardbench.run`` unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from rewardbench import study
from rewardbench.contracts import BudgetExceeded, ConfigError
from rewardbench.environments.apollolander.schema import GUIDANCE_BOUNDS, SCHEMA_ID
from rewardbench.providers.pricing import load_catalog

STUDY_ID = "feedback_study.v3"
PROTOCOL_DOC = "docs/STUDY_V3_PROTOCOL.md"
CONDITIONS = study.CONDITIONS
NUM_REVISIONS = 4  # revision 0 is the fixed start; revisions 1-3 are paid model calls (the v2 pilot's 4 revisions)
PAID_REVISIONS = NUM_REVISIONS - 1
# The start pool is the v2 uniform guidance search (same seed and size, drawn before any model data existed),
# rounded to 3 significant figures so prompts show short numbers. The rounded controllers are what is flown.
POOL_SEED = 20261026
POOL_SIZE = 48
# Mechanical selection rule, fixed before any v3 call: no pad landing and at least 6 of 8 episodes of one
# failure type; first qualifying pool indices in order.
FAILURE_MIN = 6
START_TYPES = ("crash", "timeout")
TIERS: dict[str, dict[str, int]] = {
    "pilot": {"starts_per_type": 1, "replicates": 1},
    "study": {"starts_per_type": 3, "replicates": 2},
}
# Edit directions: each parameter moved by this fraction of its bound range, both ways, from the start.
DIRECTION_STEP = 0.25
DIRECTION_MIN_GAIN = 1.0  # reward; a smaller difference counts as "no preferred direction"
# Matched random search: same number of proposals as paid revisions, Gaussian steps in bound-normalised units.
SEARCH_SIGMA = 0.10
SEARCH_REPLICATES = 16
SEARCH_SEED = 20261111
# Expected spend per paid call, measured in Mission 010 (same prompt v4, same model): USD by condition and
# revision index of the call (1 = one history entry). Used for the expected column only; limits use quotes.
MEASURED_V2_COST = {
    "no_feedback": {1: 0.002548, 2: 0.002679, 3: 0.0028140},
    "reward_only": {1: 0.0026467, 2: 0.002862, 3: 0.003072},
    "numerical_reward": {1: 0.0037515, 2: 0.005067, 3: 0.0063893},
}
ROOT = study.ROOT
CONFIG_DIR = ROOT / "configs" / "study_v3"
EVIDENCE_DIR = ROOT / "docs" / "assets" / "study-v3"
STARTS_FILE = EVIDENCE_DIR / "starts.json"
SEARCH_FILE = EVIDENCE_DIR / "random_search.json"
RUNS_ROOT = "runs/first-llm-study"  # the shared ledger root: v1/v2 spend counts toward every v3 ceiling


# ---------------------------------------------------------------- flying controllers (scripted, free)


def guidance(parameters: Mapping[str, float]) -> dict[str, Any]:
    return {"schema": SCHEMA_ID, "policy": "guidance", "parameters": dict(parameters)}


def _round3(value: float) -> float:
    return float(f"{value:.3g}")


def start_pool() -> list[dict[str, Any]]:
    """The 48 v2 uniform samples, rounded to 3 significant figures and kept inside the bounds."""
    rng = random.Random(POOL_SEED)
    pool = []
    for _ in range(POOL_SIZE):
        sample = {k: rng.uniform(lo, hi) for k, (lo, hi) in GUIDANCE_BOUNDS.items()}
        pool.append(guidance({k: min(hi, max(lo, _round3(v))) for (k, v), (lo, hi)
                              in zip(sample.items(), GUIDANCE_BOUNDS.values())}))
    return pool


def evaluator(seeds: Sequence[int] = study.DEVELOPMENT_SEEDS,
              max_steps: int = study.MAX_EPISODE_STEPS) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Fly one controller on the development seeds with the study's adapter settings. No model, no network."""
    from rewardbench.environments.apollolander import ApolloLanderAdapter

    def evaluate(controller: dict[str, Any]) -> dict[str, Any]:
        adapter = ApolloLanderAdapter(research_mode=True, max_steps=max_steps,
                                      start_schedule_version="apollolander.starts.v1", vary_fuel=False)
        result = adapter.evaluate(controller, list(seeds), split="development", origin="deterministic_mock",
                                  model="scripted-v3")
        statuses = [e["status"] for e in result["episodes"]]
        return {"mean_reward": result["mean_reward"], "landed_on_pad": result["landing_count"],
                "gentle": statuses.count("landed"), "hard": statuses.count("hard_landing"),
                "crashed": result["crash_count"], "timeout": statuses.count("timeout"),
                "outside_pad": statuses.count("landed_outside_zone"),
                "rewards": [e["reward"] for e in result["episodes"]]}

    return evaluate


def _parallel(fn, items, workers: int = 16):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def failure_type(outcome: Mapping[str, Any]) -> str | None:
    if outcome["landed_on_pad"]:
        return None
    if outcome["crashed"] >= FAILURE_MIN:
        return "crash"
    if outcome["timeout"] >= FAILURE_MIN:
        return "timeout"
    return None


def select_starts(outcomes: Sequence[Mapping[str, Any]], per_type: int) -> list[tuple[str, int]]:
    """``[(label, pool_index)]``: the first ``per_type`` pool indices of each failure type, crash first."""
    chosen = []
    for kind in START_TYPES:
        hits = [i for i, outcome in enumerate(outcomes) if failure_type(outcome) == kind][:per_type]
        if len(hits) < per_type:
            raise ConfigError(f"the start pool has only {len(hits)} {kind} controllers; {per_type} needed")
        chosen += [(f"{kind}{n + 1}", index) for n, index in enumerate(hits)]
    return chosen


def nudged(controller: Mapping[str, Any], key: str, sign: int, step: float = DIRECTION_STEP) -> dict[str, Any]:
    lo, hi = GUIDANCE_BOUNDS[key]
    params = dict(controller["parameters"])
    params[key] = min(hi, max(lo, params[key] + sign * step * (hi - lo)))
    return guidance(params)


def directions_from(base: float, up: Mapping[str, float], down: Mapping[str, float]) -> dict[str, int]:
    """+1 if raising the parameter helps more than lowering it (by at least DIRECTION_MIN_GAIN), -1 the reverse."""
    out = {}
    for key in GUIDANCE_BOUNDS:
        gain_up, gain_down = up[key] - base, down[key] - base
        best = max(gain_up, gain_down)
        if best < DIRECTION_MIN_GAIN or abs(gain_up - gain_down) < DIRECTION_MIN_GAIN:
            out[key] = 0
        else:
            out[key] = 1 if gain_up > gain_down else -1
    return out


def build_starts(*, workers: int = 16, evaluate=None) -> dict[str, Any]:
    """Fly the pool, apply the selection rule for the largest tier, and measure edit directions per start."""
    evaluate = evaluate or evaluator()
    pool = start_pool()
    outcomes = _parallel(evaluate, pool, workers)
    per_type = max(spec["starts_per_type"] for spec in TIERS.values())
    starts = {}
    for label, index in select_starts(outcomes, per_type):
        controller = pool[index]
        keys = list(GUIDANCE_BOUNDS)
        up = _parallel(lambda k: evaluate(nudged(controller, k, +1))["mean_reward"], keys, workers)
        down = _parallel(lambda k: evaluate(nudged(controller, k, -1))["mean_reward"], keys, workers)
        base = outcomes[index]["mean_reward"]
        starts[label] = {
            "pool_index": index, "type": label.rstrip("0123456789"), "controller": controller,
            "outcome": {k: v for k, v in outcomes[index].items() if k != "rewards"},
            "rewards": outcomes[index]["rewards"],
            "nudge_up_mean_reward": dict(zip(keys, up)), "nudge_down_mean_reward": dict(zip(keys, down)),
            "helpful_direction": directions_from(base, dict(zip(keys, up)), dict(zip(keys, down))),
        }
    return {
        "purpose": "fixed v3 starting controllers, chosen by a mechanical rule from scripted flights only; "
                   "no model output was used",
        "pool": {"seed": POOL_SEED, "size": POOL_SIZE, "rounding": "3 significant figures, clipped to bounds",
                 "types": {kind: [i for i, o in enumerate(outcomes) if failure_type(o) == kind] for kind in START_TYPES},
                 "outcomes": [{k: v for k, v in o.items() if k != "rewards"} for o in outcomes]},
        "rule": f"no pad landing and >= {FAILURE_MIN}/8 episodes of one failure type; first pool indices",
        "direction_step": DIRECTION_STEP, "direction_min_gain": DIRECTION_MIN_GAIN,
        "seeds": list(study.DEVELOPMENT_SEEDS), "max_steps": study.MAX_EPISODE_STEPS,
        "start_schedule": "apollolander.starts.v1",
        "starts": starts,
    }


def load_starts(path: Path = STARTS_FILE) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{path} is missing; run `python -m rewardbench.study_v3 starts --out {path}`")
    return json.loads(path.read_text(encoding="utf-8"))


def tier_starts(tier: str, starts: Mapping[str, Any]) -> list[str]:
    per_type = TIERS[tier]["starts_per_type"]
    return [f"{kind}{n}" for kind in START_TYPES for n in range(1, per_type + 1) if f"{kind}{n}" in starts["starts"]]


# ---------------------------------------------------------------- edit analysis


def normalised_edit(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, float]:
    b, a = before["parameters"], after["parameters"]
    return {k: (a[k] - b[k]) / (hi - lo) for k, (lo, hi) in GUIDANCE_BOUNDS.items()}


def edit_alignment(before: Mapping[str, Any], after: Mapping[str, Any], directions: Mapping[str, int]) -> float | None:
    """Share of the edit (L1, in bound-normalised units) that goes in a helpful direction, minus the share
    that goes against one. +1: every change helps; -1: every change hurts; 0: neutral or balanced.
    None when nothing changed."""
    edit = normalised_edit(before, after)
    total = sum(abs(v) for v in edit.values())
    if total == 0:
        return None
    return sum(directions[k] * v for k, v in edit.items()) / total


# ---------------------------------------------------------------- matched random search (scripted, free)


def perturb(controller: Mapping[str, Any], rng: random.Random, sigma: float = SEARCH_SIGMA) -> dict[str, Any]:
    params = {}
    for key, (lo, hi) in GUIDANCE_BOUNDS.items():
        value = controller["parameters"][key] + rng.gauss(0.0, sigma) * (hi - lo)
        params[key] = min(hi, max(lo, value))  # clipping is part of this scripted baseline, never of the model path
    return guidance(params)


def random_search(start: Mapping[str, Any], start_reward: float, evaluate, rng: random.Random,
                  proposals: int = PAID_REVISIONS, *, use_reward: bool) -> dict[str, Any]:
    """``use_reward``: hill climb (keep a proposal only if it scores higher). Otherwise a blind random walk
    that always keeps the latest proposal, the scripted analogue of revising without feedback."""
    current, current_reward, trail = dict(start), start_reward, []
    for _ in range(proposals):
        candidate = perturb(current, rng)
        reward = evaluate(candidate)["mean_reward"]
        trail.append(reward)
        if not use_reward or reward > current_reward:
            current, current_reward = candidate, reward
    return {"final_reward": current_reward, "delta": current_reward - start_reward, "proposals": trail}


def build_random_search(starts: Mapping[str, Any], *, replicates: int = SEARCH_REPLICATES, workers: int = 16,
                        evaluate=None) -> dict[str, Any]:
    evaluate = evaluate or evaluator()
    jobs = [(label, kind, r) for label in starts["starts"] for kind in ("hill_climb", "random_walk")
            for r in range(replicates)]

    def run(job):
        label, kind, r = job
        entry = starts["starts"][label]
        rng = random.Random(f"{SEARCH_SEED}:{label}:{kind}:{r}")
        return job, random_search(entry["controller"], entry["outcome"]["mean_reward"], evaluate, rng,
                                  use_reward=kind == "hill_climb")

    results = _parallel(run, jobs, workers)
    out: dict[str, Any] = {"purpose": "scripted matched random-search references; NOT model results",
                           "proposals": PAID_REVISIONS, "sigma": SEARCH_SIGMA, "replicates": replicates,
                           "seed": SEARCH_SEED, "starts": {}}
    for (label, kind, _r), result in results:
        out["starts"].setdefault(label, {}).setdefault(kind, []).append(result)
    for label, kinds in out["starts"].items():
        for kind in list(kinds):
            deltas = [x["delta"] for x in kinds[kind]]
            kinds[f"{kind}_summary"] = {"mean_delta": statistics.fmean(deltas),
                                        "median_delta": statistics.median(deltas),
                                        "p75_delta": sorted(deltas)[int(0.75 * (len(deltas) - 1))],
                                        "fraction_improved": sum(d > 0 for d in deltas) / len(deltas)}
    return out


# ---------------------------------------------------------------- configs


def experiment_name(tier: str, condition: str, start: str, replicate: int) -> str:
    return (f"llmstudy3-{tier}-openai-gpt54mini-{condition.replace('_', '')}-{study.PROMPT_TAG}-{start}"
            f"-r{replicate}")


def v3_config(tier: str, condition: str, start: str, replicate: int, starts: Mapping[str, Any],
              budget: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """v2's matched pilot config with the fixed start added; only condition varies inside a block."""
    if tier not in TIERS:
        raise ConfigError(f"unknown tier {tier!r}")
    entry = starts["starts"][start]
    config = study.study_config("pilot", condition, replicate=replicate)
    name = experiment_name(tier, condition, start, replicate)
    config.update(
        experiment_name=name, num_revisions=NUM_REVISIONS,
        database_path=f"{RUNS_ROOT}/v3-{tier}/{name}.sqlite",
        # The engineering held-out seeds are listed only because a config needs a disjoint held-out list;
        # v3 analysis is on development seeds and the reserved cohort is never referenced.
        held_out_seeds=list(study.ENGINEERING_HELDOUT_SEEDS),
        budget=dict(budget) if budget else {},
    )
    meta = config["metadata"]
    meta.update(study=STUDY_ID, protocol=PROTOCOL_DOC, tier=tier, replicate=replicate,
                final_eval_cohort="none (development outcomes only)",
                block=f"{start}-r{replicate}",
                initial_controller={"label": start, "type": entry["type"], "pool_index": entry["pool_index"],
                                    "source": f"v2 uniform guidance pool seed {POOL_SEED}, rounded to 3 s.f.",
                                    "controller": entry["controller"]})
    config["notes"] = (f"{STUDY_ID} {tier} block {start}-r{replicate}, arm {condition} ({PROTOCOL_DOC}). "
                       "Revision 0 is the fixed start (no model call); revisions 1-3 are paid. Matched to its "
                       "sibling arms in every field except feedback_condition and names.")
    return config


def ceilings(starts: Mapping[str, Any]) -> dict[str, Any]:
    """Per-experiment budget block: worst case of the three paid calls of the largest-prompt arm."""
    first = tier_starts("pilot", starts)[0]
    config = v3_config("pilot", "numerical_reward", first, 1, starts)
    calls = study.worst_case_calls(config, study._spec(config), load_catalog())[1:]
    return {"max_cost_usd": math.ceil(sum(c["usd"] for c in calls) * 100) / 100,
            "max_tokens": int(math.ceil(sum(c["tokens"] for c in calls) / 1000) * 1000),
            "max_wall_seconds": 3600, "max_revisions": NUM_REVISIONS,
            "max_episodes": NUM_REVISIONS * study.EPISODES_PER_REVISION,
            "max_model_calls": NUM_REVISIONS}  # includes the unbilled fixed-start attempt


HEADER = (
    "# {study}: one arm of a v3 block ({protocol}). NOT AUTHORIZED TO RUN.\n"
    "# Revision 0 is a fixed starting controller flown offline (`python -m rewardbench.study_v3 seed`).\n"
    "# Paid revisions need the owner's approval of a total USD ceiling and call count (docs/STUDY_V3_PROTOCOL.md).\n"
    "# Generated by `python -m rewardbench.study_v3 write-configs`; do not hand-edit (a test enforces it).\n"
)


def config_path(tier: str, condition: str, start: str, replicate: int, base: Path = CONFIG_DIR) -> Path:
    return base / f"{tier}_{start}_r{replicate}_{condition}.yaml"


def blocks(tier: str, starts: Mapping[str, Any]) -> list[tuple[str, int]]:
    return [(start, r) for r in range(1, TIERS[tier]["replicates"] + 1) for start in tier_starts(tier, starts)]


def write_configs(base: Path = CONFIG_DIR, *, check: bool = False, starts: Mapping[str, Any] | None = None) -> list[Path]:
    starts = starts or load_starts()
    budget = ceilings(starts)
    written, stale = [], []
    for tier in TIERS:
        for start, replicate in blocks(tier, starts):
            for condition in CONDITIONS:
                path = config_path(tier, condition, start, replicate, base)
                text = HEADER.format(study=STUDY_ID, protocol=PROTOCOL_DOC) + yaml.safe_dump(
                    v3_config(tier, condition, start, replicate, starts, budget), sort_keys=False, width=100)
                if check:
                    if not path.exists() or path.read_text(encoding="utf-8") != text:
                        stale.append(path)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                written.append(path)
    if stale:
        raise ConfigError("v3 configs are out of date: " + ", ".join(str(p) for p in stale))
    return written


def block_configs(tier: str, start: str, replicate: int, base: Path = CONFIG_DIR) -> list[Path]:
    return [config_path(tier, c, start, replicate, base) for c in CONDITIONS]


# ---------------------------------------------------------------- price


def price(starts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Exact worst-case quotes (the bound the live gates enforce) and the expected spend from Mission 010."""
    starts = starts or load_starts()
    catalog = load_catalog()
    first = tier_starts("pilot", starts)[0]
    per_arm = {}
    for condition in CONDITIONS:
        config = v3_config("pilot", condition, first, 1, starts)
        calls = study.worst_case_calls(config, study._spec(config), catalog)[1:]
        per_arm[condition] = {"calls": [{"revision": c["revision"], "worst_case_usd": c["usd"],
                                         "prompt_token_ceiling": c["prompt_tokens"],
                                         "expected_usd": MEASURED_V2_COST[condition][c["revision"]]}
                                        for c in calls]}
        per_arm[condition]["worst_case_usd"] = sum(c["worst_case_usd"] for c in per_arm[condition]["calls"])
        per_arm[condition]["expected_usd"] = sum(c["expected_usd"] for c in per_arm[condition]["calls"])
    block_worst = sum(a["worst_case_usd"] for a in per_arm.values())
    block_expected = sum(a["expected_usd"] for a in per_arm.values())
    rounds = [sum(per_arm[c]["calls"][k]["worst_case_usd"] for c in CONDITIONS) for k in range(PAID_REVISIONS)]
    tiers = {}
    for tier in TIERS:
        n = len(blocks(tier, starts))
        tiers[tier] = {"blocks": n, "paid_calls": n * 3 * PAID_REVISIONS, "worst_case_usd": n * block_worst,
                       "expected_usd": n * block_expected}
    return {"model": "openai:gpt-5.4-mini", "catalog": catalog.version, "per_arm_per_block": per_arm,
            "block": {"paid_calls": 3 * PAID_REVISIONS, "worst_case_usd": block_worst,
                      "expected_usd": block_expected, "round_worst_case_usd": rounds},
            "tiers": tiers}


# ---------------------------------------------------------------- seeding revision 0 (free)


class _StartOnly:
    """Model stand-in for the seed step: the fixed start needs no call, and any request is refused before
    it is built, exactly like a closed live-session gate (so the arm pauses, resumable by a paid run)."""

    def __init__(self, provider: str, model_id: str) -> None:
        self.provider, self.model_id = provider, model_id

    def propose(self, request):
        from rewardbench.run.live import SESSION_CALL_RESOURCE

        raise BudgetExceeded("fixed start recorded offline; live session paid-call limit reached (0/0). "
                             "Paid revisions run through rewardbench.autopilot or rewardbench.run --mode live.",
                             resource=SESSION_CALL_RESOURCE, spent=0.0, limit=0.0)


def seed(path: Path, *, database: Path | None = None) -> dict[str, Any]:
    """Record and fly revision 0 (the fixed start) of one arm. No network, no key, no spend. Idempotent."""
    from rewardbench.core.ids import experiment_id
    from rewardbench.core.runner import ExperimentRunner
    from rewardbench.run.cli import _flight_adapter_overrides
    from rewardbench.run.factory import build_environment, prepare_config
    from rewardbench.storage import SqliteStore

    config = prepare_config(path, database_path=database)
    if config.metadata.get("initial_controller") is None:
        raise ConfigError(f"{path} has no metadata.initial_controller; nothing to seed")
    db = Path(config.database_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    exp_id = experiment_id(config)
    overrides = _flight_adapter_overrides(config, experiment_id=exp_id, database=db)
    overrides.update(split=config.split.value, origin="deterministic_mock")
    environment = build_environment(config, adapter_overrides=overrides)
    store = SqliteStore(db)
    try:
        store.initialize()
        summary = ExperimentRunner(config, _StartOnly(config.provider, config.model_id), environment, store).run()
    finally:
        store.close()
        close = getattr(environment, "close", None)
        if callable(close):
            close()
    return {"experiment_id": exp_id, "database": str(db), "status": summary.status.value,
            "revisions_completed": summary.revisions_completed, "mean_reward": summary.mean_reward,
            "cost_usd": summary.total_cost_usd}


# ---------------------------------------------------------------- analysis (read-only)


def _mean_or_none(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def t_interval(values: Sequence[float], confidence: float = 0.95) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    from scipy import stats

    mean, sd = statistics.fmean(values), statistics.stdev(values)
    half = stats.t.ppf(0.5 + confidence / 2, len(values) - 1) * sd / math.sqrt(len(values))
    return mean - half, mean + half


def read_arm(database: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        exp = db.execute("SELECT experiment_id, feedback_condition, status, config_json FROM experiments").fetchone()
        attempts = db.execute("SELECT revision_index, valid, parameters_json, provider, estimated_cost_usd "
                              "FROM attempts WHERE selected = 1 ORDER BY revision_index").fetchall()
        episodes = db.execute("SELECT revision_index, total_reward, success, crashed, truncated, metrics_json "
                              "FROM episodes WHERE error IS NULL ORDER BY revision_index, seed").fetchall()
        cost = db.execute("SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM attempts").fetchone()[0]
    meta = json.loads(exp["config_json"])["metadata"]
    revisions = []
    for a in attempts:
        rows = [e for e in episodes if e["revision_index"] == a["revision_index"]]
        revisions.append({
            "revision": a["revision_index"], "valid": bool(a["valid"]), "provider": a["provider"],
            "controller": json.loads(a["parameters_json"]) if a["valid"] else None,
            "mean_reward": _mean_or_none([e["total_reward"] for e in rows]),
            "landed": sum(bool(e["success"]) for e in rows), "crashed": sum(bool(e["crashed"]) for e in rows),
            "timeouts": sum(bool(e["truncated"]) for e in rows),
            "gentle": sum(1 for e in rows if e["success"] and json.loads(e["metrics_json"]).get("vertical_speed", 1) < 0.075),
            "episodes": len(rows)})
    return {"experiment_id": exp["experiment_id"], "condition": exp["feedback_condition"], "status": exp["status"],
            "block": meta.get("block"), "start": (meta.get("initial_controller") or {}).get("label"),
            "tier": meta.get("tier"), "cost_usd": float(cost), "revisions": revisions}


def arm_outcomes(arm: Mapping[str, Any], directions: Mapping[str, int], num_revisions: int = NUM_REVISIONS) -> dict[str, Any]:
    revs = arm["revisions"]
    start = revs[0]
    paid = [r for r in revs[1:]]
    valid = [r for r in revs if r["valid"] and r["mean_reward"] is not None]
    final = valid[-1]  # last valid selected controller (the start if no paid proposal was valid)
    first_edit = next((r for r in paid if r["valid"]), None)
    return {
        "complete": len(revs) == num_revisions and all(r["valid"] is not None for r in revs),
        "start_reward": start["mean_reward"],
        "rewards": [r["mean_reward"] for r in revs],
        "valid_paid": sum(r["valid"] for r in paid), "paid": len(paid),
        "delta_final": final["mean_reward"] - start["mean_reward"],
        "delta_best": max(r["mean_reward"] for r in valid) - start["mean_reward"],
        "final_revision": final["revision"],
        "final_outcome": {k: final[k] for k in ("landed", "gentle", "crashed", "timeouts")},
        "first_edit_alignment": None if first_edit is None else edit_alignment(start["controller"], first_edit["controller"], directions),
        "overall_alignment": None if final is start else edit_alignment(start["controller"], final["controller"], directions),
        "edit_alignments": [None if not (a["valid"] and b["valid"]) else edit_alignment(a["controller"], b["controller"], directions)
                            for a, b in zip(revs, revs[1:])],
        "cost_usd": arm["cost_usd"],
    }


def analyze(out: Path, *, starts: Mapping[str, Any] | None = None, search: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every predeclared v3 outcome from the arm databases under ``out``. Read-only."""
    starts = starts or load_starts()
    if search is None and SEARCH_FILE.exists():
        search = json.loads(SEARCH_FILE.read_text(encoding="utf-8"))
    arms = [read_arm(p) for p in sorted(Path(out).glob("*.sqlite"))]
    grouped: dict[str, dict[str, Any]] = {}
    for arm in arms:
        grouped.setdefault(arm["block"], {})[arm["condition"]] = arm
    result: dict[str, Any] = {"blocks": {}, "excluded_blocks": {}}
    for block, members in sorted(grouped.items()):
        start = next(iter(members.values()))["start"]
        directions = starts["starts"][start]["helpful_direction"]
        if set(members) != set(CONDITIONS):
            result["excluded_blocks"][block] = f"arms present: {sorted(members)}"
            continue
        outcomes = {c: arm_outcomes(members[c], directions) for c in CONDITIONS}
        starts_seen = {json.dumps(members[c]["revisions"][0]["controller"], sort_keys=True) for c in CONDITIONS}
        start_rewards = {round(outcomes[c]["start_reward"], 9) for c in CONDITIONS}
        if len(starts_seen) != 1 or len(start_rewards) != 1:
            result["excluded_blocks"][block] = "arms do not share an identical revision 0 (controller or flights)"
            continue
        if not all(o["complete"] for o in outcomes.values()):
            result["excluded_blocks"][block] = "incomplete: " + ", ".join(
                f"{c} {len(members[c]['revisions'])}/{NUM_REVISIONS}" for c in CONDITIONS)
            continue
        entry = {"start": start, "type": starts["starts"][start]["type"], "arms": outcomes,
                 "contrast_vs_no_feedback": {c: outcomes[c]["delta_final"] - outcomes["no_feedback"]["delta_final"]
                                             for c in CONDITIONS if c != "no_feedback"}}
        if search and start in search.get("starts", {}):
            entry["random_search"] = {k: search["starts"][start][f"{k}_summary"] for k in ("hill_climb", "random_walk")}
        result["blocks"][block] = entry
    result["summary"] = _summarize(result["blocks"], arms)
    return result


def _summarize(blocks_: Mapping[str, Any], arms: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    paid = sum(o["paid"] for b in blocks_.values() for o in b["arms"].values())
    valid = sum(o["valid_paid"] for b in blocks_.values() for o in b["arms"].values())
    summary: dict[str, Any] = {"complete_blocks": len(blocks_), "paid_proposals": paid, "valid_paid": valid,
                               "valid_fraction": valid / paid if paid else None,
                               "cost_usd": sum(a["cost_usd"] for a in arms), "arms": {}, "contrasts": {}}
    for c in CONDITIONS:
        deltas = [b["arms"][c]["delta_final"] for b in blocks_.values()]
        first = [b["arms"][c]["first_edit_alignment"] for b in blocks_.values() if b["arms"][c]["first_edit_alignment"] is not None]
        by_type = {kind: [b["arms"][c]["first_edit_alignment"] for b in blocks_.values()
                          if b["type"] == kind and b["arms"][c]["first_edit_alignment"] is not None] for kind in START_TYPES}
        rs_gap = [b["arms"][c]["delta_final"] - b["random_search"]["hill_climb"]["mean_delta"]
                  for b in blocks_.values() if "random_search" in b]
        summary["arms"][c] = {"mean_delta_final": _mean_or_none(deltas),
                              "mean_first_edit_alignment": _mean_or_none(first),
                              "first_edit_alignment_by_start_type": {k: _mean_or_none(v) for k, v in by_type.items()},
                              "mean_delta_minus_hill_climb": _mean_or_none(rs_gap),
                              "delta_minus_hill_climb_ci95": t_interval(rs_gap)}
    for c in CONDITIONS[1:]:
        diffs = [b["contrast_vs_no_feedback"][c] for b in blocks_.values()]
        align = [b["arms"][c]["first_edit_alignment"] - b["arms"]["no_feedback"]["first_edit_alignment"]
                 for b in blocks_.values() if b["arms"][c]["first_edit_alignment"] is not None
                 and b["arms"]["no_feedback"]["first_edit_alignment"] is not None]
        summary["contrasts"][f"{c}_minus_no_feedback"] = {
            "mean_delta_difference": _mean_or_none(diffs), "ci95": t_interval(diffs), "n": len(diffs),
            "mean_alignment_difference": _mean_or_none(align)}
    summary["pilot_go"] = pilot_go(summary)
    return summary


def pilot_go(summary: Mapping[str, Any]) -> dict[str, Any]:
    """The predeclared pilot rule (docs/STUDY_V3_PROTOCOL.md): G1 engineering and G2 signal."""
    g1 = summary["valid_fraction"] is not None and summary["valid_fraction"] >= 0.9
    signals = {}
    for c in CONDITIONS[1:]:
        contrast = summary["contrasts"][f"{c}_minus_no_feedback"]
        delta = contrast["mean_delta_difference"]
        align = contrast["mean_alignment_difference"]
        signals[c] = (delta is not None and delta >= 10.0) or (align is not None and align >= 0.25)
    return {"G1_valid_fraction_at_least_0.9": g1, "G2_signal_by_arm": signals,
            "go_to_study_tier": bool(g1 and any(signals.values()))}


# ---------------------------------------------------------------- rehearsal (scripted mock, free)


def rehearse(out: Path, *, tier: str = "pilot", base: Path = CONFIG_DIR, shorten: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Run the whole tier with the scripted mock model (real physics), then the analysis. Not LLM evidence."""
    from rewardbench.run.cli import main as run_main

    starts = load_starts()
    out.mkdir(parents=True, exist_ok=True)
    for start, replicate in blocks(tier, starts):
        for condition in CONDITIONS:
            data = yaml.safe_load(config_path(tier, condition, start, replicate, base).read_text(encoding="utf-8"))
            mock = study.rehearsal_config(data)
            mock["experiment_name"] = data["experiment_name"].replace("llmstudy3", "rehearsal3", 1)
            mock["budget"]["max_model_calls"] = NUM_REVISIONS * 2
            if shorten:
                mock.update(development_seeds=list(range(shorten["seeds"])), episodes_per_revision=shorten["seeds"],
                            max_episode_steps=shorten["steps"])
                mock["metadata"]["adapter_kwargs"]["max_steps"] = shorten["steps"]
            path = out / "configs" / f"{mock['experiment_name']}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(mock, sort_keys=False), encoding="utf-8")
            code = run_main(["--config", str(path), "--mode", "mock", "--database", str(out / f"{mock['experiment_name']}.sqlite")])
            if code != 0:
                raise RuntimeError(f"rehearsal of {path.name} exited {code}")
    return analyze(out, starts=starts)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.study_v3", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("starts", help="select the fixed starts from scripted flights (free)")
    p.add_argument("--out", type=Path, default=STARTS_FILE)
    p = sub.add_parser("random-search", help="matched scripted random-search references (free)")
    p.add_argument("--out", type=Path, default=SEARCH_FILE)
    p.add_argument("--replicates", type=int, default=SEARCH_REPLICATES)
    p = sub.add_parser("write-configs")
    p.add_argument("--check", action="store_true")
    sub.add_parser("budget")
    p = sub.add_parser("seed", help="fly revision 0 (the fixed start) of each arm offline; no network, no spend")
    p.add_argument("--config", action="append", required=True, type=Path)
    p = sub.add_parser("analyze")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--json", type=Path, default=None)
    p = sub.add_parser("rehearse")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--tier", choices=tuple(TIERS), default="pilot")
    args = parser.parse_args(argv)
    try:
        if args.command == "starts":
            data = build_starts()
            _write_json(args.out, data)
            for label, entry in data["starts"].items():
                print(f"{label}: pool #{entry['pool_index']} {entry['outcome']}")
        elif args.command == "random-search":
            data = build_random_search(load_starts(), replicates=args.replicates)
            _write_json(args.out, data)
            for label, kinds in data["starts"].items():
                print(label, {k: v for k, v in kinds.items() if k.endswith("_summary")})
        elif args.command == "write-configs":
            for path in write_configs(check=args.check):
                print(("ok " if args.check else "wrote ") + str(path))
        elif args.command == "budget":
            print(json.dumps(price(), indent=2))
        elif args.command == "seed":
            for path in args.config:
                print(json.dumps({"config": str(path), **seed(path)}))
        elif args.command == "analyze":
            data = analyze(args.out)
            if args.json:
                _write_json(args.json, data)
            print(json.dumps(data["summary"], indent=2))
        elif args.command == "rehearse":
            print(json.dumps(rehearse(args.out, tier=args.tier)["summary"], indent=2))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
