import anthropic

from src.config.settings import Settings

_settings = Settings()

# claude-3-haiku is the cheapest model — only used for research analysis tasks
_MODEL = "claude-3-haiku-20240307"
_MAX_TOKENS = 1024


class LLMClient:
    """Thin async wrapper around Anthropic used by Phase 3 research analyzers."""

    def __init__(self, api_key: str | None = None):
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or _settings.ANTHROPIC_API_KEY or None
        )

    async def complete(self, prompt: str, max_tokens: int = _MAX_TOKENS) -> str:
        message = await self._client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text


def get_llm_client() -> LLMClient:
    """FastAPI dependency / convenience factory."""
    return LLMClient()
