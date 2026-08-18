"""Application configuration.

All tunable behaviour is read from the environment (see `.env.example`).
Nothing business-related is hard-coded here: margins, terms and pricing rules
live in `backend/app/config/pricing_rules.yaml`, not in code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import PROJECT_ROOT, resolve


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ------------------------------------------------------
    app_name: str = "AI Sales Quotation Copilot"
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # --- Company identity -------------------------------------------------
    company_name: str = "Your Steel Trading Company"
    company_email: str = "sales@example.com"
    company_phone: str = "+91 00000 00000"
    company_signatory: str = "Sales Team"

    # --- Database ---------------------------------------------------------
    database_url: str = "sqlite:///data/app.db"

    # --- LLM (OpenRouter) -------------------------------------------------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str = "http://localhost:8000"
    openrouter_app_title: str = "AI Sales Quotation Copilot"

    llm_model_classify: str = "openai/gpt-4o-mini"
    llm_model_extract: str = "anthropic/claude-sonnet-4.5"
    llm_model_draft: str = "anthropic/claude-sonnet-4.5"
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_temperature: float = 0.0

    # --- Email source -----------------------------------------------------
    email_source: str = Field(default="local", pattern="^(local|gmail)$")
    local_email_dir: str = "data/sample/emails"

    gmail_credentials_file: str = "data/secrets/gmail_credentials.json"
    gmail_token_file: str = "data/secrets/gmail_token.json"
    gmail_query: str = "in:inbox -in:chats newer_than:7d"
    gmail_max_results: int = 25

    # --- Polling ----------------------------------------------------------
    polling_enabled: bool = False
    polling_interval_seconds: int = 120

    # --- Safety -----------------------------------------------------------
    # Spec Rule 4: the MVP never sends without a recorded human approval.
    # This flag exists so the guardrail is explicit and auditable; the send
    # service refuses to run if it is ever flipped on in this build.
    auto_send_enabled: bool = False

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    # --- Derived ----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Absolute SQLite URL so the DB is found from any working directory."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix) :]
            db_path = resolve(raw)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return f"{prefix}{db_path.as_posix()}"
        return self.database_url

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")

    @property
    def local_email_path(self) -> Path:
        return resolve(self.local_email_dir)

    @property
    def gmail_credentials_path(self) -> Path:
        return resolve(self.gmail_credentials_file)

    @property
    def gmail_token_path(self) -> Path:
        return resolve(self.gmail_token_file)

    @property
    def llm_configured(self) -> bool:
        """False until an OpenRouter key is supplied; AI steps degrade cleanly."""
        return bool(self.openrouter_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
