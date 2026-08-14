import anthropic
import structlog

from src.config.settings import Settings

_settings = Settings()
_log = structlog.get_logger(__name__)

# claude-3-haiku is the cheapest model — only used for research analysis tasks
_RESEARCH_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024


class LLMClient:
    """Thin async wrapper around Anthropic.

    The ``model`` parameter defaults to the cheap Haiku model used by Phase 3
    research analyzers. Pass ``model=settings.CONTENT_LLM_MODEL`` (Claude Sonnet)
    for Phase 6 content generation where output quality matters more than cost.
    """

    def __init__(self, api_key: str | None = None, model: str = _RESEARCH_MODEL):
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or _settings.ANTHROPIC_API_KEY or None
        )
        self._model = model

    async def complete(
        self,
        prompt: str,
        max_tokens: int = _MAX_TOKENS,
        model: str | None = None,
        cached_prefix: str | None = None,
        temperature: float = 1.0,
    ) -> str:
        """Send a completion request, optionally with a cached prefix.

        If ``cached_prefix`` is provided (and ``LLM_PROMPT_CACHING_ENABLED`` is
        True), it is sent as a separate content block with
        ``cache_control={"type": "ephemeral"}`` — Anthropic caches it for 5
        minutes and subsequent calls with the same prefix pay ~10% of the normal
        input rate for those tokens. The prefix must clear the model's minimum
        cacheable size (1024 tokens on claude-sonnet-4-5) to actually cache;
        below that it is a silent no-op, not an error.

        When caching is disabled the prefix is merged into a single prompt so the
        model still sees identical content (debugging fallback).
        """
        used_model = model or self._model

        if cached_prefix and _settings.LLM_PROMPT_CACHING_ENABLED:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": cached_prefix,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
        elif cached_prefix:
            # Caching off: merge so behaviour matches the cached path byte-for-byte.
            messages = [{"role": "user", "content": f"{cached_prefix}\n\n{prompt}"}]
        else:
            messages = [{"role": "user", "content": prompt}]

        # NOTE: temperature is accepted by claude-sonnet-4-5 / claude-haiku-4-5.
        # If CONTENT_LLM_MODEL is ever bumped to a 4.6+/5 model, sampling params
        # are rejected (400) and this must be dropped.
        message = await self._client.messages.create(
            model=used_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        usage = message.usage
        _log.info(
            "llm_call_complete",
            model=used_model,
            input_tokens=usage.input_tokens,
            cache_read=getattr(usage, "cache_read_input_tokens", 0),
            cache_created=getattr(usage, "cache_creation_input_tokens", 0),
            output_tokens=usage.output_tokens,
        )
        return message.content[0].text


def get_llm_client() -> LLMClient:
    """FastAPI dependency / convenience factory — Phase 3 research (Haiku)."""
    return LLMClient()


def get_content_llm_client() -> LLMClient:
    """FastAPI dependency / convenience factory — Phase 6 content (Sonnet)."""
    return LLMClient(model=_settings.CONTENT_LLM_MODEL)
