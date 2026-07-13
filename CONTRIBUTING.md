# Contributing to JobSentry

The extension points, in order of how often they're wanted: the form-fill engine's field detection, a new pipeline stage, or a new job source.

## Ground rules

- **The candidate's materials never lie.** Cover letters and ATS resumes are generated from the candidate's real resume only — the prompt in [job_sentry/resume.py](job_sentry/resume.py) forbids inventing employers, titles, dates, or skills, and any change to generation must keep that constraint testable.
- **Submit stays gated.** Playwright fills forms and captures a proof screenshot, but clicking Submit requires the explicit `auto_submit` flag. Features that widen autonomous submission need the evidence trail (screenshot + filled-field report) extended to match — the user must always be able to see exactly what was sent on their behalf.
- **Every stage transition is audited.** Anything that moves a job between stages goes through the status-event mechanism so `/jobs/{id}/history` stays a complete audit trail. No silent state changes.
- **Tests run keyless and browserless.** `JOBSENTRY_BROWSER_MOCK=1` and the LLM/search stubs exist so CI needs no Serper key, no Groq key, no Chromium. Keep new features testable that way.

## Improving form-fill field detection

The engine ([job_sentry/browser.py](job_sentry/browser.py)) detects fields by label text and attribute heuristics, with special handling for Greenhouse iframes. When adding support for a new ATS (Lever, Workday, Ashby...):

1. Add detection rules, not site-specific hacks — prefer "a label containing *phone* near an input" over hardcoded selectors, so the rule generalizes.
2. Ship an HTML fixture of the real form (scrubbed of tracking) under `tests/fixtures/` and a test asserting which fields get matched and what the fill report says.
3. Unrecognized fields must end up *listed as unfilled* in the apply report, never silently skipped — the human reviewing the proof screenshot needs to know what to fill by hand.

## Adding a job source

Sources feed the scan loop. A new one (an ATS API, an RSS feed, a jobs board) should return the same normalized job shape the Serper path produces, deduplicate against existing pipeline entries by URL/company+title, and respect the per-user eligibility filters *before* anything reaches the LLM triage — filtering after scoring burns tokens on jobs the candidate would never take.

## Running checks

```bash
pip install -e ".[dashboard,dev]"
JOBSENTRY_BROWSER_MOCK=1 pytest        # 48 tests, no keys or browsers needed
```

## Commit style

Small commits, present tense, explain *why* when the diff can't.
