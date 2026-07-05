"""FastAPI application — JobSentry's copilot coordination API.

Acts as the control plane for registering candidate profiles, triggering searches,
checking statuses, and managing applications in each user's job pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from job_sentry import __version__
from job_sentry.browser import FormFiller
from job_sentry.config import settings
from job_sentry.copilot import JobCopilot
from job_sentry.emails import EmailMonitor
from job_sentry.models import (
    ApplyReport,
    ApplyRequest,
    CoverLetterUpdate,
    Job,
    JobSearchQuery,
    JobStatus,
    StatusEvent,
    StatusUpdate,
    UserProfile,
    UserProfileCreate,
)
from job_sentry.scraper import JobScraper
from job_sentry.store import JobStore

# ── Lifespan & Dependency Management ─────────────────────────────────────

_store: JobStore | None = None
_scan_task: asyncio.Task | None = None


def get_store() -> JobStore:
    assert _store is not None, "Store not initialised"
    return _store


async def autonomous_scan_loop() -> None:
    """Periodically re-scan and triage jobs for every registered user."""
    interval = settings.auto_scan_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            store = get_store()
            users = store.get_all_users()
            logging.info(f"[AUTO-SCAN] Running scheduled scan for {len(users)} user(s).")
            for user in users:
                await execute_job_search_and_triage(
                    user, user.default_keywords, user.default_location, store
                )
            EmailMonitor(store).check_updates()
        except Exception as e:
            logging.error(f"[AUTO-SCAN] Scheduled scan error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _scan_task
    _store = JobStore()
    Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    if settings.auto_scan_interval_minutes > 0:
        _scan_task = asyncio.create_task(autonomous_scan_loop())
        logging.info(
            f"Autonomous scanner armed: every {settings.auto_scan_interval_minutes} minutes."
        )
    yield
    if _scan_task:
        _scan_task.cancel()


# ── App Definition ───────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="JobSentry AI Job Application Copilot API",
    lifespan=lifespan,
)

# Serve proof screenshots captured by the form filler
Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


# ── Background Workers ───────────────────────────────────────────────────

async def execute_job_search_and_triage(user: UserProfile, keywords: str, location: str, store: JobStore):
    """Worker running job scraping, LLM match evaluation, and covers auto-drafting."""
    try:
        logging.info(f"Triggering scrape for '{keywords}' in '{location}' (user: {user.name})...")
        scraper = JobScraper()
        copilot = JobCopilot(resume_text=user.resume_text, candidate_name=user.name)

        # 1. Fetch search listings
        listings = scraper.search_jobs(keywords, location)

        for job in listings:
            # Skip listings this user already tracks (matched by URL)
            existing = store.get_job_by_url(job.url, user_id=user.user_id)
            if existing:
                continue

            job.user_id = user.user_id

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


# ── Ops Endpoints ────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


# ── User Profile Endpoints ───────────────────────────────────────────────

@app.post("/users", response_model=UserProfile, status_code=201, tags=["users"])
async def create_user(payload: UserProfileCreate, store: JobStore = Depends(get_store)):
    """Register a new candidate profile (resume, contacts, default search filters)."""
    if store.get_user_by_email(payload.email):
        raise HTTPException(status_code=409, detail="A profile with this email already exists.")
    user = UserProfile(**payload.model_dump())
    store.save_user(user)
    return user


@app.get("/users", response_model=list[UserProfile], tags=["users"])
async def list_users(store: JobStore = Depends(get_store)):
    """List all registered candidate profiles."""
    return store.get_all_users()


@app.get("/users/{user_id}", response_model=UserProfile, tags=["users"])
async def get_user(user_id: str, store: JobStore = Depends(get_store)):
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.put("/users/{user_id}", response_model=UserProfile, tags=["users"])
async def update_user(user_id: str, payload: UserProfileCreate, store: JobStore = Depends(get_store)):
    """Update a candidate's profile details and search defaults."""
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updated = user.model_copy(update=payload.model_dump())
    store.save_user(updated)
    return updated


# ── Pipeline Endpoints ───────────────────────────────────────────────────

