"""Tests for the JobSentry Email IMAP Monitor parser."""

import pytest

from job_sentry.emails import EmailMonitor
from job_sentry.models import Job, JobStatus
from job_sentry.store import JobStore


@pytest.fixture
def store():
    return JobStore(db_path=":memory:")


def test_categorize_interview_email(store):
    monitor = EmailMonitor(store)

    # Interview invite keyword match
    status = monitor.categorize_email("Hi, we would like to schedule a quick chat next week.")
    assert status == JobStatus.INTERVIEWING

    # Rejection keyword match
    status_rej = monitor.categorize_email("Thank you for your time. Unfortunately, we are not moving forward.")
    assert status_rej == JobStatus.REJECTED

    # Offer keyword match
    status_off = monitor.categorize_email("We are pleased to offer you the position. Find the offer letter attached.")
    assert status_off == JobStatus.OFFER


def test_mock_email_monitor_transitions_state(store):
    # Seed matching job
    job = Job(
        title="AI Application Engineer",
        company="CognitiveFlow Inc.",
        description="RAG LangGraph development.",
        url="https://example.com/apply",
        status=JobStatus.DISCOVERED
    )
    store.save_job(job)

    monitor = EmailMonitor(store)
    updates = monitor.check_updates()

    assert len(updates) == 1
    assert updates[0]["company"] == "CognitiveFlow Inc."
    assert updates[0]["new_status"] == JobStatus.INTERVIEWING.value

    # Verify database updated
    updated_job = store.get_job(job.job_id)
    assert updated_job.status == JobStatus.INTERVIEWING
