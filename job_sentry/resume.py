"""Generate an ATS-tailored resume from a candidate's master profile + a target JD.

The output is deliberately plain text: single column, no tables, no graphics,
standard section headings — exactly what an ATS parses cleanly — with the
summary and skills tuned to echo the specific job description's language. When
an LLM key is configured it does the tailoring; otherwise a deterministic
template frames the master resume with a JD-aware summary. It never invents
experience the master profile doesn't contain.
"""

from __future__ import annotations

import logging
import re

import httpx

from job_sentry.config import settings
from job_sentry.models import Job, UserProfile

logging.basicConfig(level=logging.INFO)

_SYSTEM_PROMPT = """You are an expert technical resume writer specializing in ATS-friendly resumes.
You are given a candidate's MASTER RESUME and a TARGET JOB DESCRIPTION.
Produce a resume tailored to the target role. Hard rules:
- Use ONLY facts, skills, and experience present in the master resume. Never invent employers,
  dates, degrees, or achievements.
- Output PLAIN TEXT only: single column, no markdown, no tables, no graphics, no columns, no
  asterisks or backticks.
- Use standard, ATS-parseable section headings in this order: a header line with the name and
  contact info, then SUMMARY, SKILLS, PROJECTS / EXPERIENCE, EDUCATION.
- Rewrite the SUMMARY (2-3 lines) and order the SKILLS to mirror the exact terminology used in
  the job description, so the ATS keyword match is high — but only include skills the candidate
  actually has.
- Keep it concise enough to fit two pages.
Output ONLY the finished resume text. No preamble, no explanation, no JSON, no code fences.
"""

# Keywords worth surfacing in the template-fallback summary when they appear in
# both the master resume and the JD.
_SKILL_VOCAB = [
    "python", "fastapi", "next.js", "react", "typescript", "javascript", "postgres", "sql",
    "docker", "kubernetes", "aws", "gcp", "ci/cd", "rag", "llm", "agents", "langgraph",
    "playwright", "machine learning", "pytorch", "tensorflow", "xgboost", "nlp",
    "microservices", "rest", "api", "streamlit", "redis", "kafka", "mlops",
]


def _keywords_in_both(resume_text: str, job: Job) -> list[str]:
    rl = resume_text.lower()
    jl = f"{job.title} {job.description}".lower()
    return [kw for kw in _SKILL_VOCAB if kw in rl and kw in jl]


def _template_resume(profile: UserProfile, job: Job) -> str:
    """Deterministic ATS-plain resume: master resume framed with a JD-aware summary."""
    contact = "  -  ".join(p for p in [profile.email, profile.phone] if p)
    matched = _keywords_in_both(profile.resume_text, job)
    focus = ", ".join(matched[:8]) if matched else "software engineering and AI systems"
    role = job.title.strip() or "the role"

    summary = (
        f"Engineer targeting {role}. Strengths directly relevant to this posting: {focus}. "
        "Builds and ships production-shaped systems end to end, with tests and CI."
    )

    lines = [
        profile.name.upper(),
        contact,
        "",
        "SUMMARY",
        summary,
        "",
        "SKILLS",
        (", ".join(matched) if matched else "See detailed background below."),
        "",
        "EXPERIENCE / PROJECTS",
        profile.resume_text.strip() or "(Add your master resume text to your profile.)",
    ]
    return "\n".join(lines).strip()


def _llm_resume(profile: UserProfile, job: Job, api_key: str) -> str | None:
    prompt = (
        f"MASTER RESUME (candidate: {profile.name}, {profile.email} {profile.phone}):\n"
        f"{profile.resume_text}\n\n"
        f"TARGET JOB: {job.title} at {job.company}\n"
        f"JOB DESCRIPTION:\n{job.description}"
    )
    payload = {
        "model": settings.llm_model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    try:
        with httpx.Client() as client:
            resp = client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=45.0,
            )
        if resp.status_code == 200:
            content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            # Strip any stray markdown emphasis the model may have added.
            text = re.sub(r"[*_`]{1,3}", "", content).strip()
            return text or None
        logging.error(f"Resume LLM returned {resp.status_code}: {resp.text}")
    except Exception as e:  # noqa: BLE001 - fall back to template on any failure
        logging.error(f"Resume LLM generation failed: {e}")
    return None


def generate_tailored_resume(profile: UserProfile, job: Job, api_key: str | None = None) -> str:
    """Return an ATS-plain resume tailored to ``job`` from the candidate's master profile.

    ``api_key`` defaults to the configured key when None; pass an explicit ""
    to force the deterministic template path.
    """
    key = settings.llm_api_key if api_key is None else api_key
    if key and profile.resume_text.strip():
        result = _llm_resume(profile, job, key)
        if result:
            return result
    return _template_resume(profile, job)
