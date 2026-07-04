"""Domain models for JobSentry applications and state management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

# ── Status Enums ─────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    DISCOVERED = "discovered"     # Scraped, match evaluated
    DRAFTING = "drafting"         # High-match, LLM answers/letter drafted
    APPLIED = "applied"           # Playwright ran, awaiting email confirmation
    INTERVIEWING = "interviewing" # Recruiter email parsed (active interviews)
    REJECTED = "rejected"         # Refusal email parsed
    OFFER = "offer"               # Offer email parsed
    ARCHIVED = "archived"         # Dismissed by operator


# ── Job Application Data ──────────────────────────────────────────────────

class Job(BaseModel):
    """Represents a job opportunity and its state inside the pipeline."""
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    company: str
    location: str = "Remote"
    description: str
    url: str

    # AI Triage & Parsing
    match_score: float = 0.0
    match_reasoning: str = ""
    status: JobStatus = JobStatus.DISCOVERED

    # Auto-fill drafts
    cover_letter: str | None = None
    custom_answers: dict[str, str] = Field(default_factory=dict)

    # Audit log timestamps
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    applied_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobSearchQuery(BaseModel):
    """Parameters to trigger a job search scrape."""
    keywords: str = "AI Application Engineer Remote"
    location_filter: str = "United States"
