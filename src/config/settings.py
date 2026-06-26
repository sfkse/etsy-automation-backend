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

    # Etsy
    ETSY_API_KEY: str = ""
    ETSY_SHARED_SECRET: str = ""
    ETSY_SHOP_ID: str = ""

    # Database
    DATABASE_URL: str = "postgresql+psycopg://etsy:etsy_local_dev@localhost:5432/etsy_taki"

    # Storage
    IMAGES_DIR: str = "./data/images"

    # App
    LOG_LEVEL: str = "INFO"
    DEFAULT_IMAGE_WORKFLOW: Literal["gemini", "openai", "flux"] = "gemini"
