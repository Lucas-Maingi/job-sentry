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

    # ── LLM Configuration ────────────────────────────────────────────────
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # ── User Profile & Resume Data ───────────────────────────────────────
    resume_text: str = (
        "Name: Lucas Maingi\n"
        "Title: Full-Stack AI & Machine Learning Engineer\n"
        "Skills: Python, FastAPI, Next.js, Postgres, XGBoost, RAG, LangGraph, Docker, CI/CD, Playwright\n"
        "Location: Nairobi, Kenya (Timezone: GMT+3)\n"
        "Experience: 13-month ALX Data Science graduate, built OSINT agentic platform, fraud-monitoring engines."
    )

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
