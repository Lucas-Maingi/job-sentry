"""Job search scraper and aggregator module.

Fetches job listings from external search engines (using Serper API if configured),
falling back to a local mock aggregator for sandbox testing.
"""

from __future__ import annotations

import logging
import re

import httpx

from job_sentry.config import settings
from job_sentry.models import Job

logging.basicConfig(level=logging.INFO)

# Matches "$120,000", "$120k - $150k", "€90k", "£65,000 per year", "120k-150k USD"
_SALARY_PATTERN = re.compile(
    r"""
    (?:\$|€|£|USD\s?|EUR\s?|GBP\s?)\s?
    \d{2,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?
    (?:\s?(?:-|–|—|to)\s?
       (?:\$|€|£)?\s?\d{2,3}(?:,\d{3})*(?:\.\d+)?\s?[kK]?)?
    (?:\s?(?:per\s(?:year|annum|hour|month)|/(?:yr|year|hr|hour|mo)|annually))?
    """,
    re.VERBOSE,
)


def extract_salary(text: str) -> str | None:
    """Pull the first salary-looking figure out of a job description snippet."""
    match = _SALARY_PATTERN.search(text)
    if not match:
        return None
    salary = match.group(0).strip()
    # Discard bare small figures that are likely not salaries (e.g. "$50")
    digits = re.sub(r"[^\d]", "", salary)
    if len(digits) < 4 and "k" not in salary.lower():
        return None
    return salary


class JobScraper:
    """Aggregates job listings across search engines and APIs."""

    def __init__(self, serper_api_key: str | None = None):
        self.api_key = serper_api_key or settings.serper_api_key
        self.mock_mode = not self.api_key
        if self.mock_mode:
            logging.info("JobSentry Scraper running in MOCK mode (no Serper API key configured).")

    def search_jobs(self, keywords: str, location: str = "Remote") -> list[Job]:
        """Scrape or simulate job listings based on criteria."""
        if self.mock_mode:
            return self._search_mock(keywords, location)
        return self._search_serper(keywords, location)

    def _search_serper(self, keywords: str, location: str) -> list[Job]:
        """Fetch search results from Serper API and parse into Job schemas."""
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        # Two passes with plain-text queries only — Serper's free tier rejects
        # advanced operators like site:, OR, and quoted phrases.
        queries = [
            f"{keywords} {location} careers apply",
            f"{keywords} {location} job openings hiring now",
        ]

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        try:
            with httpx.Client() as client:
                for query in queries:
                    resp = client.post(
                        url,
                        json={"q": query, "num": 20},
                        headers=headers,
                        timeout=15.0,
                    )
                    if resp.status_code != 200:
                        logging.error(f"Serper API returned status {resp.status_code}: {resp.text}")
                        continue

                    for result in resp.json().get("organic", []):
                        link = result.get("link", "")
                        if not link or link in seen_urls:
                            continue
                        seen_urls.add(link)

                        title = result.get("title", "Untitled Role")
                        snippet = result.get("snippet", "")

                        jobs.append(
                            Job(
                                title=self._clean_title(title),
                                company=self._deduce_company(title, link),
                                location=location,
                                description=snippet or "Description pending — open the listing URL.",
                                url=link,
                                salary=extract_salary(f"{title} {snippet}"),
                                source="serper",
                            )
                        )
        except Exception as e:
            logging.error(f"Serper scraping failed: {str(e)}")

        if not jobs:
            return self._search_mock(keywords, location)
        return jobs

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip job-board boilerplate suffixes from result titles."""
        for sep in (" | ", " - Job Application", " – Careers", " — Careers"):
            if sep in title:
                title = title.split(sep)[0]
        return title.strip()

    @staticmethod
    def _deduce_company(title: str, link: str) -> str:
        """Best-effort company name extraction from result title or URL path."""
        if " at " in title:
            return title.split(" at ")[-1].split("|")[0].split("-")[0].strip()
        if " hiring " in title:
            return title.split(" hiring ")[0].strip()

        # Greenhouse/Lever/Ashby URLs carry the company slug in the path
        board_match = re.search(
            r"(?:boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com)/([^/]+)", link
        )
        if board_match:
            return board_match.group(1).replace("-", " ").title()

        workable_match = re.search(r"apply\.workable\.com/([^/]+)", link)
        if workable_match:
            return workable_match.group(1).replace("-", " ").title()

        return "Unknown Company"

    def _search_mock(self, keywords: str, location: str) -> list[Job]:
        """Provide mock DevOps and AI roles for offline sandbox demonstrations."""
        # Static mock library matching common engineering keyword queries
        mock_database = [
            {
                "title": "AI/LLM Application Engineer",
                "company": "CognitiveFlow Inc.",
                "location": "Remote (US/Europe)",
                "description": "We are seeking an engineer to build RAG indexing pipelines, manage vector DB storage, and orchestrate agent architectures using LangGraph. Salary: $140,000 - $170,000 per year.",
                "url": "https://careers.cognitiveflow.example.com/jobs/ai-application-engineer"
            },
            {
                "title": "Full-Stack AI Developer",
                "company": "Hyperion Labs",
                "location": "Remote (Global)",
                "description": "Looking for a Python/Next.js developer to integrate LLM pipelines behind authenticated payment gateways. Experience with Stripe, FastAPI, and docker required.",
                "url": "https://hyperionlabs.example.com/careers/ai-dev-fullstack"
            },
            {
                "title": "MLOps Observability Engineer",
                "company": "Vanguard AI",
                "location": "Hybrid (London)",
                "description": "Maintain model deployment checks, monitor drift pipelines, and manage real-time fraud isolated isolation-forest trees. Linux SSH bash scripting essential. £75,000 per annum.",
                "url": "https://vanguard.example.com/jobs/mlops-observability"
            },
            {
                "title": "WhatsApp Agent Orchestrator",
                "company": "MobileM-Pesa Systems",
                "location": "Nairobi, Kenya",
                "description": "Build WhatsApp conversational agents connected to M-Pesa merchant webhooks. Experience with Twilio API, FastAPI, and async workers required.",
                "url": "https://mobilempesa.example.com/jobs/whatsapp-mpesa-agent"
            }
        ]

        # Simple string-matching keyword filtering
        kw_lower = keywords.lower()
        filtered = [
            Job(
                title=item["title"],
                company=item["company"],
                location=item["location"],
                description=item["description"],
                url=item["url"],
                salary=extract_salary(item["description"]),
                source="mock",
            )
            for item in mock_database
            if any(term in item["title"].lower() or term in item["description"].lower() for term in kw_lower.split())
        ]

        # If search matches nothing, return everything as default fallback
        if filtered:
            return filtered
        return [
            Job(**item, salary=extract_salary(item["description"]), source="mock")
            for item in mock_database
        ]
