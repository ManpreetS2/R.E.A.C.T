"""Observable sampling and billing differences. These are not a shared contract.

Core passes ``model_settings`` through without interpreting them. Each adapter
applies only the knobs that provider documents, and records the rest as ignored.
"""

from __future__ import annotations

PROVIDER_DIFFERENCES: dict[str, tuple[str, ...]] = {
    "openai": (
        "Chat Completions at a configurable endpoint. The default output cap field is max_completion_tokens, not max_tokens.",
        "temperature, top_p, and seed are sent only when those keys are set.",
        "top_k is ignored.",
        "When reasoning_effort is set, temperature and top_p are omitted because OpenAI reasoning models reject those sampling parameters.",
        "reasoning_tokens are read from completion_tokens_details.reasoning_tokens and are already included in completion_tokens, so the bill does not add them again.",
        "response_format json_object is requested by default. Some models reject it; set json_mode false to omit it.",
    ),
    "google": (
        "generateContent. The system prompt is systemInstruction, not a chat role.",
        "temperature, topP, and topK are sent only when set. seed is not sent unless gemini_send_seed is true, and then it is marked as not guaranteed.",
        "JSON replies use responseMimeType application/json. That is not OpenAI's response_format.",
        "Thinking uses thinkingConfig.thinkingBudget only when gemini_thinking_budget is set. reasoning_effort is ignored.",
        "thoughtsTokenCount is recorded as reasoning_tokens and priced at the output rate because it is not included in candidatesTokenCount.",
        "The API key is sent in the x-goog-api-key header and is never placed in the URL.",
    ),
    "anthropic": (
        "Messages API. The system prompt is a top-level system field. max_tokens is required.",
        "temperature, top_p, and top_k are sent only when set. seed and reasoning_effort are ignored.",
        "Extended thinking is sent only when anthropic_thinking_budget_tokens is set. Temperature is then omitted rather than forced to another provider's default.",
        "There is no json_object response format. The shared prompt requests JSON, and the parser reads the text blocks.",
        "Cache creation and cache read tokens are recorded and are not priced by the 2026-10-14 catalog.",
        "Input rates in that catalog apply through 100000 prompt tokens. Above that, cost is unpriced until a long-context rate is configured.",
    ),
    "xai": (
        "OpenAI-compatible Chat Completions on api.x.ai. The default output cap field is max_tokens, which is not OpenAI's max_completion_tokens.",
        "temperature and top_p are sent only when set. seed and OpenAI reasoning_effort are ignored.",
        "Set grok_reasoning_effort to request xAI reasoning. Temperature and top_p are then omitted because xAI does not document the same combination as OpenAI.",
        "json_object may be requested and is not guaranteed.",
        "The catalog price is the short-context Grok 4.3 list price. It is a cross-tier reference.",
    ),
    "mock": (
        "Returns scripted text in-process. It does not open a socket and does not read an API key.",
        "Token counts and latency come from the script, so cost math can be tested offline.",
    ),
}
