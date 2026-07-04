"""Integration and API tests for the JobSentry Central API."""

import pytest
from fastapi.testclient import TestClient
from job_sentry.app import app, get_store, execute_job_search_and_triage
from job_sentry.store import JobStore
from job_sentry.models import Job, JobStatus


@pytest.fixture
def store():
    # Use clean in-memory database per test run
    test_store = JobStore(db_path=":memory:")
    app.dependency_overrides[get_store] = lambda: test_store
    yield test_store
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_trigger_search_endpoint(client):
    payload = {
        "keywords": "AI Engineer",
        "location_filter": "Remote"
    }
    resp = client.post("/search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "search_queued"


@pytest.mark.asyncio
async def test_execute_job_search_and_triage_worker(store):
    # Run the worker to query and score jobs (with mock fallback listings)
    await execute_job_search_and_triage("WhatsApp", "Nairobi", store)
    
    # Verify mock mobilempesa role was found and scored
    jobs = store.get_all_jobs()
    assert len(jobs) >= 1
    mobile_job = [j for j in jobs if "MobileM-Pesa" in j.company][0]
    
    # MobileM-Pesa system title matches "FastAPI" and "WhatsApp" and "Agent"
    # Base 30 + fastapi 15 + agent 15 = 60.0 score -> should be DRAFTING
    assert mobile_job.match_score >= 60.0
    assert mobile_job.status == JobStatus.DRAFTING
    assert mobile_job.cover_letter is not None


def test_apply_triggers_playwright_scaffold(client, store):
    # Seed a job listing
    job = Job(
        title="AI Engineer",
        company="TechCorp",
        description="We need python developers.",
        url="https://example.com/apply"
    )
    store.save_job(job)
    
    resp = client.post(f"/jobs/{job.job_id}/apply")
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "applied"
    
    updated = store.get_job(job.job_id)
    assert updated.status == JobStatus.APPLIED


def test_refresh_emails_endpoint(client, store):
    # Seed a discovered job for CognitiveFlow
    job = Job(
        title="AI Application Engineer",
        company="CognitiveFlow Inc.",
        description="RAG developers.",
        url="https://example.com/apply",
        status=JobStatus.DISCOVERED
    )
    store.save_job(job)
    
    # Trigger IMAP scan endpoint
    resp = client.post("/emails/refresh")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["updates_found"] == 1
    
    # Verify state transitioned
    updated = store.get_job(job.job_id)
    assert updated.status == JobStatus.INTERVIEWING
