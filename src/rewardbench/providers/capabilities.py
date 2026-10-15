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
        "The default script is an empty JSON object. It is not a controller for any environment.",
        "Token counts and latency come from the script. Mock calls are not billed and are not reserved against a provider cap.",
    ),
}

# A strict dollar cap is only as strong as the reservation below.
SPENDING_LIMITS: tuple[str, ...] = (
    "Before a live call, the client reserves input tokens at one per UTF-8 byte plus 64 framing tokens, output tokens at max_output_tokens (default 800, and that same number is sent), and one reservation per HTTP try including provider retries.",
    "The reservation is held under a threading.Lock in this process so concurrent propose calls that share a SpendingGuard cannot each pass a cap that only one of them can afford. That lock is not cross-process and it is not a provider-side spending cap.",
    "OpenAI and xAI reasoning tokens are reserved inside max output because the catalog marks them as included in completion tokens. Gemini bills thoughts separately, so a capped or live Gemini call is refused unless max_reasoning_tokens or gemini_thinking_budget is set, and that budget is sent as thinkingBudget.",
    "Anthropic thinking, when enabled, must sit strictly below max_output_tokens because those tokens share the output cap. The catalog has no cache read or cache write price. Adapters do not send cache breakpoints. A response that reports cache tokens is rejected because that charge was not reserved.",
    "The runner may call propose again after a ModelClientError. Each call reserves its own retries. There is no single hold that covers the runner's max_model_retries in advance.",
    "If the catalog has no finite rate, or a separate reasoning or cache charge has no ceiling, the client does not send the request.",
    "A priced response is added to spent_usd even when it exceeds the reservation or the cap. The overrun is raised as BudgetExceeded, and the next propose in this process stops before another request. An unpriced live charge records the known portion, when there is one, and blocks later live calls instead of dropping the bill.",
)
