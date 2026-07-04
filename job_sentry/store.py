"""SQLite database store for JobSentry applications pipeline."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from job_sentry.config import settings
from job_sentry.models import Job, JobStatus


class JobStore:
    """Manages persistence and updates of job applications."""

    def __init__(self, db_path: str | None = None):
        self._path = db_path or settings.db_path
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id             TEXT PRIMARY KEY,
                title              TEXT NOT NULL,
                company            TEXT NOT NULL,
                location           TEXT NOT NULL,
                description        TEXT,
                url                TEXT UNIQUE NOT NULL,
                match_score        REAL DEFAULT 0.0,
                match_reasoning    TEXT,
                status             TEXT NOT NULL,
                cover_letter       TEXT,
                custom_answers_json TEXT,
                discovered_at      TEXT NOT NULL,
                applied_at         TEXT,
                updated_at         TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def save_job(self, job: Job) -> None:
        """Create or update a job in the database."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id, title, company, location, description, url,
                match_score, match_reasoning, status, cover_letter,
                custom_answers_json, discovered_at, applied_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.title,
                job.company,
                job.location,
                job.description,
                job.url,
                job.match_score,
                job.match_reasoning,
                job.status.value,
                job.cover_letter,
                json.dumps(job.custom_answers),
                job.discovered_at.isoformat(),
                job.applied_at.isoformat() if job.applied_at else None,
                job.updated_at.isoformat()
            )
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> Job | None:
        cursor = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def get_job_by_url(self, url: str) -> Job | None:
        cursor = self._conn.execute("SELECT * FROM jobs WHERE url = ?", (url,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def get_jobs_by_status(self, status: JobStatus) -> list[Job]:
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY match_score DESC",
            (status.value,)
        )
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_all_jobs(self, limit: int = 100) -> list[Job]:
        cursor = self._conn.execute(
            "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            description=row["description"] or "",
            url=row["url"],
            match_score=row["match_score"],
            match_reasoning=row["match_reasoning"] or "",
            status=JobStatus(row["status"]),
            cover_letter=row["cover_letter"],
            custom_answers=json.loads(row["custom_answers_json"] or "{}"),
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            applied_at=datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"])
        )

    def clear(self) -> None:
        self._conn.execute("DELETE FROM jobs")
        self._conn.commit()
