"""Configuration module for JobSentry loading settings from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for JobSentry.

    Uses Pydantic Settings to validate values. Defers to standard env variables.
    """

    app_name: str = "JobSentry"
    debug: bool = False
    db_path: str = "job_sentry.db"

    # ── Job Aggregator Configuration ─────────────────────────────────────
    serper_api_key: str = ""  # Google search API key for job scraping

    # ── LLM Configuration (OpenAI-compatible; Groq by default) ──────────
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"

    # ── Email Parser Credentials (IMAP) ───────────────────────────────────
    # Used by the email parser to check for application updates.
    email_imap_server: str = "imap.gmail.com"
    email_username: str = ""
    email_password: str = ""

    # ── Discord Webhook Integration ──────────────────────────────────────
    discord_webhook_url: str = ""

    # ── Server ──────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "JOBSENTRY_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
