# Mission 015B development log (chronological, 2026-10-30)

Preparing the live transport, including our own mistakes. **No real request, test request or token-counting request was made. Nothing authenticated to any API, and nothing was charged. Every HTTP response came from a
mock server on the loopback interface, and every key was fake.** Claude Code stayed on the subscription login (`claude auth status`: `claude.ai`, Pro; no `ANTHROPIC_*` variables).

1. **Workspace.** New worktree `R.E.A.C.T-mission-015b`, stacked on PR #25 at `3cd67f3`, with its own virtual environment. Other checkouts and `runs/` were not touched.
2. **Reading the official documentation first paid off.** Reading only, using the web documentation. Confirmed the model ID, prices and image rules. Three findings changed the plan:
   * Thinking can be turned off on Haiku 5.5. **Our protocol §5 said it could not.** That was an overgeneralization from other models, in a document we wrote; corrected by a dated amendment rather than by rewriting it.
   * The documentation says to echo thinking blocks during tool use, and that filtering them can trigger a 400. Mission 015A's adapter dropped them. Combined with history edits from the screenshot window, no adaptive mode is clean. The gate now accepts
     only `thinking: disabled`, which is also what P1 literally says. This remains an owner decision.
   * `Authorization: Bearer` is the documented header and `x-api-key` is called legacy, although many examples still use the latter.
3. **Standard library, not an SDK.** The mission asked for the smallest transport. `http.client` reads no ambient credentials, ignores proxies, never retries and never follows redirects. Earlier documentation here recommended the SDK; that was revised and
   the owner can overrule it.
4. **Gate design.** Flag first, so a closed gate reads no file at all (tested). The last step needs a person at a real terminal, so no script or agent, including this one, can start spending by itself.
5. **Overclaim fixed.** A Mission 015A comment said 529 was documented as not billed. The documentation does not say that. 529 now stays charged at worst case until reconciled, which can only overstate spending.
6. **Other small fixes from the documentation:** whitespace-only text blocks are dropped, since the API rejects them. Tool names outside the API's pattern are not echoed. Unknown stop reasons never execute a call. The tier spend cap is not retried.
7. **Test mistakes (ours):** a mock usage figure larger than its tiny request could contain; a cumulative-cap test whose cap still left room for one call; and an end-to-end check expecting the final request to carry a screenshot that only exists after its own reply runs. The code was right all three times.
8. **The credential steps were executed, not just written.** The documented PowerShell ran on this PC with a fake key in a scratch folder: the file's only grant was the owner's account, the gate's reader accepted it, and the folder was then removed. No real key was involved.
9. **Verification.** 890 tests collected, 881 passed, 9 skipped (POSIX or macOS only), 0 failed. The mutation check covers 50 rules, 18 of them new, and caught all 50.
