"""Tests for the JobSentry AI Copilot match scorer and cover drafter."""

from job_sentry.copilot import JobCopilot
from job_sentry.models import Job

_RESUME = (
    "Full-Stack AI Engineer. Skills: Python, FastAPI, RAG pipelines, "
    "LangGraph agents, Docker, Playwright automation."
)


def test_copilot_offline_low_match():
    copilot = JobCopilot(llm_api_key="", resume_text=_RESUME, candidate_name="Test Candidate")

    # Job with no matching skills
    job = Job(
        title="Cobol Mainframe Developer",
        company="LegacyCorp",
        description="We work on banking transactions using JCL and Fortran.",
        url="https://example.com/cobol"
    )

    scored_job = copilot.evaluate_and_draft(job)

    assert scored_job.match_score == 30.0  # baseline
    assert scored_job.cover_letter is None  # no drafts for low-match (< 60%)
    assert not scored_job.custom_answers


def test_copilot_offline_high_match_drafts_materials():
    copilot = JobCopilot(llm_api_key="", resume_text=_RESUME, candidate_name="Test Candidate")

    # Job with key matching skills (FastAPI, RAG)
    job = Job(
        title="AI Engineer (FastAPI & RAG)",
        company="FutureSystems",
        description="Build LLM interfaces using Python, FastAPI, and RAG pipelines.",
        url="https://example.com/future"
    )

    scored_job = copilot.evaluate_and_draft(job)

    # Base 30 + python 15 + fastapi 15 + RAG 15 = 75.0
    assert scored_job.match_score >= 60.0
    assert scored_job.cover_letter is not None
    assert "FutureSystems" in scored_job.cover_letter
    assert "Test Candidate" in scored_job.cover_letter
    assert len(scored_job.custom_answers) >= 2
    assert "Why are you interested in this position?" in scored_job.custom_answers


def test_copilot_salary_from_llm_preserved_when_scraper_found_none():
    copilot = JobCopilot(llm_api_key="", resume_text=_RESUME)
    job = Job(
        title="Python Engineer",
        company="PayCo",
        description="Python and FastAPI role.",
        url="https://example.com/payco",
        salary="$120k - $150k",
    )
    scored = copilot.evaluate_and_draft(job)
    # Fallback analysis returns empty salary; the scraped value must survive
    assert scored.salary == "$120k - $150k"
