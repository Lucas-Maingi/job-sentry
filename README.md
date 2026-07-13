# JobSentry — Semi-Autonomous AI Job Copilot

[![CI](https://github.com/Lucas-Maingi/job-sentry/actions/workflows/ci.yml/badge.svg)](https://github.com/Lucas-Maingi/job-sentry/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

JobSentry is a **multi-user**, semi-autonomous AI Job Application Copilot that automates job search, AI triage, cover letter drafting, form-filling, and pipeline tracking.

Each candidate registers a profile (resume + search defaults). JobSentry scans Google via the Serper API for open positions, scores every listing against that candidate's resume with an LLM (Groq / any OpenAI-compatible endpoint), extracts salary and company details, drafts custom cover letters, autofills applications via Playwright, and tracks every application through a stage-history timeline — Discovered → Drafting → Applied → Interviewing → Offer.

---

## 🏗️ System Architecture

```
  +------------------+                   +--------------------+
  |   Search APIs    |                   |     JobSentry      |
  | (Google / Serper)|                   |   (FastAPI API)    |
  +--------+---------+                   +---------+----------+
           |                                       |
           | 1. Scrapes listings (per user)        |
           +-------------------------------------->+
           |                                       | 2. LLM match score + salary/company
           |                                       |    extraction + cover drafting (Groq)
           |                                       v
           |                               +-------+--------+
           |                               | Multi-User     |
           |                               | Console        |
           |                               | (Streamlit)    |
           |                               +-------+--------+
           |                                       |
           |                                       | 3. Operator reviews draft, clicks Apply
           |                                       v
           | 4. Auto-Fill application (Playwright, |
           |    candidate's own profile details)   |
           +<--------------------------------------+
           |
           | 5. Poll Recruiter replies (IMAP email checks)
           +--------------------------------------> (Stage history timeline updated)
```

### Safety Protocol Layers:
1.  **Job Scrape & Score**: Jobs are discovered and evaluated (0-100 score) against the owning candidate's resume, with **eligibility filters** (location, experience level, salary floor) pruning listings the candidate can't or won't take before any tokens are spent drafting for them. Matches scoring $<60\%$ are flagged as low priority.
2.  **Drafting Phase**: Matches scoring $\ge 60\%$ are prepared in the `DRAFTING` column, automatically drafting cover letters (signed with the candidate's name), answering custom application questions, and — per posting — generating an **ATS-tailored resume** that reorders and rephrases the candidate's real experience against the job's keywords (it never invents experience).
3.  **Human-in-the-Loop Apply**: Playwright opens the real posting, fills every recognisable field (name, contacts, cover letter, custom answers), uploads the candidate's resume file, and captures a proof screenshot. Clicking Submit is gated behind an explicit auto-submit flag — by default the candidate reviews the screenshot and confirms.
4.  **Autonomous Scanner**: A background loop re-scans and triages jobs for every registered profile on a configurable interval (default: every 6 hours).
5.  **IMAP Response Monitor**: Checks for incoming recruiter emails, auto-advancing statuses to `INTERVIEWING`, `REJECTED`, or `OFFER` — every transition is recorded in the job's stage-history audit trail.

---

## 🚀 Running the System

### Prerequisites:
- Python 3.10+
- Installed packages: `pip install -e ".[dashboard,dev]"`
- Playwright browsers: `playwright install chromium`
- Copy `.env.example` to `.env` and add your Serper + LLM keys (Groq works out of the box)
- Set `JOBSENTRY_BROWSER_MOCK=1` to simulate form fills on machines without Playwright browsers

### 1. Launch the JobSentry Central API (Port 8000):
```bash
python -m uvicorn job_sentry.app:app --host 127.0.0.1 --port 8000
```

### 2. Launch the Streamlit Console (Port 8501):
```bash
streamlit run job_sentry/dashboard.py
```
Register a profile in the sidebar, hit **Scan for new jobs**, and manage your pipeline across four views: **Pipeline Board** (kanban), **Applications Tracker** (company / role / stage / salary / dates table), **Job Details** (full description, AI reasoning, drafted materials, stage timeline), and **My Profile**.

### 3. Deploy via Docker Compose:
```bash
docker-compose up --build
```
This boots both the API (`copilot`) and the Streamlit console (`console`) connected on a shared database volume.

---

## 🔌 API Documentation

Interactive docs at `http://127.0.0.1:8000/docs`.

### Users
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/users` | Register a candidate profile (name, email, resume, search defaults) |
| `GET` | `/users` | List all profiles |
| `PUT` | `/users/{user_id}` | Update a profile |
| `POST` | `/users/{user_id}/resume` | Upload the resume file used in real form fills |

### Pipeline
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/users/{user_id}/search` | Queue a scrape + AI triage for one candidate |
| `GET` | `/users/{user_id}/jobs` | That candidate's pipeline (optional `?status=` filter) |
| `GET` | `/jobs/{job_id}` | Full job detail |
| `GET` | `/jobs/{job_id}/history` | Stage-transition audit trail |
| `POST` | `/jobs/{job_id}/status` | Manual stage move |
| `PUT` | `/jobs/{job_id}/cover_letter` | Save an edited cover letter draft |
| `POST` | `/jobs/{job_id}/resume` | Generate an ATS-tailored resume for this specific posting |
| `POST` | `/jobs/{job_id}/apply` | Real Playwright form fill (`{"auto_submit": true}` to also click Submit) |
| `POST` | `/emails/refresh` | Sync recruiter email replies |

Example — register and search:
```bash
curl -X POST http://127.0.0.1:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name": "Jane Doe", "email": "jane@example.com", "resume_text": "Python engineer...", "default_keywords": "Backend Engineer", "default_location": "Remote"}'

curl -X POST http://127.0.0.1:8000/users/<user_id>/search \
  -H "Content-Type: application/json" -d '{}'
```

---

## 🧪 Testing

```bash
# Run the full test suite (48 passing tests)
pytest tests/ -v
```

---

## ☁️ Running 24/7 (free)

The autonomous scanner is only useful if it's always on. [docs/DEPLOY_ORACLE.md](docs/DEPLOY_ORACLE.md) is a start-to-finish guide for running the full stack on an **Oracle Cloud Always-Free VM** with `docker-compose.prod.yml` — scanning and triaging for every registered profile around the clock at $0/month.

---

## 📝 License
MIT — see [LICENSE](LICENSE).
