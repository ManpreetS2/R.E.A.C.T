"""Development-only ApolloLander research-mode baseline benchmark.

Scripted controllers only. This is not an LLM experiment and does not use
held-out seeds. Results inform whether apollolander.starts.v1 is a credible
first pilot distribution.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from rewardbench.environments.apollolander import (
    ENVIRONMENT_VERSION,
    ORIGIN_DETERMINISTIC_MOCK,
    ORIGIN_HAND_SPECIFIED,
    START_SCHEDULE_VERSION,
    ApolloLanderAdapter,
    assert_schedules_disjoint,
    constant_controller,
    demonstration_guidance_controller,
    derive_start,
    development_start_catalog,
    held_out_start_catalog,
    random_controller,
)
from rewardbench.environments.lunarlander.seeds import HELD_OUT_SEED_START, validate_seed_split

# Documented development evaluation set for this report. Held-out seeds are
# never evaluated here.
DEVELOPMENT_BASELINE_SEEDS: tuple[int, ...] = tuple(range(16))
MAX_STEPS = 8000
# Videos and per-episode manifests stay under output/ (gitignored).
OUTPUT = Path(__file__).resolve().parent / "output" / "research_development_baseline"
# Compact report artifacts are committed next to this script.
REPORT_DIR = Path(__file__).resolve().parent / "research_development_baseline"
REPORT_MD = REPORT_DIR / "DEVELOPMENT_BASELINE_REPORT.md"
REPORT_JSON = REPORT_DIR / "development_baseline_results.json"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    validate_seed_split(DEVELOPMENT_BASELINE_SEEDS, "development")
    if any(seed >= HELD_OUT_SEED_START for seed in DEVELOPMENT_BASELINE_SEEDS):
        raise RuntimeError("development baseline accidentally included held-out seeds")
    assert_schedules_disjoint(development_start_catalog(64), held_out_start_catalog(64))

    research = ApolloLanderAdapter(research_mode=True, max_steps=MAX_STEPS)
    fixed = ApolloLanderAdapter(research_mode=False, max_steps=MAX_STEPS)

    starts = {
        str(seed): derive_start(seed, version=START_SCHEDULE_VERSION).as_dict()
        for seed in DEVELOPMENT_BASELINE_SEEDS
    }

    baselines: list[dict[str, Any]] = [
        {
            "name": "random_seed0",
            "controller": random_controller(0),
            "origin": ORIGIN_DETERMINISTIC_MOCK,
            "model": "baseline-random-0",
            "note": "Deterministic pseudo-random open-loop baseline.",
        },
        {
            "name": "constant_coast",
            "controller": constant_controller(0, -90),
            "origin": ORIGIN_DETERMINISTIC_MOCK,
            "model": "baseline-constant-coast",
            "note": "Zero thrust, nose left; expected crash/timeout floor.",
        },
        {
            "name": "constant_hover_upright",
            "controller": constant_controller(0.333, 0),
            "origin": ORIGIN_DETERMINISTIC_MOCK,
            "model": "baseline-constant-hover",
            "note": "Near-hover thrust, upright; weak scripted control.",
        },
        {
            "name": "hand_specified_guidance",
            "controller": demonstration_guidance_controller(),
            "origin": ORIGIN_HAND_SPECIFIED,
            "model": "hand-specified-guidance",
            "note": "Tuned on the fixed demonstration start; not an LLM.",
        },
    ]

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for baseline in baselines:
        print(f"running {baseline['name']} on {len(DEVELOPMENT_BASELINE_SEEDS)} development seeds…", flush=True)
        record_seeds = [DEVELOPMENT_BASELINE_SEEDS[0]]
        report = research.evaluate(
            baseline["controller"],
            DEVELOPMENT_BASELINE_SEEDS,
            revision=1,
            split="development",
            origin=baseline["origin"],
            model=baseline["model"],
            max_steps=MAX_STEPS,
            record_dir=OUTPUT,
            record_video=True,
            video_seeds=record_seeds,
        )
        summary = _summarize(baseline["name"], report, note=baseline["note"])
        # Replay-verify the recorded seed.
        episode0 = report["episodes"][0]
        verify = research.verify_flight_record(episode0["flight_record_path"])
        summary["replay_verified"] = verify["matched"]
        summary["replay_mismatches"] = verify["mismatches"]
        summary["sample_flight_record_path"] = episode0.get("flight_record_path")
        summary["sample_video_path"] = episode0.get("video_path")
        summary["sample_trace_hash"] = episode0.get("trace_hash")
        summary["autonomous_learning"] = report["autonomous_learning"]
        summary["origin"] = report["origin"]
        results.append(summary)
        print(
            f"  land={summary['landing_rate']:.3f} crash={summary['crash_rate']:.3f} "
            f"timeout={summary['timeout_rate']:.3f} mean_r={summary['mean_reward']:.2f} "
            f"replay_ok={verify['matched']}",
            flush=True,
        )

    print("running fixed-start guidance control (single seed, not research)…", flush=True)
    fixed_report = fixed.evaluate(
        demonstration_guidance_controller(),
        [0],
        revision=1,
        split="development",
        origin=ORIGIN_HAND_SPECIFIED,
        model="hand-specified-guidance-fixed",
        max_steps=MAX_STEPS,
        record_dir=OUTPUT,
        record_video=True,
    )
    fixed_summary = _summarize("hand_specified_guidance_fixed_start", fixed_report, note="Control: same guidance on the original fixed spawn.")
    fixed_ep = fixed_report["episodes"][0]
    fixed_verify = fixed.verify_flight_record(fixed_ep["flight_record_path"])
    fixed_summary["replay_verified"] = fixed_verify["matched"]
    fixed_summary["replay_mismatches"] = fixed_verify["mismatches"]
    fixed_summary["sample_flight_record_path"] = fixed_ep.get("flight_record_path")
    fixed_summary["sample_video_path"] = fixed_ep.get("video_path")
    fixed_summary["mode"] = "fixed_start"

    # Reproducibility spot-check: two independent research runs on one seed.
    ctrl = constant_controller(0.2, -80)
    a = research.evaluate(ctrl, [7], revision=1, split="development", origin=ORIGIN_DETERMINISTIC_MOCK, model="repro-a", max_steps=120)
    b = research.evaluate(ctrl, [7], revision=1, split="development", origin=ORIGIN_DETERMINISTIC_MOCK, model="repro-b", max_steps=120)
    repro = {
        "seed": 7,
        "starts_equal": a["episodes"][0]["start"] == b["episodes"][0]["start"],
        "rewards_equal": a["episodes"][0]["reward"] == b["episodes"][0]["reward"],
        "trace_hashes_equal": a["episodes"][0]["trace_hash"] == b["episodes"][0]["trace_hash"],
        "model_names_differ": a["episodes"][0]["model"] != b["episodes"][0]["model"],
    }

    elapsed = time.perf_counter() - started
    assessment = _assess(results, fixed_summary)
    payload = {
        "title": "ApolloLander research-mode development baseline",
        "schedule_version": START_SCHEDULE_VERSION,
        "environment_version": ENVIRONMENT_VERSION,
        "split": "development",
        "held_out_seeds_used": False,
        "development_seeds": list(DEVELOPMENT_BASELINE_SEEDS),
        "max_steps": MAX_STEPS,
        "starts": starts,
        "baselines": results,
        "fixed_start_control": fixed_summary,
        "reproducibility_spot_check": repro,
        "assessment": assessment,
        "elapsed_seconds": elapsed,
        "autonomous_learning": False,
        "note": "All controllers are scripted baselines. None are evidence of in-context learning.",
    }
    REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(_markdown(payload), encoding="utf-8")
    print(REPORT_JSON)
    print(REPORT_MD)
    print(json.dumps(assessment, indent=2))


def _summarize(name: str, report: dict[str, Any], *, note: str) -> dict[str, Any]:
    episodes = report["episodes"]
    n = len(episodes)
    landed = sum(1 for ep in episodes if ep["landed"])
    crashed = sum(1 for ep in episodes if ep["crashed"])
    timed_out = sum(1 for ep in episodes if ep["timed_out"])
    rewards = [float(ep["reward"]) for ep in episodes]
    fuels = [float(ep["fuel_used"]) for ep in episodes]
    steps = [int(ep["steps"]) for ep in episodes]
    touchdowns = []
    for ep in episodes:
        verified = ep.get("verified") or {}
        if ep["landed"] and isinstance(verified, dict):
            touchdowns.append(
                {
                    "seed": ep["seed"],
                    "vy": verified.get("vy"),
                    "rotation": verified.get("rotation"),
                    "perfect": verified.get("perfect"),
                    "designated": verified.get("designated"),
                }
            )
    return {
        "name": name,
        "mode": "research",
        "note": note,
        "n_episodes": n,
        "landing_count": landed,
        "crash_count": crashed,
        "timeout_count": timed_out,
        "landing_rate": landed / n,
        "crash_rate": crashed / n,
        "timeout_rate": timed_out / n,
        "mean_reward": statistics.fmean(rewards),
        "reward_stdev": statistics.pstdev(rewards) if n > 1 else 0.0,
        "mean_fuel_used": statistics.fmean(fuels),
        "mean_steps": statistics.fmean(steps),
        "touchdowns": touchdowns,
        "episode_status": [
            {
                "seed": ep["seed"],
                "status": ep["status"],
                "reward": ep["reward"],
                "fuel_used": ep["fuel_used"],
                "steps": ep["steps"],
                "start": ep["start"],
                "trace_hash": ep["trace_hash"],
                "controller_hash": ep["controller_hash"],
            }
            for ep in episodes
        ],
    }


def _assess(results: list[dict[str, Any]], fixed: dict[str, Any]) -> dict[str, Any]:
    by_name = {item["name"]: item for item in results}
    guidance = by_name["hand_specified_guidance"]
    random_b = by_name["random_seed0"]
    coast = by_name["constant_coast"]
    fixed_lands = fixed["landing_rate"] >= 1.0 - 1e-9

    if guidance["landing_rate"] >= 0.25:
        difficulty = "achievable_with_current_guidance"
        rationale = (
            f"Hand-specified guidance verified landing rate on development research "
            f"starts is {guidance['landing_rate']:.3f} (mean reward "
            f"{guidance['mean_reward']:.2f}). Weak scripted baselines do not land. "
            "A first LLM pilot on apollolander.starts.v1 is credible; no easier tier "
            "is required from this evidence."
        )
        recommend_tier = None
    elif guidance["landing_rate"] > 0 and fixed_lands:
        difficulty = "hard_guidance_overfit_to_fixed_start"
        rationale = (
            "Guidance still lands on the fixed demonstration start but only rarely "
            "(or sparsely) under research starts. The controller is over-fit to the "
            "fixed spawn more than the distribution is proven impossible."
        )
        recommend_tier = "optional_future_apollolander.starts.v2_narrower_dx_rotation"
    elif fixed_lands and guidance["landing_rate"] == 0:
        difficulty = "no_research_landing_with_fixed_tuned_guidance"
        rationale = (
            "Guidance succeeds on the fixed start but never on the development research "
            "set. Likely over-fit to the demonstration spawn; does not prove the task is "
            "impossible for a better controller. Consider a documented easier schedule "
            "version for a first pilot while keeping v1 for later stress tests."
        )
        recommend_tier = "propose_apollolander.starts.v2_pilot_easier_without_replacing_v1"
    else:
        difficulty = "inconclusive"
        rationale = (
            "Baselines did not establish a clear achievable floor; more scripted "
            "controllers or a narrower documented seed subset may be needed before a "
            "paid LLM pilot."
        )
        recommend_tier = None

    return {
        "difficulty": difficulty,
        "rationale": rationale,
        "recommended_difficulty_tier": recommend_tier,
        "v1_schedule_unchanged": True,
        "fixed_start_guidance_lands": fixed_lands,
        "research_guidance_landing_rate": guidance["landing_rate"],
        "research_random_landing_rate": random_b["landing_rate"],
        "research_coast_crash_or_timeout_rate": coast["crash_rate"] + coast["timeout_rate"],
        "pilot_seeds_suggestion": list(DEVELOPMENT_BASELINE_SEEDS[:8]),
        "pilot_note": (
            "Use the same eight development seeds as research_development_numerical.yaml "
            "for a matched first LLM pilot; keep held-out seeds sealed."
        ),
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# ApolloLander research-mode — development baseline report",
        "",
        "Scripted baselines only. Not an LLM result. Held-out seeds were not used.",
        "",
        f"- Schedule: `{payload['schedule_version']}`",
        f"- Environment: `{payload['environment_version']}`",
        f"- Development seeds: `{payload['development_seeds']}`",
        f"- Max steps: {payload['max_steps']}",
        f"- Held-out used: `{payload['held_out_seeds_used']}`",
        "",
        "## Summary table",
        "",
        "| Baseline | Land % | Crash % | Timeout % | Mean reward | Mean fuel | Replay OK |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload["baselines"]:
        lines.append(
            f"| {item['name']} | {100*item['landing_rate']:.1f} | {100*item['crash_rate']:.1f} | "
            f"{100*item['timeout_rate']:.1f} | {item['mean_reward']:.2f} | {item['mean_fuel_used']:.1f} | "
            f"{item['replay_verified']} |"
        )
    fixed = payload["fixed_start_control"]
    lines.extend(
        [
            "",
            "## Fixed-start control",
            "",
            f"Hand-specified guidance on the original spawn: land={fixed['landing_rate']}, "
            f"status episodes={fixed['episode_status']}, replay_ok={fixed['replay_verified']}.",
            "",
            "## Assessment",
            "",
            f"- Difficulty: **{payload['assessment']['difficulty']}**",
            f"- {payload['assessment']['rationale']}",
            f"- Recommended tier proposal: `{payload['assessment']['recommended_difficulty_tier']}`",
            f"- v1 schedule left unchanged: `{payload['assessment']['v1_schedule_unchanged']}`",
            f"- Suggested pilot seeds: `{payload['assessment']['pilot_seeds_suggestion']}`",
            "",
            "## Reproducibility spot-check",
            "",
            "```json",
            json.dumps(payload["reproducibility_spot_check"], indent=2),
            "```",
            "",
            "## Provenance",
            "",
            "Origins are `hand_specified_demonstration` or `deterministic_mock`. "
            "`autonomous_learning` is false for every baseline.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
