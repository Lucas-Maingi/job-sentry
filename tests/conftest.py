"""Shared test configuration: force mock/offline behaviour regardless of local .env."""

import pytest

from job_sentry.config import settings


@pytest.fixture(autouse=True)
def offline_settings(tmp_path, monkeypatch):
    """Keep tests deterministic: no real browser, no scheduler, isolated dirs."""
    monkeypatch.setattr(settings, "browser_mock", True)
    monkeypatch.setattr(settings, "browser_auto_submit", False)
    monkeypatch.setattr(settings, "auto_scan_interval_minutes", 0)
    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path / "uploads"))
    yield
