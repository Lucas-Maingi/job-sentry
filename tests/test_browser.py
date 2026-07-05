"""Tests for the JobSentry Playwright FormFiller engine."""

from job_sentry.browser import FormFiller
from job_sentry.models import Job, UserProfile


def _job() -> Job:
    job = Job(
        title="AI Engineer",
        company="InnovativeCorp",
        description="We need engineers.",
        url="https://example.com/apply-now"
    )
    job.cover_letter = "Hi, I am a strong candidate."
    job.custom_answers = {"Why work here?": "Because you are innovative."}
    return job


def test_form_filler_mock_fill_without_submit():
    filler = FormFiller(mock_mode=True, auto_submit=False,
                        profile=UserProfile(name="Jane Doe", email="jane@example.com"))
    result = filler.fill_application(_job(), resume_path="Jane_Resume.pdf")

    assert result.success is True
    assert result.submitted is False  # HITL default: fill only
    assert "full_name" in result.filled_fields
    assert "resume" in result.filled_fields
    assert "cover_letter" in result.filled_fields
    assert "Jane Doe" in result.text_log


def test_form_filler_mock_auto_submit():
    filler = FormFiller(mock_mode=True, auto_submit=True)
    result = filler.fill_application(_job())

    assert result.success is True
    assert result.submitted is True


def test_backwards_compatible_boolean_wrapper():
    filler = FormFiller(mock_mode=True, auto_submit=True)
    assert filler.auto_fill_application(_job()) is True
