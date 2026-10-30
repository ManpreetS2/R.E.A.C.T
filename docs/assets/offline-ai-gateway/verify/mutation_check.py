"""Do the browser-free tests actually catch a broken safety rule? Break each rule in a throwaway copy and find out.

Each mutation removes or weakens one guard. A mutation that no test notices would mean that guard is not really covered.
The copy lives in a temporary directory; the checkout is never modified. No provider exists to call, so this costs nothing.

    python docs/assets/offline-ai-gateway/verify/mutation_check.py <repo> <report.json>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GATEWAY, LEDGER, CONTRACT, HOST = "model_gateway.py", "spend_ledger.py", "contract.py", "host.py"

# (name, file, exact text, replacement)
MUTATIONS = [
    ("live calls enabled", GATEWAY, "LIVE_CALLS_PERMITTED = False", "LIVE_CALLS_PERMITTED = True"),
    ("non-offline transport accepted", GATEWAY, 'if not getattr(transport, "is_offline", False) and not LIVE_CALLS_PERMITTED:', "if False:"),
    ("budget refusal ignored (call goes out without a reservation)", GATEWAY,
     'raise self.stop(f"budget_exhausted_{exc.scope}") from None', 'reservation = "unreserved"'),
    ("image window off by one", GATEWAY, 'keep = set(sorted(self._images)[-self.config.max_images_per_call:])',
     'keep = set(sorted(self._images)[-(self.config.max_images_per_call + 1):])'),
    ("outbound image guard removed", GATEWAY, 'if len(images) > self.config.max_images_per_call:', "if False:"),
    ("game accepts actions the model never made", GATEWAY, "if entry.canonical != (tool, act):", "if False:"),
    ("next turn allowed with calls pending", GATEWAY, "if self._next_executable() is not None and not self._batch_closed:", "if False:"),
    ("hallucinated tools accepted", GATEWAY, 'if not isinstance(name, str) or name not in {t["name"] for t in self.tools}:', "if False:"),
    ("extra tool-call arguments accepted", GATEWAY, "if set(arguments) - allowed:", "if False:"),
    ("too many tool calls accepted", GATEWAY, "if accepted >= self.config.max_tool_calls_per_reply:", "if False:"),
    ("cut-off replies executed", GATEWAY, 'if stop == "max_tokens":', "if False:"),
    ("screenshot hash not checked", GATEWAY, 'if hashlib.sha256(png).hexdigest() != image["sha256"]:', "if False:"),
    ("PNG CRC not checked", GATEWAY, 'or zlib.crc32(png[pos + 4:pos + 8 + length]) != int.from_bytes(png[pos + 8 + length:end], "big"):', ":"),
    ("extra game fields forwarded", GATEWAY, "if fields != contract.OBSERVATION_FIELDS:", "if False:"),
    ("refusal not treated as the end", GATEWAY, 'if reply.stop == "refusal":', "if False:"),
    ("wrong model accepted", GATEWAY, "if reply.model != self.config.model_id:", "if False:"),
    ("missing usage accepted", GATEWAY, 'raise self.stop("usage_missing")', "return reply"),
    ("timeouts charged nothing", GATEWAY, "charged = worst if charge_worst else Decimal(0)", "charged = Decimal(0)"),
    ("context limit removed", GATEWAY, "if estimate > self.config.max_context_tokens:", "if False:"),
    ("model call limit removed", GATEWAY, 'if self.counts["model_calls"] >= self.config.max_model_calls:', "if False:"),
    ("consecutive error limit removed", GATEWAY, "if self._consecutive_errors >= self.config.max_consecutive_provider_errors:", "if False:"),
    ("consecutive invalid limit removed", GATEWAY, "if self._consecutive_invalid >= self.config.max_consecutive_invalid_replies:", "if False:"),
    ("redaction removed", GATEWAY, 'return _SECRET.sub("[redacted]", str(text))[:limit]', "return str(text)[:limit]"),
    ("session cap not enforced", LEDGER, "if total + worst > session_limit:", "if False:"),
    ("cumulative cap not enforced", LEDGER, "if state.committed + worst > cumulative_limit:", "if False:"),
    ("ledger chain not verified", LEDGER,
     'if entry["prev_sha256"] != tip or hashlib.sha256(_canonical(body)).hexdigest() != entry["sha256"]:', "if False:"),
    ("ledger mode not checked", LEDGER, 'elif records[0].get("mode") != mode or records[0].get("schema") != SCHEMA:', "elif False:"),
    ("keyset.v2 still offers the speed key", CONTRACT, 'if k != "KeyS")', 'if k != "KeyQ")'),
    ("host forwards without asking the gateway", HOST, "self.gateway.authorize_game(tool, act)", "pass"),
    ("player may supply model content", HOST, 'if set(request) != {"tool"}:', "if False:"),
    ("host and gateway may disagree", HOST, 'raise ValueError("the host and the gateway disagree on the keyset, episodes, frames, wall clock or game requests")', "pass"),
]
TESTS = ["tests/blindplay/test_model_gateway.py", "tests/blindplay/test_spend_ledger.py", "tests/blindplay/test_keyset_v2.py"]


def run(repo: Path, src: Path) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONPATH=str(src), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "-x", "--no-header", "-p", "no:cacheprovider",
                           "-k", "not same_inputs and not speed_key_records and not still_replays"],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=600)
    failed = [ln for ln in done.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    return done.returncode == 0, failed[0][:160] if failed else done.stdout.strip().splitlines()[-1][:160]


def main(repo_arg: str, report_arg: str) -> int:
    repo = Path(repo_arg).resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="react-mutation-") as tmp:
        src = Path(tmp) / "src"
        shutil.copytree(repo / "src", src, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        package = src / "rewardbench" / "blindplay"
        passed, summary = run(repo, src)
        if not passed:
            print("the unmodified copy does not pass:", summary)
            return 2
        for name, file, old, new in MUTATIONS:
            path = package / file
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                results.append({"mutation": name, "result": "NOT_APPLIED", "detail": f"{original.count(old)} matches"})
                continue
            path.write_text(original.replace(old, new), encoding="utf-8")
            try:
                survived, detail = run(repo, src)
            finally:
                path.write_text(original, encoding="utf-8")
            results.append({"mutation": name, "result": "SURVIVED" if survived else "caught", "detail": detail})
            print(results[-1]["result"], "-", name, flush=True)
    report = {"mutations": len(results), "caught": sum(r["result"] == "caught" for r in results),
              "survived": [r["mutation"] for r in results if r["result"] == "SURVIVED"],
              "not_applied": [r["mutation"] for r in results if r["result"] == "NOT_APPLIED"], "results": results}
    Path(report_arg).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("mutations", "caught", "survived", "not_applied")}, indent=2))
    return 0 if report["caught"] == report["mutations"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
