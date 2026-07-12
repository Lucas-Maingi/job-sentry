from job_sentry.models import Job, UserProfile
from job_sentry.resume import generate_tailored_resume


def profile(resume_text="Python and FastAPI engineer. Built RAG pipelines with Docker and AWS."):
    return UserProfile(name="Lucas Maingi", email="lucas@example.com", phone="+254700000000", resume_text=resume_text)


def job(title="AI Engineer", description="We need Python, FastAPI, RAG, and Docker experience."):
    return Job(title=title, company="Acme", location="Remote", description=description, url="http://x")


class TestTemplateFallback:
    def test_returns_plain_text_with_standard_sections(self):
        # No api_key -> template path
        out = generate_tailored_resume(profile(), job(), api_key="")
        assert "SUMMARY" in out
        assert "SKILLS" in out
        assert "EXPERIENCE" in out or "PROJECTS" in out

    def test_is_ats_plain_no_markdown_or_tables(self):
        out = generate_tailored_resume(profile(), job(), api_key="")
        assert "|" not in out          # no tables
        assert "```" not in out         # no code fences
        assert "<" not in out           # no html/graphics

    def test_header_has_name_and_contact(self):
        out = generate_tailored_resume(profile(), job(), api_key="")
        assert "LUCAS MAINGI" in out
        assert "lucas@example.com" in out

    def test_summary_echoes_jd_keywords_present_in_resume(self):
        out = generate_tailored_resume(profile(), job(), api_key="").lower()
        # 'fastapi' and 'rag' appear in both the resume and the JD -> should surface
        assert "fastapi" in out
        assert "rag" in out

    def test_does_not_fabricate_absent_skills(self):
        # 'kubernetes' is in neither the resume nor JD; it must not be injected
        out = generate_tailored_resume(profile(), job(), api_key="").lower()
        assert "kubernetes" not in out

    def test_empty_master_resume_still_returns_something(self):
        out = generate_tailored_resume(profile(resume_text=""), job(), api_key="")
        assert isinstance(out, str) and out
