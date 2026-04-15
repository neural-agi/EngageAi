"""Application configuration and environment validation."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Container for backend settings."""

    environment: str = Field(default="development")
    app_name: str = Field(default="EngageAI API")
    log_level: str = Field(default="INFO")
    backend_host: str = Field(default="0.0.0.0")
    backend_port: int = Field(default=8000)
    backend_cors_origins: str = Field(default="")
    api_key: str | None = Field(default=None)
    api_rate_limit_per_minute: int = Field(default=60)

    openai_api_key: str | None = Field(default=None)
    session_manager_secret: str | None = Field(default=None)
    database_url: str | None = Field(default=None)
    openai_base_url: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    ai_timeout_seconds: float = Field(default=30.0)
    ai_max_retries: int = Field(default=2)
    pipeline_timeout_seconds: float = Field(default=120.0)
    pipeline_max_retries: int = Field(default=2)
    pipeline_max_executions_per_day: int = Field(default=5)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def validate_required_settings(settings: Settings | None = None) -> Settings:
    """Validate required environment variables and fail fast when they are missing."""

    settings = settings or get_settings()
    missing_variables: list[str] = []

    if not settings.openai_api_key:
        missing_variables.append("OPENAI_API_KEY")
    if not settings.session_manager_secret:
        missing_variables.append("SESSION_MANAGER_SECRET")
    if not settings.api_key:
        missing_variables.append("API_KEY")
    environment = settings.environment.strip().lower()
    if environment == "production":
        if not settings.backend_cors_origins.strip():
            missing_variables.append("BACKEND_CORS_ORIGINS")

    if missing_variables:
        missing = ", ".join(missing_variables)
        raise RuntimeError(
            "Missing required environment variables: "
            f"{missing}. Set them in the deployment environment or .env file."
        )

    return settings


def get_cors_origins(settings: Settings | None = None) -> list[str]:
    """Return a normalized list of configured CORS origins."""

    settings = settings or get_settings()
    configured_origins = [
        origin.strip()
        for origin in settings.backend_cors_origins.split(",")
        if origin.strip()
    ]
    return configured_origins
