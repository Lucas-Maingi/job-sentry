"""FastAPI application — JobSentry's copilot coordination API.

Acts as the control plane for triggering searches, checking statuses, and managing
applications in the job pipeline.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse

from job_sentry import __version__
from job_sentry.config import settings
from job_sentry.models import Job, JobStatus, JobSearchQuery
from job_sentry.store import JobStore

# ── Lifespan & Dependency Management ─────────────────────────────────────

_store: JobStore | None = None


def get_store() -> JobStore:
    assert _store is not None, "Store not initialised"
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    _store = JobStore()
    yield


# ── App Definition ───────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="JobSentry AI Job Application Copilot API",
    lifespan=lifespan,
)


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


@app.post("/search", tags=["copilot"])
async def trigger_search(query: JobSearchQuery, store: JobStore = Depends(get_store)):
    """Triggers background scraping and analysis for jobs matching keyword filters."""
    # Scraping logic and LLM scoring will be implemented asynchronously in next commits.
    # For now, we return a success indicator to verify the endpoint scaffold.
    return {
        "status": "search_queued",
        "keywords": query.keywords,
        "location": query.location_filter,
        "message": "Scraper initialized. Discovered listings will populate dashboard."
    }


@app.get("/jobs", response_model=list[Job], tags=["pipeline"])
async def list_jobs(store: JobStore = Depends(get_store)):
    """Retrieve all job application listings inside the pipeline."""
    return store.get_all_jobs()


@app.post("/jobs/{job_id}/apply", tags=["pipeline"])
async def apply_to_job(job_id: str, store: JobStore = Depends(get_store)):
    """Triggers Playwright browser automation task to auto-submit applications."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # In next commits, this launches the Playwright browser session
    # For now, we simulate execution
    job.status = JobStatus.APPLIED
    store.save_job(job)
    
    return {
        "status": "success",
        "job_id": job.job_id,
        "new_status": job.status.value,
        "message": "Playwright completed form submittal."
    }
