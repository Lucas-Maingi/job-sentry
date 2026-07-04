"""Smoke tests for the JobSentry FastAPI app skeleton."""

import pytest
from fastapi.testclient import TestClient
from job_sentry.app import app, get_store
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


def test_trigger_search(client):
    payload = {
        "keywords": "React Developer",
        "location_filter": "Remote"
    }
    resp = client.post("/search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "search_queued"


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
