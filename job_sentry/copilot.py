"""AI Job Copilot match scorer and cover letter writer.

Scores scraped jobs against the user's resume and drafts customized cover letters
and common application answers using LLMs or local template heuristics.
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
3. Draft a short, impactful, 3-paragraph Cover Letter.
4. Answer these common application questions:
   - "why_role": "Why are you interested in this position?"
   - "experience_llm": "Describe your hands-on experience integrating LLMs."
Strictly return your analysis as a JSON object with keys:
  - "match_score": float
  - "match_reasoning": string
  - "cover_letter": string
  - "why_role": string
  - "experience_llm": string
"""


class JobCopilot:
    """Evaluates match compatibility and drafts application materials."""

    def __init__(self, llm_api_key: str | None = None):
        self.api_key = llm_api_key or settings.llm_api_key
        self.resume = settings.resume_text
        self.mock_mode = not self.api_key
        if self.mock_mode:
            logging.info("JobSentry Copilot running in MOCK heuristic mode (no LLM API key).")

    def evaluate_and_draft(self, job: Job) -> Job:
        """Run match evaluation and write application drafts for a job."""
        analysis = self._evaluate_fallback(job) if self.mock_mode else self._evaluate_llm(job)

        job.match_score = analysis.get("match_score", 0.0)
        job.match_reasoning = analysis.get("match_reasoning", "Evaluation completed.")

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
                resp = client.post(url, json=payload, headers=headers, timeout=20.0)

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

        # Base resume keywords we check intersection for
        keywords = {
            "python": 15, "fastapi": 15, "next.js": 15, "postgres": 10,
            "docker": 10, "rag": 15, "agent": 15, "langgraph": 15, "playwright": 10
        }

        score = 30.0 # baseline score
        reasons = []

        # Calculate intersection
        for kw, points in keywords.items():
            if kw in title_lower or kw in desc_lower:
                score += points
                reasons.append(kw.upper())

        score = min(score, 100.0)

        # Generate clean template cover letter
        cover_letter = (
            f"Dear Hiring Team at {job.company},\n\n"
            f"I am writing to express my strong interest in the {job.title} position. "
            f"As a Full-Stack AI Engineer experienced in building agentic systems and "
            f"RAG orchestrations, I am confident in my ability to contribute value immediately.\n\n"
            f"In my previous projects, I have implemented scalable FastAPI integrations, custom predictive "
            f"ML models (XGBoost), and headless browser automation systems. I look forward to bringing "
            f"these core competencies in {', '.join(reasons) if reasons else 'AI Engineering'} to your team.\n\n"
            f"Sincerely,\nLucas Maingi"
        )

        why_role = (
            f"I am drawn to {job.company}'s work on {job.title}. My expertise in FastAPI "
            f"and RAG structures aligns directly with the technical requirements of this team."
        )

        experience_llm = (
            "I have built production-ready agentic orchestration loops using LangGraph, "
            "implementing semantic prompt caches, guardrail gateway scanning intercepts, "
            "and real-time streaming tools."
        )

        reasoning = (
            f"Matches resume skills on {', '.join(reasons)}" if reasons
            else "General software alignment; low direct AI skill intersections found."
        )

        return {
            "match_score": score,
            "match_reasoning": reasoning,
            "cover_letter": cover_letter,
            "why_role": why_role,
            "experience_llm": experience_llm
        }
