from job_sentry.filters import eligible, location_eligible, salary_ok, stated_salary_usd
from job_sentry.models import Job


def job(title="Engineer", location="Remote", description="", salary=None):
    return Job(title=title, company="Acme", location=location, description=description, url="http://x", salary=salary)


class TestLocationEligible:
    def test_any_mode_keeps_everything(self):
        ok, _ = location_eligible(job(location="On-site, Berlin"), "any")
        assert ok

    def test_remote_mode_keeps_open_remote(self):
        ok, _ = location_eligible(job(location="Remote", description="fully remote, worldwide"), "remote")
        assert ok

    def test_remote_mode_rejects_region_locked(self):
        ok, reason = location_eligible(
            job(location="Remote", description="Remote (US only). Must be authorized to work in the US."),
            "remote",
        )
        assert ok is False
        assert "region-locked" in reason

    def test_remote_mode_rejects_pure_onsite_elsewhere(self):
        ok, _ = location_eligible(job(location="Amsterdam", description="on-site position, hybrid 3 days"), "remote")
        assert ok is False

    def test_remote_mode_keeps_local_nairobi(self):
        ok, _ = location_eligible(job(location="Nairobi, Kenya", description="on-site"), "remote")
        assert ok  # you can do a local job in person

    def test_nairobi_mode_keeps_kenya_roles(self):
        ok, _ = location_eligible(job(location="Nairobi", description="hybrid"), "nairobi")
        assert ok

    def test_nairobi_mode_keeps_open_remote(self):
        ok, _ = location_eligible(job(location="Remote", description="work anywhere"), "nairobi")
        assert ok

    def test_nairobi_mode_rejects_foreign_onsite(self):
        ok, _ = location_eligible(job(location="London", description="on-site only"), "nairobi")
        assert ok is False


class TestSalary:
    def test_parses_comma_number(self):
        assert stated_salary_usd(job(salary="$120,000 - $150,000")) == 120000

    def test_parses_k_notation(self):
        assert stated_salary_usd(job(salary="$90k")) == 90000

    def test_none_when_absent(self):
        assert stated_salary_usd(job(salary=None)) is None

    def test_salary_ok_keeps_when_unknown(self):
        ok, _ = salary_ok(job(salary=None), 100000)
        assert ok  # never exclude for unknown pay

    def test_salary_ok_rejects_below_floor(self):
        ok, _ = salary_ok(job(salary="$40,000"), 80000)
        assert ok is False

    def test_salary_ok_accepts_above_floor(self):
        ok, _ = salary_ok(job(salary="$120k"), 80000)
        assert ok


class TestCombinedGate:
    def test_eligible_requires_both(self):
        ok, _ = eligible(
            job(location="Remote", description="worldwide", salary="$120k"),
            location_mode="remote", min_salary_usd=80000,
        )
        assert ok

    def test_ineligible_on_location_short_circuits(self):
        ok, reason = eligible(
            job(location="Berlin", description="on-site", salary="$200k"),
            location_mode="remote", min_salary_usd=80000,
        )
        assert ok is False
        assert reason.startswith("location:")
