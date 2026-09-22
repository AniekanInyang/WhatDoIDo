from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    database_url: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_light_model: str = "openai/gpt-oss-20b"
    groq_light_fallback_model: str | None = "qwen/qwen3.8-27b"
    groq_recommendation_fallback_model: str | None = "openai/gpt-oss-20b"
    decision_llm_token_budget: int = 20_000
    decision_max_clarification_turns: int = 8
    extraction_max_tokens: int = 500
    question_max_tokens: int = 300
    recommendation_max_tokens: int = 1_500
    frontend_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