@app.post("/users/{user_id}/search", tags=["copilot"])
async def trigger_search(
    user_id: str,
    query: JobSearchQuery,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_store)
):
    """Queue background scraping + AI triage for one user's keyword filters."""
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    keywords = query.keywords or user.default_keywords
    location = query.location_filter or user.default_location

    background_tasks.add_task(execute_job_search_and_triage, user, keywords, location, store)
    return {
        "status": "search_queued",
        "user_id": user.user_id,
        "keywords": keywords,
        "location": location,
        "message": "Scraper initialized. Discovered listings will populate the dashboard."
    }


@app.get("/users/{user_id}/jobs", response_model=list[Job], tags=["pipeline"])
async def list_user_jobs(
    user_id: str,
    status: JobStatus | None = None,
    store: JobStore = Depends(get_store)
):
    """Retrieve one user's job applications, optionally filtered by pipeline stage."""
    if status is not None:
        return store.get_jobs_by_status(status, user_id=user_id)
    return store.get_all_jobs(user_id=user_id)


@app.get("/jobs/{job_id}", response_model=Job, tags=["pipeline"])
async def get_job(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/history", response_model=list[StatusEvent], tags=["pipeline"])
async def get_job_history(job_id: str, store: JobStore = Depends(get_store)):
    """Full stage-transition audit trail for one job application."""
    if not store.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return store.get_status_history(job_id)


@app.post("/jobs/{job_id}/status", response_model=Job, tags=["pipeline"])
async def update_job_status(job_id: str, payload: StatusUpdate, store: JobStore = Depends(get_store)):
    """Manually move a job to a new pipeline stage (operator override)."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = payload.status
    if payload.status == JobStatus.APPLIED and job.applied_at is None:
        job.applied_at = datetime.now(timezone.utc)
    store.save_job(job)
    return job


@app.put("/jobs/{job_id}/cover_letter", response_model=Job, tags=["pipeline"])
async def update_cover_letter(job_id: str, payload: CoverLetterUpdate, store: JobStore = Depends(get_store)):
    """Persist an operator-edited cover letter draft before applying."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cover_letter = payload.cover_letter
    store.save_job(job)
    return job


@app.post("/jobs/{job_id}/apply", response_model=ApplyReport, tags=["pipeline"])
def apply_to_job(job_id: str, payload: ApplyRequest | None = None, store: JobStore = Depends(get_store)):
    """Runs Playwright browser automation to fill (and optionally submit) the application.

    Declared sync on purpose: FastAPI executes it in a worker thread, which the
    synchronous Playwright API requires. With auto_submit off (the default) the
    form is filled and screenshotted for human review; the candidate confirms
    submission from the dashboard.
    """
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = store.get_user(job.user_id) if job.user_id else None
    auto_submit = payload.auto_submit if payload else None

    filler = FormFiller(profile=profile, auto_submit=auto_submit)
    result = filler.fill_application(job)

    # Persist evidence regardless of outcome
    job.apply_log = result.text_log
    if result.screenshot_path:
        job.screenshot_path = result.screenshot_path

    if result.submitted:
        job.status = JobStatus.APPLIED
        job.applied_at = datetime.now(timezone.utc)
        message = "Form filled and submitted. Post-submit screenshot captured."
    elif result.success:
        message = "Form filled and screenshotted — review the proof, then confirm submission."
    else:
        message = "Could not fill an application form on this page. See the run log."
    store.save_job(job)

    if not result.success:
        raise HTTPException(status_code=422, detail={"message": message, "log": result.text_log})

    return ApplyReport(
        job_id=job.job_id,
        success=result.success,
        submitted=result.submitted,
        filled_fields=result.filled_fields,
        log=result.text_log,
        screenshot_path=result.screenshot_path,
        new_status=job.status.value,
        message=message,
    )


@app.post("/users/{user_id}/resume", response_model=UserProfile, tags=["users"])
async def upload_resume(user_id: str, file: UploadFile = File(...), store: JobStore = Depends(get_store)):
    """Store the candidate's resume file for real form uploads."""
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    suffix = Path(file.filename or "resume.pdf").suffix.lower()
    if suffix not in (".pdf", ".doc", ".docx", ".txt"):
        raise HTTPException(status_code=400, detail="Resume must be a PDF, DOC, DOCX, or TXT file.")

    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{user_id}_{Path(file.filename or 'resume').name}")
    dest = uploads / safe_name
    dest.write_bytes(await file.read())

    user.resume_path = str(dest)
    store.save_user(user)
    return user


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
