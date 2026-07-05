"""Playwright form-filling automation engine with Human-in-the-loop safety.

Fills real application forms (Greenhouse, Lever, Workable, Ashby, and generic
career pages) with the candidate's profile details, drafted cover letter, and
resume file, then captures a proof screenshot. Clicking Submit is gated behind
an explicit auto_submit flag so a human always stays in the loop by default.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from job_sentry.config import settings
from job_sentry.models import Job, UserProfile

logging.basicConfig(level=logging.INFO)

_FALLBACK_PROFILE = UserProfile(name="JobSentry Candidate", email="candidate@example.com")

# Field detection strategies: canonical field -> (label regex, attribute needles)
_FIELD_PATTERNS: dict[str, tuple[str, list[str]]] = {
    "first_name": (r"first\s*name", ["first_name", "firstname", "first-name"]),
    "last_name": (r"last\s*name|surname|family\s*name", ["last_name", "lastname", "last-name"]),
    "full_name": (r"^(full\s*)?name$|your\s*name", ["full_name", "fullname", "name"]),
    "email": (r"e-?mail", ["email"]),
    "phone": (r"phone|mobile|tel", ["phone", "tel", "mobile"]),
    "location": (r"location|city|current\s*address", ["location", "city"]),
    "cover_letter": (r"cover\s*letter|why.*(join|interested)|motivation", ["cover_letter", "coverletter", "cover-letter", "comments", "additional"]),
}

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit application')",
    "button:has-text('Submit Application')",
    "button:has-text('Submit')",
    "button:has-text('Apply')",
    "#btn-submit",
]

_COOKIE_BUTTONS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept cookies')",
    "button:has-text('I agree')",
    "#onetrust-accept-btn-handler",
]


class FillResult:
    """Mutable run report collected while a form-fill session executes."""

    def __init__(self) -> None:
        self.filled_fields: list[str] = []
        self.lines: list[str] = []
        self.submitted = False
        self.success = False
        self.screenshot_path: str | None = None

    def log(self, message: str) -> None:
        self.lines.append(message)
        logging.info(f"[FORM FILLER] {message}")

    @property
    def text_log(self) -> str:
        return "\n".join(self.lines)


class FormFiller:
    """Automates browser navigation and form fills for job applications."""

    def __init__(
        self,
        headless: bool | None = None,
        mock_mode: bool | None = None,
        profile: UserProfile | None = None,
        auto_submit: bool | None = None,
    ):
        self.headless = settings.browser_headless if headless is None else headless
        self.mock_mode = settings.browser_mock if mock_mode is None else mock_mode
        self.auto_submit = settings.browser_auto_submit if auto_submit is None else auto_submit
        self.profile = profile or _FALLBACK_PROFILE
        if self.mock_mode:
            logging.info("JobSentry FormFiller initialized in MOCK mode (no browser GUI allocated).")

    # ── Public API ───────────────────────────────────────────────────────

    def fill_application(self, job: Job, resume_path: str | None = None) -> FillResult:
        """Run the browser automation sequence for the given job.

        Fills every recognisable field; clicks Submit only when auto_submit
        is enabled. Always captures a proof screenshot of the filled form.
        """
        resume = resume_path or self.profile.resume_path or None
        if self.mock_mode:
            return self._fill_mock(job, resume)
        return self._fill_real(job, resume)

    def auto_fill_application(self, job: Job, resume_path: str | None = None) -> bool:
        """Backwards-compatible boolean wrapper around fill_application."""
        return self.fill_application(job, resume_path).success

    # ── Real Browser Session ─────────────────────────────────────────────

    def _fill_real(self, job: Job, resume_path: str | None) -> FillResult:
        from playwright.sync_api import sync_playwright

        result = FillResult()
        artifacts = Path(settings.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    viewport={"width": 1366, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()

                result.log(f"Navigating to {job.url}")
                page.goto(job.url, timeout=45000, wait_until="domcontentloaded")
                self._settle(page)
                self._dismiss_cookie_banners(page, result)

                # Greenhouse job pages embed the application form inside an iframe.
                scope = self._resolve_form_scope(page, result)

                filled = self._fill_profile_fields(scope, result)

                # Resume upload
                if resume_path and Path(resume_path).exists():
                    try:
                        file_input = scope.locator("input[type='file']").first
                        if file_input.count() > 0:
                            file_input.set_input_files(resume_path, timeout=8000)
                            result.filled_fields.append("resume")
                            result.log(f"Uploaded resume: {Path(resume_path).name}")
                    except Exception as e:
                        result.log(f"Resume upload skipped: {type(e).__name__}")
                elif resume_path:
                    result.log(f"Resume file not found on disk: {resume_path}")

                # Cover letter + drafted custom answers into remaining textareas
                self._fill_long_answers(scope, job, result)

                if not filled and not result.filled_fields:
                    result.log(
                        "No recognisable application form found on this page. "
                        "It is likely a listing/aggregator page — open it manually "
                        "or use the direct 'Apply' URL of the posting."
                    )

                # Proof screenshot of the filled state
                shot = artifacts / f"{job.job_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
                page.screenshot(path=str(shot), full_page=True)
                result.screenshot_path = str(shot)
                result.log(f"Captured proof screenshot: {shot.name}")

                # Submission is opt-in — human stays in the loop by default.
                if self.auto_submit and result.filled_fields:
                    result.submitted = self._click_submit(scope, page, result)
                    if result.submitted:
                        post = artifacts / f"{job.job_id}_submitted_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
                        page.screenshot(path=str(post), full_page=True)
                        result.screenshot_path = str(post)
                        result.log(f"Captured post-submit screenshot: {post.name}")
                elif result.filled_fields:
                    result.log("Auto-submit disabled — review the screenshot, then submit manually or re-run with auto-submit.")

                browser.close()
                result.success = bool(result.filled_fields)

        except Exception as e:
            result.log(f"Browser session error: {type(e).__name__}: {e}")
            result.success = False

        return result

    def _settle(self, page) -> None:
        """Give SPAs a moment to hydrate without hanging on busy pages."""
        import contextlib

        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=8000)
        time.sleep(1.0)

    def _dismiss_cookie_banners(self, page, result: FillResult) -> None:
        for selector in _COOKIE_BUTTONS:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    result.log("Dismissed cookie banner.")
                    return
            except Exception:
                continue

    def _resolve_form_scope(self, page, result: FillResult):
        """Return the frame containing the application form (Greenhouse iframes)."""
        try:
            for frame in page.frames:
                if frame is not page.main_frame and "greenhouse.io" in (frame.url or ""):
                    result.log("Detected embedded Greenhouse application iframe.")
                    return frame
        except Exception:
            pass
        return page

    def _fill_profile_fields(self, scope, result: FillResult) -> bool:
        """Fill standard candidate fields using label, placeholder, and attribute matching."""
        name_parts = self.profile.name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        values = {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": self.profile.name,
            "email": self.profile.email,
            "phone": self.profile.phone,
            "location": self.profile.default_location,
        }

        # If a dedicated first-name field exists, skip the full-name pattern
        # (and vice versa) to avoid writing the full name twice.
        has_first = self._find_field(scope, *_FIELD_PATTERNS["first_name"]) is not None

        any_filled = False
        for field, value in values.items():
            if not value:
                continue
            if field == "full_name" and has_first:
                continue
            if field in ("first_name", "last_name") and not has_first:
                continue

            target = self._find_field(scope, *_FIELD_PATTERNS[field])
            if target is not None:
                try:
                    target.fill(value, timeout=5000)
                    result.filled_fields.append(field)
                    result.log(f"Filled {field.replace('_', ' ')}: {value if field != 'phone' else '•••'}")
                    any_filled = True
                except Exception as e:
                    result.log(f"Could not fill {field}: {type(e).__name__}")
        return any_filled

    def _find_field(self, scope, label_pattern: str, attr_needles: list[str]):
        """Locate one visible, empty input via label text or attribute needles."""
        # Strategy 1: accessible label
        try:
            loc = scope.get_by_label(re.compile(label_pattern, re.I)).first
            if loc.count() > 0 and loc.is_visible() and loc.is_editable():
                return loc
        except Exception:
            pass

        # Strategy 2: name/id/placeholder attribute contains a needle
        for needle in attr_needles:
            for css in (
                f"input[name*='{needle}' i]",
                f"input[id*='{needle}' i]",
                f"input[placeholder*='{needle}' i]",
                f"textarea[name*='{needle}' i]",
                f"textarea[placeholder*='{needle}' i]",
            ):
                try:
                    loc = scope.locator(css).first
                    if loc.count() > 0 and loc.is_visible() and loc.is_editable():
                        return loc
                except Exception:
                    continue
        return None

    def _fill_long_answers(self, scope, job: Job, result: FillResult) -> None:
        """Place the drafted cover letter and custom answers into textareas."""
        if job.cover_letter:
            target = self._find_field(scope, *_FIELD_PATTERNS["cover_letter"])
            if target is not None:
                try:
                    target.fill(job.cover_letter, timeout=5000)
                    result.filled_fields.append("cover_letter")
                    result.log("Filled cover letter draft.")
                except Exception as e:
                    result.log(f"Could not fill cover letter: {type(e).__name__}")

        for question, answer in job.custom_answers.items():
            if not answer:
                continue
            # Match a textarea whose label shares significant words with the question
            keywords = [w for w in re.findall(r"[a-z]{5,}", question.lower())][:3]
            if not keywords:
                continue
            pattern = "|".join(re.escape(k) for k in keywords)
            try:
                loc = scope.get_by_label(re.compile(pattern, re.I)).first
                if loc.count() > 0 and loc.is_visible() and loc.is_editable():
                    loc.fill(answer, timeout=5000)
                    result.filled_fields.append("custom_answer")
                    result.log(f"Answered custom question: '{question[:48]}…'")
            except Exception:
                continue

    def _click_submit(self, scope, page, result: FillResult) -> bool:
        for selector in _SUBMIT_SELECTORS:
            try:
                btn = scope.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    result.log(f"Clicking submission button ({selector}).")
                    btn.click(timeout=8000)
                    self._settle(page)
                    return True
            except Exception:
                continue
        result.log("No submit button found — application left in filled state.")
        return False

    # ── Mock Session (CI / no browser installed) ─────────────────────────

    def _fill_mock(self, job: Job, resume_path: str | None) -> FillResult:
        result = FillResult()
        result.log(f"[MOCK] Accessing job URL: {job.url}")
        time.sleep(0.2)

        result.log(f"[MOCK] Autofilled Name: {self.profile.name}")
        result.log(f"[MOCK] Autofilled Email: {self.profile.email}")
        result.filled_fields += ["full_name", "email"]

        if resume_path:
            result.log(f"[MOCK] Uploaded resume from path: {resume_path}")
            result.filled_fields.append("resume")

        if job.cover_letter:
            result.log("[MOCK] Autofilled cover letter draft.")
            result.filled_fields.append("cover_letter")

        for q, a in job.custom_answers.items():
            result.log(f"[MOCK] Answered custom question: '{q}' -> '{a[:30]}...'")
            result.filled_fields.append("custom_answer")

        if self.auto_submit:
            result.log("[MOCK] Clicked submission button. Application transmitted.")
            result.submitted = True
        else:
            result.log("[MOCK] Auto-submit disabled — form left filled for review.")

        result.success = True
        return result
