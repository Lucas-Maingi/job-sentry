"""SQLite database store for JobSentry applications pipeline."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from job_sentry.config import settings
from job_sentry.models import Job, JobStatus, StatusEvent, UserProfile


class JobStore:
    """Manages persistence of user profiles, job applications, and stage history."""

    def __init__(self, db_path: str | None = None):
        self._path = db_path or settings.db_path
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          TEXT PRIMARY KEY,
                name             TEXT NOT NULL,
                email            TEXT UNIQUE NOT NULL,
                phone            TEXT DEFAULT '',
                resume_text      TEXT DEFAULT '',
                default_keywords TEXT DEFAULT '',
                default_location TEXT DEFAULT '',
                created_at       TEXT NOT NULL
            )
        """)

        # Legacy single-user installs have a jobs table without user_id and a
        # global UNIQUE(url); rebuild it so uniqueness is scoped per user.
        cursor = self._conn.execute("PRAGMA table_info(jobs)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        if existing_cols and "user_id" not in existing_cols:
            self._conn.execute("ALTER TABLE jobs RENAME TO jobs_legacy")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id             TEXT PRIMARY KEY,
                user_id            TEXT NOT NULL DEFAULT '',
                title              TEXT NOT NULL,
                company            TEXT NOT NULL,
                location           TEXT NOT NULL,
                description        TEXT,
                url                TEXT NOT NULL,
                salary             TEXT,
                source             TEXT DEFAULT 'serper',
                match_score        REAL DEFAULT 0.0,
                match_reasoning    TEXT,
                status             TEXT NOT NULL,
                cover_letter       TEXT,
                custom_answers_json TEXT,
                discovered_at      TEXT NOT NULL,
                applied_at         TEXT,
                updated_at         TEXT NOT NULL,
                UNIQUE(user_id, url)
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL,
                status      TEXT NOT NULL,
                note        TEXT DEFAULT '',
                occurred_at TEXT NOT NULL
            )
        """)

        # Copy legacy rows across once, then drop the old table.
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs_legacy'"
        )
        if cursor.fetchone():
            self._conn.execute("""
                INSERT OR IGNORE INTO jobs (
                    job_id, user_id, title, company, location, description, url,
                    match_score, match_reasoning, status, cover_letter,
                    custom_answers_json, discovered_at, applied_at, updated_at
                )
                SELECT job_id, '', title, company, location, description, url,
                       match_score, match_reasoning, status, cover_letter,
                       custom_answers_json, discovered_at, applied_at, updated_at
                FROM jobs_legacy
            """)
            self._conn.execute("DROP TABLE jobs_legacy")

        self._conn.commit()

    # ── User Profiles ────────────────────────────────────────────────────

    def save_user(self, user: UserProfile) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO users (
                user_id, name, email, phone, resume_text,
                default_keywords, default_location, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.user_id, user.name, user.email, user.phone, user.resume_text,
                user.default_keywords, user.default_location, user.created_at.isoformat()
            )
        )
        self._conn.commit()

    def get_user(self, user_id: str) -> UserProfile | None:
        cursor = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_email(self, email: str) -> UserProfile | None:
        cursor = self._conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_all_users(self) -> list[UserProfile]:
        cursor = self._conn.execute("SELECT * FROM users ORDER BY created_at ASC")
        return [self._row_to_user(row) for row in cursor.fetchall()]

    def _row_to_user(self, row: sqlite3.Row) -> UserProfile:
        return UserProfile(
            user_id=row["user_id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"] or "",
            resume_text=row["resume_text"] or "",
            default_keywords=row["default_keywords"] or "",
            default_location=row["default_location"] or "",
            created_at=datetime.fromisoformat(row["created_at"])
        )

    # ── Jobs ─────────────────────────────────────────────────────────────

    def save_job(self, job: Job) -> None:
        """Create or update a job, logging a status_history event on stage change."""
        existing = self.get_job(job.job_id)
        job.updated_at = datetime.now(timezone.utc)

        self._conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id, user_id, title, company, location, description, url,
                salary, source, match_score, match_reasoning, status, cover_letter,
                custom_answers_json, discovered_at, applied_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.user_id,
                job.title,
                job.company,
                job.location,
                job.description,
                job.url,
                job.salary,
                job.source,
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

        if existing is None or existing.status != job.status:
            self._conn.execute(
                "INSERT INTO status_history (job_id, status, note, occurred_at) VALUES (?, ?, ?, ?)",
                (
                    job.job_id,
                    job.status.value,
                    "Entered pipeline" if existing is None else f"Moved from {existing.status.value}",
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

    def get_job_by_url(self, url: str, user_id: str = "") -> Job | None:
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE url = ? AND user_id = ?", (url, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def get_jobs_by_status(self, status: JobStatus, user_id: str | None = None) -> list[Job]:
        if user_id is None:
            cursor = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY match_score DESC",
                (status.value,)
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM jobs WHERE status = ? AND user_id = ? ORDER BY match_score DESC",
                (status.value, user_id)
            )
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_all_jobs(self, limit: int = 500, user_id: str | None = None) -> list[Job]:
        if user_id is None:
            cursor = self._conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit)
            )
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_status_history(self, job_id: str) -> list[StatusEvent]:
        cursor = self._conn.execute(
            "SELECT * FROM status_history WHERE job_id = ? ORDER BY occurred_at ASC, event_id ASC",
            (job_id,)
        )
        return [
            StatusEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                status=JobStatus(row["status"]),
                note=row["note"] or "",
                occurred_at=datetime.fromisoformat(row["occurred_at"])
            )
            for row in cursor.fetchall()
        ]

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            user_id=row["user_id"] or "",
            title=row["title"],
            company=row["company"],
            location=row["location"],
            description=row["description"] or "",
            url=row["url"],
            salary=row["salary"],
            source=row["source"] or "serper",
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
        self._conn.execute("DELETE FROM status_history")
        self._conn.execute("DELETE FROM users")
        self._conn.commit()
