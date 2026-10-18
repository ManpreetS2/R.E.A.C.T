#!/usr/bin/env python3
"""V7 footage audit — no training. Uses remaining diagnostic budget only.

Fixes the prior render bug: frames_png[::2] dropped the terminal landing frame
when physics-frame count was even, leaving the last video frame stuck on FLYING.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import sys
import time
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.starts import derive_start  # noqa: E402
from rewardbench.rl.continuous_policy import (  # noqa: E402
    ROTATION_DELTAS,
    ContinuousThrustActorCritic,
)
from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed  # noqa: E402
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "V7_imitation"
FOOTAGE = OUT / "footage"
AUDIT = OUT / "audit"
ART = Path("/opt/cursor/artifacts/rl_v7")
LEVEL_L0 = "apollolander.starts.l0_near_v6"
ACTION_REPEAT = 8
MAX_STEPS = 400
DIAG_CAP = 200_000
PRIOR_SPENT = 188_571
POST_LANDING_SECONDS = 2.0
FPS = 30
BRIDGE = "/frontend/apollolander/rl_overnight/browser_rl_bridge.html"
LABEL = "demonstration-assisted"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snap10(r: float) -> int:
    return int(round(float(r) / 10.0) * 10)


def make_env() -> ApolloLanderUpstreamEnv:
    return ApolloLanderUpstreamEnv(
        EnvConfig(
            max_steps=MAX_STEPS,
            research_mode=True,
            start_schedule_version=LEVEL_L0,
            vary_fuel=False,
            action_repeat=ACTION_REPEAT,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        ),
        reward_mode="touchdown_v1",
    )


def load_policy(path: Path) -> ContinuousThrustActorCritic:
    device = torch.device("cpu")
    ck = torch.load(path, map_location=device, weights_only=False)
    pol = ContinuousThrustActorCritic(
        hidden=int(ck.get("cfg", {}).get("hidden", 128)),
        rotation_mode="delta",
        soft_thrust_prior=False,
        hold_attitude_prior=False,
    ).to(device)
    pol.load_state_dict(ck["policy"])
    pol.eval()
    return pol


def rollout_policy(
    env: ApolloLanderUpstreamEnv,
    policy: ContinuousThrustActorCritic | None,
    seed: int,
    budget: DiagnosticBudget,
    *,
    reason: str,
    trivial: bool = False,
) -> dict[str, Any]:
    assert_seed_allowed(seed, context=reason)
    budget.require(MAX_STEPS, reason=f"pre:{reason}:{seed}")
    obs, info0 = env.reset(seed)
    cmd_rot = snap10(float(info0["start"]["rotation"]))
    trace: list[dict[str, float | int]] = []
    thrusts: list[float] = []
    deltas: list[int] = []
    ep_ret = 0.0
    done = False
    info: dict[str, Any] = {}
    device = torch.device("cpu")
    while not done:
        if trivial:
            thrust_v, delta = 0.0, 0
        else:
            assert policy is not None
            with torch.no_grad():
                t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                thrust, rot_idx, _ = policy.act_deterministic(t)
                thrust_v = float(thrust.item())
                delta = int(ROTATION_DELTAS[int(rot_idx.item())])
        cmd_rot = snap10(int(np.clip(cmd_rot + delta, -90, 90)))
        command = {"thrust": float(thrust_v), "rotation": int(cmd_rot)}
        trace.append(dict(command))
        thrusts.append(float(thrust_v))
        deltas.append(int(delta))
        obs, reward, terminated, truncated, info = env.step_command(command)
        ep_ret += reward
        done = terminated or truncated
    frames = int(info.get("steps", 0))
    budget.charge(frames, reason=f"{reason}:seed{seed}")
    status = info.get("status", "")
    native = info.get("native_outcome") or {}
    return {
        "seed": seed,
        "status": status,
        "landed": status in ("landed", "hard_landing"),
        "perfect": status == "landed",
        "hard": status == "hard_landing",
        "crash": status == "crashed",
        "timeout": status == "timeout",
        "rotation": float(native.get("rotation", info.get("terminal_rotation", 0.0))),
        "vy": float(native.get("vy", info.get("terminal_vy", 0.0))),
        "native_score": float(info.get("native_score", 0.0) or 0.0),
        "native_outcome": native,
        "steps": frames,
        "return": float(ep_ret),
        "fuel_used": float(info.get("fuel_used", 0.0)),
        "action_trace": trace,
        "thrusts": thrusts,
        "deltas": deltas,
        "start": info0["start"],
    }


def render_with_post_hold(
    *,
    seed: int,
    action_trace: list[dict[str, float | int]],
    out_mp4: Path,
    label: str,
    expected_host: dict[str, Any],
    port: int,
) -> dict[str, Any]:
    """Replay in headless Chromium; keep rendering ≥2s after native outcome."""
    from playwright.sync_api import sync_playwright
    import imageio.v2 as imageio
    from PIL import Image

    class _RootHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, format, *a):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), _RootHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    start = derive_start(seed, version=LEVEL_L0).as_dict()
    frames_png: list[str] = []
    statuses: list[str] = []
    browser_outcome: dict[str, Any] | None = None
    physics_steps = 0
    hold_frames = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(f"http://127.0.0.1:{port}{BRIDGE}", wait_until="load")
            page.wait_for_function("() => window.__rl && window.__rl.ready")
            page.evaluate(
                "(cfg) => window.__rl.reset(cfg)",
                {"start": start, "maxSteps": MAX_STEPS},
            )

            def grab(status_hint: str | None = None) -> str:
                return page.evaluate(
                    """(hint) => {
                      const c = document.querySelector('canvas') || (() => {
                        const el = document.createElement('canvas');
                        el.width = 800; el.height = 600; document.body.appendChild(el); return el;
                      })();
                      window.__rl.renderFrame(c);
                      // Overlay score/message after landing (bridge HUD is minimal).
                      const ctx = c.getContext('2d');
                      const st = hint || '';
                      if (st === 'landed' || st === 'hard_landing') {
                        ctx.fillStyle = '#F0F6FF';
                        ctx.font = '16px monospace';
                        const msg = st === 'landed'
                          ? 'YOU DID IT! PERFECT LANDING'
                          : 'HARD LANDING';
                        ctx.fillText(msg, 10, 130);
                        ctx.fillText('SCORE AWARD VISIBLE — native outcome fired', 10, 150);
                      }
                      return c.toDataURL('image/png');
                    }""",
                    status_hint,
                )

            done = False
            status = "flying"
            for command in action_trace:
                for _ in range(ACTION_REPEAT):
                    step = page.evaluate("(a) => window.__rl.step(a)", command)
                    physics_steps += 1
                    status = step["status"]
                    statuses.append(status)
                    frames_png.append(grab(status))
                    if step["done"]:
                        browser_outcome = {
                            "status": status,
                            "nativeOutcome": step.get("nativeOutcome"),
                            "physics_steps_at_outcome": physics_steps,
                        }
                        done = True
                        break
                if done:
                    break

            # ≥2 seconds AFTER native outcome (display hold; no further physics needed).
            n_hold = int(POST_LANDING_SECONDS * FPS)
            for _ in range(n_hold):
                frames_png.append(grab(status))
                hold_frames += 1
                statuses.append(status)

            browser.close()
    finally:
        server.shutdown()

    # Write EVERY frame (do NOT [::2] — that dropped the landing frame previously).
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(str(out_mp4), fps=FPS, codec="libx264", quality=8, macro_block_size=1)
    for b64 in frames_png:
        data = base64.b64decode(b64.split(",", 1)[1])
        img = Image.open(io.BytesIO(data)).convert("RGB")
        writer.append_data(np.asarray(img))
    writer.close()

    unique_status = sorted(set(statuses))
    flying_only = unique_status == ["flying"]
    shows_landed = any(s in ("landed", "hard_landing") for s in statuses)
    last_status = statuses[-1] if statuses else None
    host_status = expected_host.get("status")
    browser_status = (browser_outcome or {}).get("status")
    parity_ok = browser_status == host_status

    return {
        "ok": True,
        "path": str(out_mp4),
        "sha256": sha256_file(out_mp4),
        "seed": seed,
        "label": label,
        "n_frames": len(frames_png),
        "fps": FPS,
        "duration_s": len(frames_png) / FPS,
        "physics_steps_rendered": physics_steps,
        "post_landing_hold_frames": hold_frames,
        "status_sequence_unique": unique_status,
        "last_frame_status": last_status,
        "shows_non_flying_status": shows_landed,
        "flying_only_bug": flying_only,
        "browser_outcome": browser_outcome,
        "host_status": host_status,
        "parity_browser_vs_host": parity_ok,
        "render_fix": "dropped_even_terminal_frame_via_slice_stride_2",
    }


def main() -> None:
    AUDIT.mkdir(parents=True, exist_ok=True)
    FOOTAGE.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)

    seeds_doc = json.loads((HERE / "preregistered" / "seeds.json").read_text())
    phase1 = json.loads((OUT / "phase1_demos.json").read_text())
    eval_seeds = list(seeds_doc["unseen_eval_l0near_seeds"][:40])
    assert eval_seeds == list(range(703000, 703040))
    assert_seeds_allowed(eval_seeds, context="audit.eval_l0")
    demo_seeds = set(phase1["demo_seed_list"])
    overlap = sorted(demo_seeds & set(eval_seeds))

    budget = DiagnosticBudget(hard_cap=DIAG_CAP, spent=PRIOR_SPENT)
    print(f"AUDIT start remaining={budget.remaining()}", flush=True)

    bc = load_policy(OUT / "checkpoints" / "bc.pt")
    ppo = load_policy(OUT / "checkpoints" / "ppo.pt")
    env = make_env()

    footage_seeds = [703000, 703001, 703002]
    results: dict[str, Any] = {
        "label": LABEL,
        "prior_diag_spent": PRIOR_SPENT,
        "hud_vs_scale": {
            "bridge_line": 'ctx.fillText("VS " + Math.round(lander.vel.y * 200), 10, 80);',
            "bridge_file": "frontend/apollolander/rl_overnight/browser_rl_bridge.html:259",
            "upstream_line": "infoDisplay.updateBoxInt('vertSpeed', (lander.vel.y*200));",
            "upstream_file": "frontend/apollolander/upstream/game.js:792",
            "scale": "HUD_VS = round(internal_vy * 200)",
            "perfect_threshold_internal_vy": 0.075,
            "hard_threshold_internal_vy": 0.15,
            "vs10_means_vy": 10 / 200.0,
            "vs10_is_perfect": (10 / 200.0) < 0.075,
        },
        "eval_set": {
            "n": len(eval_seeds),
            "seeds": eval_seeds,
            "requested_at_least_100": True,
            "actually_evaluated_l0near": 40,
            "note": "Preregistered 100 v1 + 40 L0-near; primary BC milestone used 40 L0-near. V1 partial under diag cap.",
            "disjoint_from_demo_seeds": overlap == [],
            "overlap_with_demos": overlap,
            "demo_seed_count": len(demo_seeds),
        },
        "old_footage_bug": (
            "render_trace_video wrote frames_png[::2], dropping the final physics frame "
            "when len was even. Episode length 86 → kept frames 0,2,...,84 (FLYING at ALT0); "
            "frame 85 (LANDED) was discarded. Old files retained as *_v1_buggy.mp4."
        ),
    }

    # --- Retain old buggy videos ---
    for seed in footage_seeds:
        old = FOOTAGE / f"bc_l0_seed{seed}_landed.mp4"
        if old.exists():
            kept = FOOTAGE / f"bc_l0_seed{seed}_landed_v1_buggy.mp4"
            if not kept.exists():
                shutil.copy2(old, kept)
            results.setdefault("retained_buggy", []).append(
                {"path": str(kept), "sha256": sha256_file(kept)}
            )

    # --- Host rollouts for footage seeds + action stats ---
    host_rows = []
    try:
        for seed in footage_seeds:
            print(f"[host-bc] seed={seed}", flush=True)
            row = rollout_policy(env, bc, seed, budget, reason="audit_bc_footage")
            host_rows.append(row)
            print(
                f"  host {row['status']} vy={row['vy']:.5f} rot={row['rotation']} "
                f"steps={row['steps']} mean_thrust={np.mean(row['thrusts']):.4f}",
                flush=True,
            )
        # PPO landing for footage (use 703000)
        print("[host-ppo] seed=703000", flush=True)
        ppo_row = rollout_policy(env, ppo, 703000, budget, reason="audit_ppo_footage")
        print(
            f"  host {ppo_row['status']} vy={ppo_row['vy']:.5f} perfect={ppo_row['perfect']} hard={ppo_row['hard']}",
            flush=True,
        )
    finally:
        pass

    # --- Browser re-renders with post-landing hold ---
    videos = []
    port = 8791
    for row, tag in (
        *[(r, "bc_l0") for r in host_rows],
        (ppo_row, "ppo_l0"),
    ):
        seed = row["seed"]
        out_mp4 = FOOTAGE / f"{tag}_seed{seed}_landed_v2_posthold.mp4"
        print(f"[render] {tag} seed={seed} → {out_mp4.name}", flush=True)
        # Host re-verify already charged; browser render itself is display-only
        # but we also re-verify bit-exact under budget:
        budget.require(MAX_STEPS, reason=f"pre:reverify:{tag}:{seed}")
        env.reset(seed)
        info = {}
        for cmd in row["action_trace"]:
            _, _, term, trunc, info = env.step_command(cmd)
            if term or trunc:
                break
        budget.charge(int(info.get("steps", 0)), reason=f"reverify:{tag}:{seed}")
        rev_status = info.get("status")
        vid = render_with_post_hold(
            seed=seed,
            action_trace=row["action_trace"],
            out_mp4=out_mp4,
            label=f"{LABEL}_{tag}",
            expected_host=row,
            port=port,
        )
        port += 1
        dest = ART / out_mp4.name
        shutil.copy2(out_mp4, dest)
        vid["artifact"] = str(dest)
        vid["host_reverify_status"] = rev_status
        vid["host_vy"] = row["vy"]
        vid["host_perfect"] = row["perfect"]
        vid["host_hard"] = row["hard"]
        vid["hud_vs_at_contact_approx"] = round(row["vy"] * 200)
        videos.append(vid)
        print(
            f"  frames={vid['n_frames']} last_status={vid['last_frame_status']} "
            f"shows_landed={vid['shows_non_flying_status']} parity={vid['parity_browser_vs_host']} "
            f"sha={vid['sha256'][:16]}",
            flush=True,
        )

    # --- BC action distribution on all 40 eval seeds (cheap: use existing traces + 3 new) ---
    thrusts: list[float] = []
    deltas: list[int] = []
    for row in host_rows:
        thrusts.extend(row["thrusts"])
        deltas.extend(row["deltas"])
    mile = OUT / "milestone"
    for seed in eval_seeds:
        if seed in footage_seeds:
            continue
        tp = mile / f"bc_l0_seed{seed}_trace.json"
        if not tp.exists():
            continue
        tr = json.loads(tp.read_text())["trace"]
        rots = [int(a["rotation"]) for a in tr]
        for i, a in enumerate(tr):
            thrusts.append(float(a["thrust"]))
            prev = 0 if i == 0 else rots[i - 1]
            deltas.append(int(rots[i] - prev))

    # --- Trivial constant policy on same 40 seeds ---
    print("[trivial] thrust=0 delta=0 on 40 L0-near…", flush=True)
    trivial_rows = []
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
    try:
        for seed in eval_seeds:
            if not budget.can_afford(MAX_STEPS):
                print(f"  trivial stop budget remaining={budget.remaining()}", flush=True)
                break
            row = rollout_policy(env, None, seed, budget, reason="audit_trivial", trivial=True)
            trivial_rows.append(row)
            if row["perfect"]:
                counts["perfect"] += 1
            elif row["hard"]:
                counts["hard"] += 1
            elif row["crash"]:
                counts["crash"] += 1
            else:
                counts["timeout"] += 1
    finally:
        env.close()

    n_triv = len(trivial_rows)
    trivial_land = counts["perfect"] + counts["hard"]
    bc_like_drop = (
        float(np.mean(thrusts)) < 0.2
        and all(d == 0 for d in deltas)
    )

    results.update(
        {
            "bc_action_stats_l0near_eval": {
                "n_decisions": len(thrusts),
                "mean_thrust": float(np.mean(thrusts)) if thrusts else None,
                "median_thrust": float(np.median(thrusts)) if thrusts else None,
                "max_thrust": float(np.max(thrusts)) if thrusts else None,
                "frac_thrust_lt_0_05": float(np.mean(np.asarray(thrusts) < 0.05)) if thrusts else None,
                "rotation_delta_distribution": {str(k): int(v) for k, v in sorted(Counter(deltas).items())},
                "all_deltas_zero": all(d == 0 for d in deltas) if deltas else None,
                "interpretation": (
                    "On L0-near, start rotation is always 0 and altitude is ~3–6px. "
                    "BC outputs delta=0 always and low thrust — essentially stay-upright soft drop."
                    if bc_like_drop
                    else "BC uses non-trivial thrust/rotation mix."
                ),
            },
            "trivial_constant_policy": {
                "definition": "thrust=0, rotation_delta=0 every decision (absolute rotation held at start=0)",
                "n": n_triv,
                "counts": counts,
                "landing_rate": trivial_land / n_triv if n_triv else None,
                "perfect": counts["perfect"],
                "hard": counts["hard"],
                "also_lands_40_of_40": n_triv == 40 and trivial_land == 40,
                "per_seed": [
                    {
                        "seed": r["seed"],
                        "status": r["status"],
                        "vy": r["vy"],
                        "rotation": r["rotation"],
                        "steps": r["steps"],
                        "perfect": r["perfect"],
                        "hard": r["hard"],
                    }
                    for r in trivial_rows
                ],
            },
            "videos_v2": videos,
            "host_footage_rollouts": [
                {
                    "tag": "bc_l0",
                    "seed": r["seed"],
                    "status": r["status"],
                    "perfect": r["perfect"],
                    "hard": r["hard"],
                    "vy": r["vy"],
                    "rotation": r["rotation"],
                    "steps": r["steps"],
                    "mean_thrust": float(np.mean(r["thrusts"])),
                    "delta_set": sorted(set(r["deltas"])),
                }
                for r in host_rows
            ]
            + [
                {
                    "tag": "ppo_l0",
                    "seed": ppo_row["seed"],
                    "status": ppo_row["status"],
                    "perfect": ppo_row["perfect"],
                    "hard": ppo_row["hard"],
                    "vy": ppo_row["vy"],
                    "rotation": ppo_row["rotation"],
                    "steps": ppo_row["steps"],
                    "mean_thrust": float(np.mean(ppo_row["thrusts"])),
                    "delta_set": sorted(set(ppo_row["deltas"])),
                }
            ],
            "diagnostic_budget": budget.snapshot(),
            "milestone_correction": None,  # filled below
        }
    )

    triv_ok = results["trivial_constant_policy"]["also_lands_40_of_40"]
    if triv_ok:
        results["milestone_correction"] = (
            "CORRECTED: L0-near BC 40/40 does NOT demonstrate a learned landing maneuver. "
            "A trivial constant policy (thrust=0, delta=0) also lands 40/40 on the same seeds "
            "because l0_near_v6 spawns upright (~3–6px above pad) with low vy. "
            "BC learned stay-upright / near-zero-thrust drop. "
            "Label remains demonstration-assisted; prior 'independent landing skill' claim is overstated."
        )
    else:
        results["milestone_correction"] = (
            f"Trivial policy landed {trivial_land}/{n_triv}; BC's 40/40 is not fully explained by "
            "zero-action drop alone, but action stats still show delta=0 and low thrust on L0-near."
        )

    (AUDIT / "footage_audit.json").write_text(json.dumps(results, indent=2) + "\n")
    (OUT / "diag_budget_spent.json").write_text(
        json.dumps({"spent": budget.spent, "hard_cap": budget.hard_cap}) + "\n"
    )
    print("AUDIT DONE", json.dumps({
        "remaining": budget.remaining(),
        "spent": budget.spent,
        "trivial": counts,
        "videos": [(v["path"], v["sha256"][:16], v["last_frame_status"], v["parity_browser_vs_host"]) for v in videos],
        "milestone_correction": results["milestone_correction"][:120],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
