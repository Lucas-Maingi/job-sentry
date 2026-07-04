"""Tests for the JobSentry Playwright FormFiller engine."""

from job_sentry.browser import FormFiller
from job_sentry.models import Job


def test_form_filler_defaults_to_mock():
    filler = FormFiller()
    assert filler.mock_mode is True


def test_form_filler_mock_execution():
    filler = FormFiller(mock_mode=True)
    job = Job(
        title="AI Engineer",
        company="InnovativeCorp",
        description="We need engineers.",
        url="https://example.com/apply-now"
    )
    job.cover_letter = "Hi, I am Lucas."
    job.custom_answers = {"Why work here?": "Because you are innovative."}

    success = filler.auto_fill_application(job, resume_path="Lucas_Resume.pdf")

    assert success is True
