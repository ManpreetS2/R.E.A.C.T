# Mission 015A development log (chronological, 2026-10-30)

Building the offline model gateway, including our own mistakes. **No model was called, no API was authenticated to or
charged. Every "model" was a fixed script (a mocked provider), and every sandbox player a NON-AI stand-in.**

1. **Workspace.** Back on the Windows PC. The main checkout was clean on `feature/isolated-player-runtime`; its gitignored
   research data (`runs/`) was left untouched. PR #24's branch was fetched, and this work is in a separate worktree
   (`R.E.A.C.T-mission-015a`) with its own virtual environment, based on `c1d4b9b`. `claude auth status` reported a
   `claude.ai` login on the Pro subscription; no `ANTHROPIC_*`/provider keys, base URL, `apiKeyHelper` or cloud-provider
   switches were set.
2. **`keyset.v2`.** Added as a new immutable `ContractVersion`. The v1 contract's hash was recorded from the unmodified code
   before any change (`083d655c…`) and is pinned by a test, so v1 is provably untouched. Sessions record their keyset, and
   `replay.py` reads it from `session.json`, so a v1 session that pressed `KeyS` still replays. The upstream game is unchanged.
   `Session`, `serve` and `HostConfig` keep v1 as the default so nothing changes meaning silently; only the model gateway
   requires v2.
3. **Design change: the host owns the conversation.** Mission 014's `agent` loop kept the message list inside the sandbox.
   Reading it again for a billed session showed two problems: a compromised player could write anything into a model's
   history, and its `[:8]` cut would leave some tool calls unanswered, which real providers reject. The gateway now builds the
   history itself, and the player's request is exactly `{"tool": "model"}`. A further rule followed naturally: a game request
   passes only if it is the model's next validated call. `agent` mode stays, unchanged, for Mission 014's test; the host
   refuses a real model in it.
4. **Finding from the API reference, not from a call.** Reading the bundled Claude API documentation showed that on current
   models thinking blocks are bound to the exact earlier conversation, and an edited turn makes replayed blocks fail with a
   400 on enforced accounts. The last-four-screenshots policy is such an edit. Hence: never replay thinking. The same reading
   showed Claude Haiku 5.5's price rises 5× above 100K input tokens, hence the price threshold in `ModelPricing`, and that a
   server-side `fallbacks` option could change the model mid-session, so it is deliberately not used (and a different model
   answering stops the session). None of this has been confirmed against the real API.
5. **Reservation before the call.** The ledger fsyncs a worst-case reservation before the provider is contacted, so any crash
   overstates spending and never understates it. Uncertain failures (timeouts, 5xx) stay charged at worst case. A hash chain plus
   an OS lock (released by the kernel on process death, so no stale lock) cover tampering and concurrent sessions.
6. **Bug found by the tests:** a hallucinated tool whose `name` was a JSON list crashed the gateway (`unhashable type: 'list'`)
   instead of being rejected. It would have ended a paid session early. Fixed: the type is checked first, and deeply nested
   arguments are handled too.
7. **Test mistakes (ours, not the gateway's):** a mock usage figure above the output limit (the gateway correctly stopped); a
   session cap above the cumulative cap (the configuration correctly refused it); a second session whose own cap fired before
   the cumulative one (rewritten to test the cumulative cap directly); a test host missing its start time. None of these changed a
   safety rule.
