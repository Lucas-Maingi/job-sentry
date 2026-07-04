"""FastAPI application — JobSentry's copilot coordination API.

Acts as the control plane for triggering searches, checking statuses, and managing
applications in the job pipeline.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

from job_sentry import __version__
from job_sentry.config import settings
from job_sentry.models import Job, JobStatus, JobSearchQuery
from job_sentry.store import JobStore
from job_sentry.scraper import JobScraper
from job_sentry.copilot import JobCopilot
from job_sentry.browser import FormFiller
from job_sentry.emails import EmailMonitor

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


# ── Background Workers ───────────────────────────────────────────────────

async def execute_job_search_and_triage(keywords: str, location: str, store: JobStore):
    """Worker running job scraping, LLM match evaluation, and covers auto-drafting."""
    try:
        logging.info(f"Triggering scrape for '{keywords}' in location '{location}'...")
        scraper = JobScraper()
        copilot = JobCopilot()
        
        # 1. Fetch search listings
        listings = scraper.search_jobs(keywords, location)
        
        for job in listings:
            # Check if this job has already been scraped by URL
            existing = store.get_job_by_url(job.url)
            if existing:
                continue
                
            # 2. Evaluate skills match & draft letters
            scored_job = copilot.evaluate_and_draft(job)
            
            # 3. Transition to DRAFTING if high match, otherwise keep DISCOVERED
            if scored_job.match_score >= 60.0:
                scored_job.status = JobStatus.DRAFTING
                
            # 4. Save to SQLite store
            store.save_job(scored_job)
            
        logging.info("Scrape and AI triage completed successfully.")
    except Exception as e:
        logging.error(f"Background triage worker error: {str(e)}")


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


@app.post("/search", tags=["copilot"])
async def trigger_search(
    query: JobSearchQuery, 
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_store)
):
    """Triggers background scraping and analysis for jobs matching keyword filters."""
    background_tasks.add_task(execute_job_search_and_triage, query.keywords, query.location_filter, store)
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

    # Launch browser automation
    filler = FormFiller()
    success = filler.auto_fill_application(job, resume_path="Lucas_Resume.pdf")
    
    if success:
        job.status = JobStatus.APPLIED
        store.save_job(job)
        return {
            "status": "success",
            "job_id": job.job_id,
            "new_status": job.status.value,
            "message": "Playwright completed form submittal successfully."
        }
    else:
        raise HTTPException(status_code=500, detail="Playwright form filling session failed.")


@app.post("/emails/refresh", tags=["copilot"])
async def refresh_emails(store: JobStore = Depends(get_store)):
    """Triggers IMAP parsing loop to pull recruiter updates from Gmail."""
    monitor = EmailMonitor(store)
    updates = monitor.check_updates()
    return {
        "status": "success",
        "updates_found": len(updates),
        "updates": updates
    }
