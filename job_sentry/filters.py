"""Deterministic eligibility filters applied to scraped listings before they're
kept in a user's pipeline.

The most valuable filter is *location eligibility*: it stops the pipeline from
wasting applications (and screening attempts) on roles the candidate is
structurally ineligible for — onsite roles in another city, or "remote" roles
that are actually region-locked to the US/EU. Salary is a soft filter: a job is
only excluded when it *states* a number that's clearly below the minimum, never
when the pay is simply unknown.
"""

from __future__ import annotations

import re

from job_sentry.models import Job

# Signals extracted from the job's location + title + description (lowercased).
_REMOTE = ("remote", "work from home", "wfh", "distributed", "work anywhere", "fully remote")
_NAIROBI = ("nairobi", "kenya", "254")

# "Remote, but only if you live in X" — the trap that produces fast auto-rejections
# for a Nairobi-based candidate. Best-effort: snippet text is imperfect.
_REGION_LOCK = (
    "us only", "u.s. only", "usa only", "united states only", "us-based", "u.s.-based",
    "based in the us", "based in the united states", "must reside in the united states",
    "eu only", "uk only", "canada only", "authorized to work in the us",
    "eligible to work in the united states", "must be located in the us",
    "work authorization in the united states", "us work authorization",
)


def _text(job: Job) -> str:
    return f"{job.location} {job.title} {job.description}".lower()


def location_eligible(job: Job, mode: str) -> tuple[bool, str]:
    """Decide whether a listing fits the candidate's location constraint.

    mode: "remote" (globally/Africa-open remote), "nairobi" (Nairobi/Kenya
    onsite or hybrid), or "any" (no location filter).
    """
    if mode == "any" or not mode:
        return True, "any location"

    text = _text(job)

    if mode == "nairobi":
        if any(sig in text for sig in _NAIROBI):
            return True, "Nairobi/Kenya based"
        # A globally-remote role is still doable from Nairobi.
        if any(sig in text for sig in _REMOTE) and not any(s in text for s in _REGION_LOCK):
            return True, "remote (workable from Nairobi)"
        return False, "not Nairobi-based and not open-remote"

    # mode == "remote"
    is_remote = any(sig in text for sig in _REMOTE)
    locked = any(sig in text for sig in _REGION_LOCK)
    if is_remote and locked:
        return False, "remote but region-locked to a region you're not in"
    if is_remote:
        return True, "open remote"
    if any(sig in text for sig in _NAIROBI):
        return True, "local (Nairobi) — you can do this in person"
    return False, "no remote signal and not local"


_SALARY_NUM = re.compile(r"\$?\s?(\d{2,3})(?:\s?[,.]?\s?(\d{3}))?\s?(k|000)?", re.I)


def stated_salary_usd(job: Job) -> int | None:
    """Best-effort parse of an annual USD figure from the job's salary field.
    Returns None when nothing parseable is present."""
    raw = (job.salary or "").strip()
    if not raw:
        return None
    m = _SALARY_NUM.search(raw)
    if not m:
        return None
    lead, trail, suffix = m.group(1), m.group(2), m.group(3)
    if trail:                      # e.g. "120,000"
        return int(lead + trail)
    if suffix and suffix.lower() == "k":  # e.g. "120k"
        return int(lead) * 1000
    if suffix == "000":            # e.g. "120 000"
        return int(lead) * 1000
    n = int(lead)
    return n * 1000 if n < 1000 else n  # treat a bare "120" as 120k


def salary_ok(job: Job, min_salary_usd: int) -> tuple[bool, str]:
    """Soft filter: exclude only when a stated salary is clearly below the floor."""
    if not min_salary_usd:
        return True, "no salary floor set"
    stated = stated_salary_usd(job)
    if stated is None:
        return True, "salary not stated — kept"
    if stated >= min_salary_usd:
        return True, f"stated ~${stated:,} meets floor"
    return False, f"stated ~${stated:,} below ${min_salary_usd:,} floor"


def eligible(job: Job, *, location_mode: str, min_salary_usd: int = 0) -> tuple[bool, str]:
    """Combined gate: a job is kept only if it passes both location and salary."""
    loc_ok, loc_reason = location_eligible(job, location_mode)
    if not loc_ok:
        return False, f"location: {loc_reason}"
    sal_ok, sal_reason = salary_ok(job, min_salary_usd)
    if not sal_ok:
        return False, f"salary: {sal_reason}"
    return True, loc_reason
