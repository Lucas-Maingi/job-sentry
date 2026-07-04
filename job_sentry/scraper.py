"""Job search scraper and aggregator module.

Fetches job listings from external search engines (using Serper API if configured),
falling back to a local mock aggregator for sandbox testing.
"""

from __future__ import annotations

import logging

import httpx

from job_sentry.config import settings
from job_sentry.models import Job

logging.basicConfig(level=logging.INFO)


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
        query = f"{keywords} {location} job postings"
        url = "https://google.serper.dev/search"

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {"q": query}
        jobs: list[Job] = []

        try:
            with httpx.Client() as client:
                resp = client.post(url, json=payload, headers=headers, timeout=10.0)

            if resp.status_code == 200:
                results = resp.json()
                # Parse organic Google search results
                organic = results.get("organic", [])
                for idx, result in enumerate(organic):
                    title = result.get("title", f"AI Role {idx}")
                    snippet = result.get("snippet", "Detailed description not found.")
                    link = result.get("link", f"https://example.com/job-{idx}")

                    # Deduce company name from title or snippet
                    company = "Unknown Company"
                    if " at " in title:
                        parts = title.split(" at ")
                        company = parts[-1].split("|")[0].split("-")[0].strip()
                    elif " hiring " in title:
                        company = title.split(" hiring ")[0].strip()

                    jobs.append(
                        Job(
                            title=title,
                            company=company,
                            location=location,
                            description=snippet,
                            url=link
                        )
                    )
            else:
                logging.error(f"Serper API returned status {resp.status_code}: {resp.text}")
                return self._search_mock(keywords, location)

        except Exception as e:
            logging.error(f"Serper scraping failed: {str(e)}")
            return self._search_mock(keywords, location)

        return jobs

    def _search_mock(self, keywords: str, location: str) -> list[Job]:
        """Provide mock DevOps and AI roles for offline sandbox demonstrations."""
        # Static mock library matching common engineering keyword queries
        mock_database = [
            {
                "title": "AI/LLM Application Engineer",
                "company": "CognitiveFlow Inc.",
                "location": "Remote (US/Europe)",
                "description": "We are seeking an engineer to build RAG indexing pipelines, manage vector DB storage, and orchestrate agent architectures using LangGraph.",
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
                "description": "Maintain model deployment checks, monitor drift pipelines, and manage real-time fraud isolated isolation-forest trees. Linux SSH bash scripting essential.",
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
                url=item["url"]
            )
            for item in mock_database
            if any(term in item["title"].lower() or term in item["description"].lower() for term in kw_lower.split())
        ]

        # If search matches nothing, return everything as default fallback
        return filtered if filtered else [Job(**item) for item in mock_database]
