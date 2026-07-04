"""Playwright form-filling automation engine with Human-in-the-loop triggers."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, Page
from job_sentry.models import Job

logging.basicConfig(level=logging.INFO)


class FormFiller:
    """Automates browser navigation and form submittals for job applications."""

    def __init__(self, headless: bool = True, mock_mode: bool = True):
        self.headless = headless
        self.mock_mode = mock_mode
        if self.mock_mode:
            logging.info("JobSentry FormFiller initialized in MOCK mode (no browser GUI allocated).")

    def auto_fill_application(self, job: Job, resume_path: Optional[str] = None) -> bool:
        """Run the browser automation sequence for the given job.

        Returns True if the form was successfully auto-filled/submitted.
        """
        if self.mock_mode:
            return self._auto_fill_mock(job, resume_path)
        return self._auto_fill_real(job, resume_path)

    def _auto_fill_real(self, job: Job, resume_path: Optional[str] = None) -> bool:
        """Launches a live Playwright browser session to auto-fill forms."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()
                
                logging.info(f"Navigating to job portal url: {job.url}")
                page.goto(job.url, timeout=30000)
                page.wait_for_load_state("networkidle")

                # 1. Fill standard fields
                self._fill_input_if_exists(page, ["first name", "firstname", "first_name"], "Lucas")
                self._fill_input_if_exists(page, ["last name", "lastname", "last_name"], "Maingi")
                self._fill_input_if_exists(page, ["email", "e-mail"], "maingilucas0@gmail.com")
                self._fill_input_if_exists(page, ["phone", "tel", "mobile"], "+254712345678")
                
                # 2. Upload resume if path supplied
                if resume_path and os.path.exists(resume_path):
                    file_input = page.query_selector("input[type='file']")
                    if file_input:
                        logging.info("Uploading resume file...")
                        file_input.set_input_files(resume_path)

                # 3. Fill cover letter if drafted and field exists
                if job.cover_letter:
                    self._fill_input_if_exists(page, ["cover letter", "cover_letter", "letter"], job.cover_letter)

                # 4. Fill custom questions
                for question, answer in job.custom_answers.items():
                    # Attempt to find textareas matching question keyword parts
                    kw = question.lower().split()[-1]
                    self._fill_input_if_exists(page, [kw], answer)

                # 5. Handle submission or trigger human-in-the-loop pause
                # In production, we check if captcha exists or if page requires manual click.
                # If so, we'd pause for operator input if headless=False:
                # time.sleep(10) # operator completes captcha
                
                # Click apply/submit button
                submit_selectors = [
                    "button[type='submit']", "input[type='submit']", 
                    "button:has-text('Submit')", "button:has-text('Apply')"
                ]
                
                submitted = False
                for sel in submit_selectors:
                    btn = page.query_selector(sel)
                    if btn:
                        logging.info(f"Clicking submission button: {sel}")
                        btn.click()
                        page.wait_for_load_state("networkidle")
                        submitted = True
                        break

                browser.close()
                return submitted
                
        except Exception as e:
            logging.error(f"Playwright execution encountered error: {str(e)}")
            return False

    def _fill_input_if_exists(self, page: Page, labels: list[str], value: str) -> None:
        """Finds input elements based on matching labels/placeholders and fills them."""
        for label in labels:
            # Match by name, placeholder, or label text
            selectors = [
                f"input[name*='{label}']",
                f"input[placeholder*='{label}']",
                f"textarea[name*='{label}']",
                f"textarea[placeholder*='{label}']"
            ]
            for selector in selectors:
                el = page.query_selector(selector)
                if el:
                    el.fill(value)
                    return

    def _auto_fill_mock(self, job: Job, resume_path: Optional[str] = None) -> bool:
        """Simulates form fills logging matched fields and submittal events."""
        logging.info(f"[MOCK FORM FILLER] Accessing job URL: {job.url}")
        time.sleep(0.5)
        
        logging.info("[MOCK FORM FILLER] Autofilled Name: Lucas Maingi")
        logging.info("[MOCK FORM FILLER] Autofilled Email: maingilucas0@gmail.com")
        
        if resume_path:
            logging.info(f"[MOCK FORM FILLER] Uploaded resume from path: {resume_path}")
            
        if job.cover_letter:
            logging.info("[MOCK FORM FILLER] Autofilled cover letter draft.")
            
        for q, a in job.custom_answers.items():
            logging.info(f"[MOCK FORM FILLER] Answered custom question: '{q}' -> '{a[:30]}...'")

        logging.info("[MOCK FORM FILLER] Clicked submission button. Application transmitted.")
        return True
