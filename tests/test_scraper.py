"""Tests for the JobSentry Scraper and aggregator module."""

from job_sentry.scraper import JobScraper, extract_salary


def test_scraper_defaults_to_mock_when_no_key():
    scraper = JobScraper(serper_api_key="")
    assert scraper.mock_mode is True


def test_scraper_mock_search_returns_listings():
    scraper = JobScraper()
    jobs = scraper.search_jobs("AI Engineer")

    assert len(jobs) >= 1
    # Check that it returns valid Job schemas
    assert jobs[0].title is not None
    assert jobs[0].company is not None
    assert jobs[0].url.startswith("https://")


def test_scraper_mock_keyword_filtering():
    scraper = JobScraper()

    # Search specifically for WhatsApp
    whatsapp_jobs = scraper.search_jobs("WhatsApp")
    assert len(whatsapp_jobs) == 1
    assert "MobileM-Pesa" in whatsapp_jobs[0].company
    assert "WhatsApp" in whatsapp_jobs[0].title


def test_salary_extraction_patterns():
    assert extract_salary("Compensation: $140,000 - $170,000 per year") is not None
    assert extract_salary("Pay range £65,000 per annum") is not None
    assert extract_salary("$120k - $150k USD") is not None
    assert extract_salary("Join our fast-paced team!") is None


def test_mock_listings_carry_extracted_salary():
    scraper = JobScraper(serper_api_key="")
    jobs = scraper.search_jobs("RAG LangGraph")
    cognitive = [j for j in jobs if "CognitiveFlow" in j.company][0]
    assert cognitive.salary is not None
    assert "140,000" in cognitive.salary
