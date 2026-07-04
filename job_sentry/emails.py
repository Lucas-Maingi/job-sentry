"""IMAP Email parser and response categorizer module for JobSentry.

Polls email inboxes (using Python's standard imaplib if configured),
parsing messages to categorize updates (interviews, rejections, offers)
and log status updates inside the SQLite pipeline.
"""

from __future__ import annotations

import imaplib
import email
import logging
from typing import Any
from job_sentry.config import settings
from job_sentry.models import JobStatus
from job_sentry.store import JobStore

logging.basicConfig(level=logging.INFO)


class EmailMonitor:
    """Checks and parses recruiter email responses to track application state."""

    def __init__(self, store: JobStore, email_username: str | None = None):
        self.store = store
        self.username = email_username or settings.email_username
        self.mock_mode = not self.username
        if self.mock_mode:
            logging.info("JobSentry EmailMonitor running in MOCK mode (no email username configured).")

    def check_updates(self) -> list[dict[str, str]]:
        """Check recruiter emails and return list of detected updates."""
        if self.mock_mode:
            return self._check_mock()
        return self._check_real()

    def _check_real(self) -> list[dict[str, str]]:
        """Connect to IMAP server and fetch unread email threads."""
        updates: list[dict[str, str]] = []
        try:
            # Secure SSL connection
            mail = imaplib.IMAP4_SSL(settings.email_imap_server)
            mail.login(self.username, settings.email_password)
            mail.select("inbox")
            
            # Search for unread emails containing keywords
            status, messages = mail.search(None, '(UNSEEN)')
            if status != "OK":
                return updates

            for num in messages[0].split():
                status, data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                subject = msg.get("Subject", "")
                sender = msg.get("From", "")
                body = ""
                
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")

                # Categorize email content
                category = self.categorize_email(subject + "\n" + body)
                if category:
                    # Look up job by company domain in sender
                    company_match = self._find_matching_company(sender)
                    if company_match:
                        # Update status in store
                        company_match.status = category
                        self.store.save_job(company_match)
                        updates.append({
                            "company": company_match.company,
                            "subject": subject,
                            "new_status": category.value
                        })
            mail.logout()
        except Exception as e:
            logging.error(f"IMAP check failed: {str(e)}")
            
        return updates

    def categorize_email(self, content: str) -> Optional[JobStatus]:
        """Classify email text into a Pipeline JobStatus category."""
        text = content.lower()
        
        # 1. Offer check
        if any(term in text for term in ["offer letter", "congratulations", "pleased to offer", "official offer"]):
            return JobStatus.OFFER
            
        # 2. Interview check
        if any(term in text for term in ["interview", "schedule", "chat", "meet with", "availability", "time to connect"]):
            return JobStatus.INTERVIEWING
            
        # 3. Rejection check
        if any(term in text for term in ["thank you for your interest", "not moving forward", "pursue other candidates", "unfortunately"]):
            return JobStatus.REJECTED
            
        return None

    def _find_matching_company(self, sender: str) -> Optional[Any]:
        """Lookup job in database based on sender name/email address patterns."""
        sender_lower = sender.lower()
        all_jobs = self.store.get_all_jobs()
        for job in all_jobs:
            if job.company.lower() in sender_lower:
                return job
        return None

    def _check_mock(self) -> list[dict[str, str]]:
        """Simulates finding recruiter update emails for testing."""
        updates = []
        
        # In mock mode, we trigger an interview invite from CognitiveFlow (which we scraped in mock database)
        all_jobs = self.store.get_all_jobs()
        cognitive_jobs = [j for j in all_jobs if j.company == "CognitiveFlow Inc."]
        
        if cognitive_jobs and cognitive_jobs[0].status == JobStatus.DISCOVERED:
            job = cognitive_jobs[0]
            # Transition status
            job.status = JobStatus.INTERVIEWING
            self.store.save_job(job)
            
            updates.append({
                "company": job.company,
                "subject": "Interview Request: AI Application Engineer",
                "new_status": JobStatus.INTERVIEWING.value
            })
            logging.info(f"[MOCK EMAIL MONITOR] Discovered update: {job.company} -> INTERVIEWING")
            
        return updates
