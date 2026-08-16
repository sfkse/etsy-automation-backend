from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AI providers
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Video provider — Higgsfield (image-to-video). Create keys at
    # https://cloud.higgsfield.ai; auth header is "Key {ID}:{SECRET}".
    HIGGSFIELD_API_KEY_ID: str = ""
    HIGGSFIELD_API_KEY_SECRET: str = ""

    # Etsy OAuth
    ETSY_API_KEY: str = ""
    ETSY_SHARED_SECRET: str = ""
    ETSY_SHOP_ID: str = ""
    ETSY_REDIRECT_URI: str = "http://localhost:8000/admin/etsy/callback"

    # Etsy shop configuration
    SHIPPING_PROFILE_ID: int = 0
    RETURN_POLICY_ID: int = 0
    SHOP_CREATION_DATE: str = ""  # ISO date, e.g. "2024-06-01" — used for new-shop limits

    # Database
    DATABASE_URL: str = "postgresql+psycopg://etsy:etsy_local_dev@localhost:5432/etsy_taki"

    # Storage
    IMAGES_DIR: str = "./data/images"

    # Public origin of this app (scheme + host[:port], no trailing slash), e.g.
    # "https://abc123.ngrok.app". Required for video generation: the video
    # provider fetches the source photo by URL and cannot reach localhost.
    PUBLIC_BASE_URL: str = ""

    # App
    LOG_LEVEL: str = "INFO"
    DEFAULT_IMAGE_WORKFLOW: Literal["gemini", "openai"] = "gemini"
    DEFAULT_VIDEO_WORKFLOW: Literal["dop", "kling"] = "dop"

    # Phase 3 — Research
    REQUIRE_RESEARCH_FOR_GENERATION: bool = False

    # Phase 6 — Per-task LLM model routing.
    #   CREATIVE   = titles, descriptions, tags (quality-sensitive)
    #   STRUCTURED = cliché extraction, research analyzers (pattern extraction)
    #   FALLBACK   = retry target if a STRUCTURED (Haiku) call is malformed
    LLM_MODEL_CREATIVE: str = "claude-sonnet-4-5"
    LLM_MODEL_STRUCTURED: str = "claude-haiku-4-5"
    LLM_MODEL_FALLBACK: str = "claude-sonnet-4-5"

    # Phase 6 — Anthropic prompt caching. When False, LLMClient ignores
    # cached_prefix and merges everything into one prompt (debugging fallback).
    LLM_PROMPT_CACHING_ENABLED: bool = True

    # Phase 6 — Batch title+tag generation. When True, all 3 variants' titles and
    # tags are produced in a single LLM call (9→4 calls/product). Falls back to the
    # per-variant generators automatically on parse/validation failure.
    LLM_BATCH_MODE_ENABLED: bool = True

    # Phase 10 — Google Sheets sync
    GOOGLE_SHEETS_ENABLED: bool = False
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""  # path to service-account JSON key file
    GOOGLE_SHEETS_ID: str = ""             # spreadsheet ID from the URL
