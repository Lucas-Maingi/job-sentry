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


# ── User Profiles ─────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    """A candidate account: resume, contact details, and default search filters."""
    user_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    email: str
    phone: str = ""
    resume_text: str = ""
    resume_path: str = ""  # uploaded resume file used for form uploads
    default_keywords: str = "AI Application Engineer Remote"
    default_location: str = "Remote"
    # Eligibility filters — applied to every scraped listing before it's kept.
    location_mode: str = "remote"   # "remote" | "nairobi" | "any"
    experience_level: str = ""       # "", "entry", "mid", "senior"
    min_salary_usd: int = 0          # 0 = no minimum
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserProfileCreate(BaseModel):
    """Payload for registering a new candidate profile."""
    name: str
    email: str
    phone: str = ""
    resume_text: str = ""
    default_keywords: str = "AI Application Engineer Remote"
    default_location: str = "Remote"
    location_mode: str = "remote"
    experience_level: str = ""
    min_salary_usd: int = 0


# ── Job Application Data ──────────────────────────────────────────────────

class Job(BaseModel):
    """Represents a job opportunity and its state inside the pipeline."""
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    title: str
    company: str
    location: str = "Remote"
    description: str
    url: str
    salary: str | None = None
    source: str = "serper"

    # AI Triage & Parsing
    match_score: float = 0.0
    match_reasoning: str = ""
    status: JobStatus = JobStatus.DISCOVERED

    # Auto-fill drafts
    cover_letter: str | None = None
    tailored_resume: str | None = None  # ATS-plain resume generated for this JD
    custom_answers: dict[str, str] = Field(default_factory=dict)

    # Browser automation evidence
    apply_log: str = ""              # human-readable trace of the last form-fill run
    screenshot_path: str | None = None  # proof screenshot of the filled application

    # Audit log timestamps
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    applied_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusEvent(BaseModel):
    """One entry in a job's stage-transition audit trail."""
    event_id: int | None = None
    job_id: str
    status: JobStatus
    note: str = ""
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobSearchQuery(BaseModel):
    """Parameters to trigger a job search scrape."""
    keywords: str = ""
    location_filter: str = ""


class StatusUpdate(BaseModel):
    """Payload for manually moving a job to a new pipeline stage."""
    status: JobStatus
    note: str = ""


class CoverLetterUpdate(BaseModel):
    """Payload for saving an operator-edited cover letter draft."""
    cover_letter: str


class ApplyRequest(BaseModel):
    """Options for a browser form-fill run."""
    auto_submit: bool | None = None  # None -> fall back to the configured default


class ApplyReport(BaseModel):
    """Outcome of a browser form-fill run."""
    job_id: str
    success: bool
    submitted: bool
    filled_fields: list[str] = Field(default_factory=list)
    log: str = ""
    screenshot_path: str | None = None
    new_status: str = ""
    message: str = ""
