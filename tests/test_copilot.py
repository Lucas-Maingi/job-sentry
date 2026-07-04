"""Tests for the JobSentry AI Copilot match scorer and cover drafter."""

from job_sentry.copilot import JobCopilot
from job_sentry.models import Job


def test_copilot_offline_low_match():
    copilot = JobCopilot(llm_api_key="")

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
    copilot = JobCopilot()

    # Job with key matching skills (FastAPI, RAG)
    job = Job(
        title="AI Engineer (FastAPI & RAG)",
        company="FutureSystems",
        description="Build LLM interfaces using Python, FastAPI, and RAG pipelines.",
        url="https://example.com/future"
    )

    scored_job = copilot.evaluate_and_draft(job)

    # Base 30 + fastapi 15 + RAG 15 = 60.0
    assert scored_job.match_score >= 60.0
    assert scored_job.cover_letter is not None
    assert "FutureSystems" in scored_job.cover_letter
    assert "FastAPI" in scored_job.cover_letter
    assert len(scored_job.custom_answers) >= 2
    assert "Why are you interested in this position?" in scored_job.custom_answers
