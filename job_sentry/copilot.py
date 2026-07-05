"""AI Job Copilot match scorer and cover letter writer.

Scores scraped jobs against a candidate's resume and drafts customized cover letters
and common application answers using LLMs (Groq by default) or local template heuristics.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from job_sentry.config import settings
from job_sentry.models import Job

logging.basicConfig(level=logging.INFO)

_COPILOT_SYSTEM_PROMPT = """You are the JobSentry AI Application Writer.
You are given a candidate resume and a target job description.
Your tasks:
1. Score the candidate's match for the role from 0 to 100.
2. Provide a 1-sentence reasoning for the score.
3. Draft a short, impactful, 3-paragraph Cover Letter signed with the candidate's name.
4. Extract the salary or salary range if the job description mentions one (empty string if not).
5. Extract the hiring company's name if identifiable from the title or description (empty string if not).
6. Answer these common application questions:
   - "why_role": "Why are you interested in this position?"
   - "experience_llm": "Describe your hands-on experience integrating LLMs."
Strictly return your analysis as a JSON object with keys:
  - "match_score": float
  - "match_reasoning": string
  - "cover_letter": string
  - "salary": string
  - "company": string
  - "why_role": string
  - "experience_llm": string
"""

_DEFAULT_RESUME = (
    "Generalist software engineer. Skills: Python, APIs, automation, cloud deployment."
)


class JobCopilot:
    """Evaluates match compatibility and drafts application materials for one candidate."""

    def __init__(
        self,
        llm_api_key: str | None = None,
        resume_text: str | None = None,
        candidate_name: str = "The Candidate",
    ):
        self.api_key = llm_api_key or settings.llm_api_key
        self.resume = resume_text or _DEFAULT_RESUME
        self.candidate_name = candidate_name
        self.mock_mode = not self.api_key
        if self.mock_mode:
            logging.info("JobSentry Copilot running in MOCK heuristic mode (no LLM API key).")

    def evaluate_and_draft(self, job: Job) -> Job:
        """Run match evaluation and write application drafts for a job."""
        analysis = self._evaluate_fallback(job) if self.mock_mode else self._evaluate_llm(job)

        job.match_score = float(analysis.get("match_score", 0.0))
        job.match_reasoning = analysis.get("match_reasoning", "Evaluation completed.")

        # Prefer LLM-extracted salary when the scraper regex found nothing
        llm_salary = (analysis.get("salary") or "").strip()
        if llm_salary and not job.salary:
            job.salary = llm_salary

        # Fill in the company name when the scraper couldn't deduce one
        llm_company = (analysis.get("company") or "").strip()
        if llm_company and job.company in ("", "Unknown Company"):
            job.company = llm_company

        # If it's a high match (>= 60%), save the auto-drafted cover letter and questions
        if job.match_score >= 60.0:
            job.cover_letter = analysis.get("cover_letter")
            job.custom_answers = {
                "Why are you interested in this position?": analysis.get("why_role", ""),
                "Describe your hands-on experience integrating LLMs.": analysis.get("experience_llm", "")
            }
        return job

    def _evaluate_llm(self, job: Job) -> dict[str, Any]:
        """Query LLM to score matching qualifications and write covers."""
        prompt = (
            f"Candidate Name: {self.candidate_name}\n"
            f"Candidate Resume:\n{self.resume}\n\n"
            f"Job Listing Title: {job.title} at {job.company}\n"
            f"Job Description:\n{job.description}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": settings.llm_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _COPILOT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        }

        url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client() as client:
                resp = client.post(url, json=payload, headers=headers, timeout=30.0)

            if resp.status_code == 200:
                result = resp.json()
                content_str = result["choices"][0]["message"]["content"]
                return json.loads(content_str)
            else:
                logging.error(f"LLM API returned error status {resp.status_code}: {resp.text}")
        except Exception as e:
            logging.error(f"LLM match evaluation failed: {str(e)}")

        return self._evaluate_fallback(job)

    def _evaluate_fallback(self, job: Job) -> dict[str, Any]:
        """Local keyword intersections for scoring and template-based covers."""
        title_lower = job.title.lower()
        desc_lower = job.description.lower()
        resume_lower = self.resume.lower()

        # Score against skills that appear in BOTH the resume and the listing
        candidate_skills = {
            "python": 15, "fastapi": 15, "next.js": 15, "postgres": 10,
            "docker": 10, "rag": 15, "agent": 15, "langgraph": 15, "playwright": 10,
            "javascript": 10, "react": 10, "sql": 10, "aws": 10, "api": 5,
        }

        score = 30.0 # baseline score
        reasons = []

        for kw, points in candidate_skills.items():
            if kw in resume_lower and (kw in title_lower or kw in desc_lower):
                score += points
                reasons.append(kw.upper())

        score = min(score, 100.0)

        # Generate clean template cover letter
        cover_letter = (
            f"Dear Hiring Team at {job.company},\n\n"
            f"I am writing to express my strong interest in the {job.title} position. "
            f"My background building production software and automation systems maps "
            f"directly onto the requirements in your listing.\n\n"
            f"In my previous projects, I have shipped end-to-end features across the stack "
            f"and I look forward to bringing my strengths in "
            f"{', '.join(reasons) if reasons else 'software engineering'} to your team.\n\n"
            f"Sincerely,\n{self.candidate_name}"
        )

        why_role = (
            f"I am drawn to {job.company}'s work on {job.title}. My skill set "
            f"aligns directly with the technical requirements of this team."
        )

        experience_llm = (
            "I have built production LLM integrations covering prompt design, "
            "structured JSON outputs, retrieval pipelines, and API orchestration."
        )

        reasoning = (
            f"Matches resume skills on {', '.join(reasons)}" if reasons
            else "General software alignment; low direct skill intersections found."
        )

        return {
            "match_score": score,
            "match_reasoning": reasoning,
            "cover_letter": cover_letter,
            "salary": "",
            "company": "",
            "why_role": why_role,
            "experience_llm": experience_llm
        }
