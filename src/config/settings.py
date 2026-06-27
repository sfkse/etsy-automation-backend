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
    FAL_API_KEY: str = ""

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

    # App
    LOG_LEVEL: str = "INFO"
    DEFAULT_IMAGE_WORKFLOW: Literal["gemini", "openai", "flux"] = "gemini"

    # Phase 3 — Research
    REQUIRE_RESEARCH_FOR_GENERATION: bool = False

    # Phase 6 — Content LLM (Sonnet for quality; Haiku used by research analyzers)
    CONTENT_LLM_MODEL: str = "claude-sonnet-4-5"

    # Phase 10 — Google Sheets sync
    GOOGLE_SHEETS_ENABLED: bool = False
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""  # path to service-account JSON key file
    GOOGLE_SHEETS_ID: str = ""             # spreadsheet ID from the URL
