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

    async def complete(self, prompt: str, max_tokens: int = _MAX_TOKENS) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = message.usage
        _log.info(
            "llm_call_complete",
            model=self._model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        return message.content[0].text


def get_llm_client() -> LLMClient:
    """FastAPI dependency / convenience factory — Phase 3 research (Haiku)."""
    return LLMClient()


def get_content_llm_client() -> LLMClient:
    """FastAPI dependency / convenience factory — Phase 6 content (Sonnet)."""
    return LLMClient(model=_settings.CONTENT_LLM_MODEL)
