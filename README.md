# JobSentry — Semi-Autonomous AI Job Copilot

[![CI](https://github.com/Lucas-Maingi/job-sentry/actions/workflows/ci.yml/badge.svg)](https://github.com/Lucas-Maingi/job-sentry/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

JobSentry is a semi-autonomous AI Job Application Copilot designed to automate the job search, triage, cover letter drafting, form-filling, and recruiter response tracking.

It leverages Google Search / Serper APIs to scan for open positions, matches listings against the user's resume, drafts custom cover letters, autofills applications via Playwright, and checks IMAP emails for recruiter replies.

---

## 🏗️ System Architecture

```
  +------------------+                   +--------------------+
  |   Search APIs    |                   |     JobSentry      |
  | (Google / Serper)|                   |   (FastAPI API)    |
  +--------+---------+                   +---------+----------+
           |                                       |
           | 1. Scrapes listings                   |
           +-------------------------------------->+
           |                                       | 2. Scrape match & draft letters (LLM)
           |                                       v
           |                               +-------+--------+
           |                               |  Kanban Board  |
           |                               +-------+--------+
           |                                       |
           |                                       | 3. Operator clicks Apply
           |                                       v
           | 4. Auto-Fill application (Playwright) |
           +<--------------------------------------+
           |
           | 5. Poll Recruiter replies (IMAP email checks)
           +--------------------------------------> (Mark Interview/Refused)
```

### Safety Protocol Layers:
1.  **Job Scrape & Score**: Jobs are discovered and evaluated (0-100 score). Matches scoring $<60\%$ are flagged as low priority.
2.  **Drafting Phase**: Matches scoring $\ge 60\%$ are prepared in the `DRAFTING` column, automatically drafting Cover Letters and answering custom application questions.
3.  **Human-in-the-Loop Apply**: Playwright form submittal triggers upon user review of drafts. Operators click "Trigger Playwright Apply" to launch the browser session.
4.  **IMAP Response Monitor**: Continuous checks for incoming recruiter emails, auto-advancing statuses to `INTERVIEWING`, `REJECTED`, or `OFFER` columns.

---

## 🚀 Running the System

### Prerequisites:
- Python 3.10+
- Installed packages: `pip install -e ".[dashboard,dev]"`
- Playwright browsers: `playwright install chromium`

### 1. Launch SentryJob Central API (Port 8000):
```bash
python -m uvicorn job_sentry.app:app --host 127.0.0.1 --port 8000
```

### 2. Launch the Streamlit Kanban Board Console (Port 8501):
```bash
streamlit run job_sentry/dashboard.py
```

### 3. Deploy via Docker Compose:
```bash
docker-compose up --build
```
This boots both the API (`copilot`) and the Streamlit Kanban dashboard console (`console`) connected on a shared database volume.

---

## 🔌 API Documentation

### 1. Trigger Search Scan:
`POST /search`
```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": "AI Application Engineer",
    "location_filter": "Remote"
  }'
```

### 2. Trigger Playwright Submission:
`POST /jobs/{job_id}/apply`
```bash
curl -X POST http://127.0.0.1:8000/jobs/83cf92b1/apply
```

### 3. Sync Email Statuses:
`POST /emails/refresh`
```bash
curl -X POST http://127.0.0.1:8000/emails/refresh
```

---

## 🧪 Testing

```bash
# Run the full test suite (14 passing tests)
pytest tests/ -v
```

---

## 📝 License
MIT.
