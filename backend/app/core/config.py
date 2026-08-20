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
    # PostgreSQL, not by preference but by requirement: tenant isolation is
    # enforced by row-level security, which SQLite has no equivalent of.
    database_url: str = "postgresql+psycopg://steeldesk_app:steeldesk_dev@localhost:5432/steeldesk"

    # --- Security ---------------------------------------------------------
    #: Signs session tokens. A change invalidates every live session, which is
    #: the intended lever for "sign everyone out now".
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    #: Encrypts mailbox refresh tokens at rest, so a database backup is not a
    #: set of live Gmail credentials for every customer.
    credential_key: str = ""
    #: Seeded on first boot so there is somebody who can onboard the first
    #: desk. Change the password immediately in any real deployment.
    super_admin_email: str = "admin@steeldesk.io"
    super_admin_password: str = "change-me-now"

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
    # The whole conversation, not just what arrived. A trader who replies in
    # Gmail has still replied, and a system that only reads the inbox cannot
    # see that - it would show the enquiry as unanswered and chase a customer
    # who is waiting on nothing.
    gmail_query: str = "(in:inbox OR in:sent) -in:chats newer_than:7d"
    gmail_max_results: int = 25

    # --- Notifications ----------------------------------------------------
    # "local" writes messages to data/notifications/ instead of sending them,
    # so rules and the queue are exercisable before any provider account
    # exists. Switch to "twilio" once the credentials below are filled in.
    notification_provider: str = Field(default="local", pattern="^(local|twilio)$")
    notifications_enabled: bool = True
    notification_data_dir: str = "data"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_sms_from: str = ""

    # --- Follow-ups -------------------------------------------------------
    # The scheduler decides when a nudge is *due*; sending stays a human
    # action unless a specific rule opts in. This flag only enables the
    # scheduler that queues them.
    follow_ups_enabled: bool = True

    # --- Polling ----------------------------------------------------------
    polling_enabled: bool = False
    polling_interval_seconds: int = 120
    #: How often the poller wakes to *consider* each desk. Whether any given
    #: desk is checked is decided from its own crawl window, so this only
    #: bounds how precisely those windows are honoured.
    poll_tick_seconds: int = 60

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
    def data_dir(self) -> Path:
        return resolve(self.notification_data_dir)

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
