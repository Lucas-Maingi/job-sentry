"""Integration and API tests for the JobSentry Central API."""

import pytest
from fastapi.testclient import TestClient

from job_sentry.app import app, execute_job_search_and_triage, get_store
from job_sentry.models import Job, JobStatus, UserProfile
from job_sentry.store import JobStore


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


@pytest.fixture
def user(store):
    profile = UserProfile(
        name="Test Candidate",
        email="candidate@example.com",
        resume_text="Python, FastAPI, RAG, LangGraph agents, Docker, Playwright engineer.",
        default_keywords="AI Engineer",
        default_location="Remote",
    )
    store.save_user(profile)
    return profile


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_and_list_users(client, store):
    payload = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "resume_text": "Senior Python engineer.",
    }
    resp = client.post("/users", json=payload)
    assert resp.status_code == 201
    user_id = resp.json()["user_id"]

    # Duplicate email registration is rejected
    dup = client.post("/users", json=payload)
    assert dup.status_code == 409

    listed = client.get("/users")
    assert listed.status_code == 200
    assert any(u["user_id"] == user_id for u in listed.json())


def test_update_user_profile(client, user):
    resp = client.put(f"/users/{user.user_id}", json={
        "name": "Test Candidate",
        "email": "candidate@example.com",
        "resume_text": "Updated resume with Kubernetes.",
        "default_keywords": "Platform Engineer",
        "default_location": "Europe",
    })
    assert resp.status_code == 200
    assert resp.json()["default_keywords"] == "Platform Engineer"
    assert "Kubernetes" in resp.json()["resume_text"]


def test_trigger_search_endpoint(client, user):
    payload = {
        "keywords": "AI Engineer",
        "location_filter": "Remote"
    }
    resp = client.post(f"/users/{user.user_id}/search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "search_queued"
    assert resp.json()["user_id"] == user.user_id


def test_trigger_search_unknown_user(client, store):
    resp = client.post("/users/nonexistent/search", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_job_search_and_triage_worker(store, user):
    # Run the worker to query and score jobs (with mock fallback listings)
    await execute_job_search_and_triage(user, "WhatsApp", "Nairobi", store)

    # Verify mock mobilempesa role was found, scored, and scoped to the user
    jobs = store.get_all_jobs(user_id=user.user_id)
    assert len(jobs) >= 1
    mobile_job = [j for j in jobs if "MobileM-Pesa" in j.company][0]

    # Resume matches FastAPI + Agent keywords in listing -> >= 60 -> DRAFTING
    assert mobile_job.match_score >= 60.0
    assert mobile_job.status == JobStatus.DRAFTING
    assert mobile_job.cover_letter is not None
    assert mobile_job.user_id == user.user_id


def test_apply_fill_only_keeps_stage_and_stores_evidence(client, store, user):
    # Default HITL mode: form is filled, but not submitted — stage unchanged
    job = Job(
        user_id=user.user_id,
        title="AI Engineer",
        company="TechCorp",
        description="We need python developers.",
        url="https://example.com/apply",
        status=JobStatus.DRAFTING,
    )
    store.save_job(job)

    resp = client.post(f"/jobs/{job.job_id}/apply", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["submitted"] is False
    assert body["new_status"] == "drafting"

    updated = store.get_job(job.job_id)
    assert updated.status == JobStatus.DRAFTING
    assert updated.apply_log  # evidence trail persisted


def test_apply_with_auto_submit_marks_applied(client, store, user):
    job = Job(
        user_id=user.user_id,
        title="AI Engineer",
        company="TechCorp",
        description="We need python developers.",
        url="https://example.com/apply-direct"
    )
    store.save_job(job)

    resp = client.post(f"/jobs/{job.job_id}/apply", json={"auto_submit": True})
    assert resp.status_code == 200
    assert resp.json()["submitted"] is True
    assert resp.json()["new_status"] == "applied"

    updated = store.get_job(job.job_id)
    assert updated.status == JobStatus.APPLIED
    assert updated.applied_at is not None


def test_resume_upload(client, store, user):
    resp = client.post(
        f"/users/{user.user_id}/resume",
        files={"file": ("My_Resume.pdf", b"%PDF-1.4 fake resume bytes", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["resume_path"].endswith(".pdf")

    refreshed = store.get_user(user.user_id)
    assert refreshed.resume_path

    # Non-document extensions are rejected
    bad = client.post(
        f"/users/{user.user_id}/resume",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert bad.status_code == 400


def test_manual_status_update_and_history(client, store, user):
    job = Job(
        user_id=user.user_id,
        title="ML Engineer",
        company="DeepStack",
        description="Model deployment role.",
        url="https://example.com/ml"
    )
    store.save_job(job)

    resp = client.post(f"/jobs/{job.job_id}/status", json={"status": "interviewing"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "interviewing"

    history = client.get(f"/jobs/{job.job_id}/history")
    assert history.status_code == 200
    statuses = [event["status"] for event in history.json()]
    # Initial discovery event followed by the manual transition
    assert statuses == ["discovered", "interviewing"]


def test_cover_letter_update(client, store, user):
    job = Job(
        user_id=user.user_id,
        title="AI Engineer",
        company="LetterCorp",
        description="Python role.",
        url="https://example.com/letter",
        cover_letter="Original draft."
    )
    store.save_job(job)

    resp = client.put(f"/jobs/{job.job_id}/cover_letter", json={"cover_letter": "Edited draft."})
    assert resp.status_code == 200
    assert store.get_job(job.job_id).cover_letter == "Edited draft."


def test_user_jobs_are_scoped(client, store, user):
    other = UserProfile(name="Other", email="other@example.com")
    store.save_user(other)

    store.save_job(Job(user_id=user.user_id, title="A", company="X",
                       description="", url="https://example.com/a"))
    store.save_job(Job(user_id=other.user_id, title="B", company="Y",
                       description="", url="https://example.com/b"))

    mine = client.get(f"/users/{user.user_id}/jobs").json()
    assert len(mine) == 1
    assert mine[0]["title"] == "A"


def test_refresh_emails_endpoint(client, store, user):
    # Seed a discovered job for CognitiveFlow
    job = Job(
        user_id=user.user_id,
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
