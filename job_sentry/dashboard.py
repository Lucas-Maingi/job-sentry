"""Streamlit Operations Console for JobSentry.

Multi-user job application command center. Candidates register a profile
(resume + search defaults), trigger AI-triaged job scrapes, review drafted
cover letters, fire real Playwright form-fills with proof screenshots, and
track every application through Discovered → Drafting → Applied →
Interviewing → Offer with a full stage-history timeline.

All data flows through the FastAPI backend — run `uvicorn job_sentry.app:app`
before launching this console.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from job_sentry.config import settings
from job_sentry.models import JobStatus

# ── Page & Theme ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="JobSentry Console",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = """
<style>
    /* Remove Streamlit chrome entirely: no toolbar overlay, no clipped hero,
       and the app owns the full viewport like a real product. */
    #MainMenu, footer,
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    .stAppDeployButton { display: none !important; }
    .block-container { padding-top: 0.9rem; padding-bottom: 0.4rem; max-width: 100%; }

    /* Responsive fixed-height panes: Python sets a fallback px height, then an
       invisible .js-pane-* marker inside each pane lets us retarget the exact
       container and stretch it to the viewport edge — no wasted space, no page
       scroll, on any screen size. Streamlit sizes these via `flex: 0 0 <h>px`,
       so flex-basis (not height) is the property that must be overridden. */
    .js-pane-board, .js-pane-detail { display: none; }
    div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .js-pane-board) {
        flex-basis: calc(100vh - 278px) !important;
        height: calc(100vh - 278px) !important;
        min-height: 300px;
    }
    div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .js-pane-detail) {
        flex-basis: calc(100vh - 330px) !important;
        height: calc(100vh - 330px) !important;
        min-height: 340px;
    }

    /* Tighter vertical rhythm between stacked elements */
    div[data-testid="stVerticalBlock"] { gap: 0.65rem; }

    .js-hero {
        background: linear-gradient(120deg, #101c3d 0%, #1c3a72 55%, #2563eb 100%);
        border-radius: 12px;
        padding: 14px 22px;
        margin-bottom: 10px;
        color: #f5f7ff;
        display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
    }
    .js-hero h1 { margin: 0; font-size: 1.45rem; color: #ffffff; display: inline; }
    .js-hero p  { margin: 0; opacity: 0.85; font-size: 0.85rem; display: inline; }

    .js-pill {
        display: inline-block; padding: 1px 9px; border-radius: 999px;
        font-size: 0.7rem; font-weight: 600; letter-spacing: 0.02em;
    }
    .js-pill-discovered   { background: #e2e8f0; color: #334155; }
    .js-pill-drafting     { background: #fef3c7; color: #92400e; }
    .js-pill-applied      { background: #dbeafe; color: #1d4ed8; }
    .js-pill-interviewing { background: #ede9fe; color: #6d28d9; }
    .js-pill-rejected     { background: #fee2e2; color: #b91c1c; }
    .js-pill-offer        { background: #dcfce7; color: #15803d; }
    .js-pill-archived     { background: #f1f5f9; color: #64748b; }

    /* Compact kanban card typography with clamped title lines */
    .js-card-title {
        font-weight: 600; font-size: 0.86rem; line-height: 1.25;
        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .js-company { color: #94a3b8; font-size: 0.75rem;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
    .js-salary { color: #22c55e; font-weight: 700; font-size: 0.75rem; }
    .js-score-hi  { color: #22c55e; font-weight: 700; font-size: 0.78rem; }
    .js-score-mid { color: #f59e0b; font-weight: 700; font-size: 0.78rem; }
    .js-score-lo  { color: #94a3b8; font-weight: 700; font-size: 0.78rem; }

    div[data-testid="stMetric"] {
        background: rgba(37, 99, 235, 0.07);
        border: 1px solid rgba(37, 99, 235, 0.18);
        border-radius: 10px; padding: 6px 14px;
    }
    div[data-testid="stMetric"] label { font-size: 0.78rem; }
    div[data-testid="stMetricValue"] { font-size: 1.35rem; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

STAGE_LABELS = {
    JobStatus.DISCOVERED.value: "🔍 Discovered",
    JobStatus.DRAFTING.value: "✍️ Drafting",
    JobStatus.APPLIED.value: "📨 Applied",
    JobStatus.INTERVIEWING.value: "🎙️ Interviewing",
    JobStatus.REJECTED.value: "🚫 Rejected",
    JobStatus.OFFER.value: "🏆 Offer",
    JobStatus.ARCHIVED.value: "🗄️ Archived",
}

# Sentinel heights: the CSS above rewrites these to calc(100vh - N) so panes
# always fit the viewport. Keep the values unique — they double as selectors.
BOARD_HEIGHT = 521
DETAIL_HEIGHT = 601


def status_pill(status: str) -> str:
    label = STAGE_LABELS.get(status, status).split(" ", 1)[-1]
    return f"<span class='js-pill js-pill-{status}'>{label}</span>"


def score_span(score: float) -> str:
    cls = "js-score-hi" if score >= 75 else "js-score-mid" if score >= 60 else "js-score-lo"
    return f"<span class='{cls}'>{score:.0f}%</span>"


def fmt_ts(iso_ts: str | None) -> str:
    if not iso_ts:
        return "—"
    try:
        return datetime.fromisoformat(iso_ts).strftime("%d %b %Y, %H:%M")
    except (ValueError, TypeError):
        return str(iso_ts)


def artifact_url(local_path: str | None) -> str | None:
    """Map a server-side screenshot path onto the API's /artifacts mount."""
    if not local_path:
        return None
    return f"{API}/artifacts/{Path(local_path).name}"


# ── API Client ───────────────────────────────────────────────────────────

with st.sidebar.expander("⚙️ Connection", expanded=False):
    api_url = st.text_input("API URL", f"http://127.0.0.1:{settings.port}")
API = api_url.rstrip("/")


def api_get(path: str, **params) -> Any:
    resp = httpx.get(f"{API}{path}", params=params or None, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def api_send(method: str, path: str, payload: dict | None = None, timeout: float = 180.0) -> Any:
    resp = httpx.request(method, f"{API}{path}", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def error_detail(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            detail = e.response.json().get("detail", "")
            if isinstance(detail, dict):
                return detail.get("message", str(detail))
            return str(detail) or str(e)
        except Exception:
            return str(e)
    return str(e)


# ── Backend Health Gate ──────────────────────────────────────────────────

try:
    api_get("/health")
except Exception:
    st.markdown(
        "<div class='js-hero'><h1>🛰️ JobSentry</h1>"
        "<p>Semi-autonomous job search, application, and pipeline tracking.</p></div>",
        unsafe_allow_html=True,
    )
    st.error(
        f"Cannot reach the JobSentry API at `{API}`.\n\n"
        "Start the backend first:\n```\nuvicorn job_sentry.app:app --port 8000\n```"
    )
    st.stop()

# ── Sidebar: Account Selection / Registration ────────────────────────────

st.sidebar.markdown("## 👤 Account")
users = api_get("/users")

selected_user = None
if users:
    labels = {f"{u['name']} ({u['email']})": u for u in users}
    choice = st.sidebar.selectbox("Active profile", list(labels.keys()))
    selected_user = labels[choice]

with st.sidebar.expander("➕ New profile", expanded=not users), st.form("new_profile", clear_on_submit=True):
    np_name = st.text_input("Full name")
    np_email = st.text_input("Email")
    np_phone = st.text_input("Phone (optional)")
    np_keywords = st.text_input("Target roles / keywords", "AI Application Engineer Remote")
    np_location = st.text_input("Preferred location", "Remote")
    np_resume = st.text_area("Resume / skills summary", height=120,
                             placeholder="Paste your resume text — the AI scores every job against this.")
    if st.form_submit_button("Create profile", use_container_width=True):
        if not np_name or not np_email:
            st.warning("Name and email are required.")
        else:
            try:
                api_send("POST", "/users", {
                    "name": np_name, "email": np_email, "phone": np_phone,
                    "resume_text": np_resume,
                    "default_keywords": np_keywords, "default_location": np_location,
                })
                st.toast(f"Profile created for {np_name}!", icon="🎉")
                st.rerun()
            except Exception as e:
                st.error(f"Could not create profile: {error_detail(e)}")

# ── Hero Header ──────────────────────────────────────────────────────────

hero_sub = (
    f"Signed in as <b>{selected_user['name']}</b> · semi-autonomous search, apply & tracking"
    if selected_user else
    "Create a profile in the sidebar to start your automated job hunt."
)
st.markdown(
    f"<div class='js-hero'><h1>🛰️ JobSentry</h1><p>{hero_sub}</p></div>",
    unsafe_allow_html=True,
)

if not selected_user:
    st.info("👈 Register your first profile in the sidebar — name, email, and a resume summary are all it takes.")
    st.stop()

USER_ID = selected_user["user_id"]

# ── Sidebar: Copilot Controls ────────────────────────────────────────────

st.sidebar.markdown("---")
st.sidebar.markdown("## 🤖 Copilot Controls")
search_keywords = st.sidebar.text_input("Keywords", selected_user.get("default_keywords") or "AI Engineer")
search_location = st.sidebar.text_input("Location", selected_user.get("default_location") or "Remote")

if st.sidebar.button("🔍 Scan for new jobs", use_container_width=True, type="primary"):
    try:
        api_send("POST", f"/users/{USER_ID}/search",
                 {"keywords": search_keywords, "location_filter": search_location})
        st.toast("Search queued! AI triage runs in the background — refresh in ~30s.", icon="🔍")
    except Exception as e:
        st.sidebar.error(f"Search failed: {error_detail(e)}")

auto_submit = st.sidebar.toggle(
    "Auto-submit after filling",
    value=False,
    help="Off (recommended): the copilot fills the form and captures a proof screenshot; "
         "you review and confirm. On: it clicks Submit for you.",
)

if st.sidebar.button("✉️ Sync recruiter emails", use_container_width=True):
    try:
        result = api_send("POST", "/emails/refresh", timeout=60.0)
        st.toast(f"Inbox synced — {result.get('updates_found', 0)} update(s) found.", icon="✉️")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Email sync failed: {error_detail(e)}")

if st.sidebar.button("🔄 Refresh dashboard", use_container_width=True):
    st.rerun()

if settings.auto_scan_interval_minutes > 0:
    st.sidebar.caption(
        f"🛰️ Autonomous scanner: re-scans all profiles every "
        f"{settings.auto_scan_interval_minutes} min."
    )

# ── Load This User's Pipeline ────────────────────────────────────────────

jobs: list[dict] = api_get(f"/users/{USER_ID}/jobs")
jobs_df = pd.DataFrame(jobs) if jobs else pd.DataFrame()
if not jobs_df.empty:
    # pandas turns JSON nulls into NaN, which is truthy in Python and renders
    # as the literal string "nan" — normalise every missing value back to None.
    jobs_df = jobs_df.astype(object).where(pd.notna(jobs_df), None)

# ── KPI Row ──────────────────────────────────────────────────────────────

def count(status: str) -> int:
    if jobs_df.empty:
        return 0
    return int((jobs_df["status"] == status).sum())

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("In Triage", count("discovered") + count("drafting"),
          help="Discovered listings plus drafts awaiting your review")
k2.metric("Applied", count("applied"))
k3.metric("Interviewing", count("interviewing"))
k4.metric("Offers", count("offer"))
active = len(jobs_df) - count("rejected") - count("archived") if not jobs_df.empty else 0
k5.metric("Active in pipeline", active)

# ── Card Actions ─────────────────────────────────────────────────────────

def run_apply(job_id: str) -> None:
    with st.spinner("Launching browser — filling the application form..."):
        try:
            report = api_send("POST", f"/jobs/{job_id}/apply", {"auto_submit": auto_submit})
            if report.get("submitted"):
                st.toast("Application submitted! Proof screenshot saved.", icon="🚀")
            else:
                st.toast("Form filled & screenshotted — review in Job Details, then confirm.", icon="📸")
            st.rerun()
        except Exception as e:
            st.error(f"Apply failed: {error_detail(e)}")


def move_stage(job_id: str, new_stage: str) -> None:
    api_send("POST", f"/jobs/{job_id}/status", {"status": new_stage})
    st.toast(f"Moved to {STAGE_LABELS.get(new_stage, new_stage)}", icon="✅")
    st.rerun()


def render_card(row: pd.Series, stage: str) -> None:
    with st.container(border=True):
        salary_html = (
            f" · <span class='js-salary'>💰 {row['salary']}</span>"
            if row.get("salary") else ""
        )
        proof = " 📸" if row.get("screenshot_path") else ""
        st.markdown(
            f"<div class='js-card-title'>{row['title']}</div>"
            f"<span class='js-company'>{row['company']} · {row['location']}</span>"
            f"{score_span(row['match_score'])}{salary_html}{proof}",
            unsafe_allow_html=True,
        )
        with st.popover("Actions", use_container_width=True):
            st.markdown(f"**{row['title']}**")
            st.caption(row["match_reasoning"] or "No reasoning recorded.")
            st.markdown(f"[Open listing ↗]({row['url']})")

            if stage == JobStatus.DRAFTING.value:
                cl = st.text_area(
                    "Cover letter draft", value=row.get("cover_letter") or "",
                    height=140, key=f"cl_{row['job_id']}",
                )
                c1, c2 = st.columns(2)
                if c1.button("💾 Save letter", key=f"save_{row['job_id']}", use_container_width=True):
                    api_send("PUT", f"/jobs/{row['job_id']}/cover_letter", {"cover_letter": cl})
                    st.toast("Cover letter saved.", icon="💾")
                if c2.button("🚀 Fill application", key=f"apply_{row['job_id']}",
                             use_container_width=True, type="primary"):
                    run_apply(row["job_id"])
                if row.get("apply_log") and st.button(
                    "✅ Confirm submitted", key=f"conf_{row['job_id']}", use_container_width=True
                ):
                    move_stage(row["job_id"], JobStatus.APPLIED.value)

            new_stage = st.selectbox(
                "Move to stage",
                [""] + [s.value for s in JobStatus if s.value != stage],
                key=f"mv_{row['job_id']}",
                format_func=lambda v: "Select…" if v == "" else STAGE_LABELS.get(v, v),
            )
            if new_stage and st.button("Confirm move", key=f"mvbtn_{row['job_id']}",
                                       use_container_width=True):
                move_stage(row["job_id"], new_stage)


# ── Tabs ─────────────────────────────────────────────────────────────────

tab_board, tab_tracker, tab_detail, tab_profile = st.tabs(
    ["📌 Pipeline Board", "📋 Applications Tracker", "🔎 Job Details", "👤 My Profile"]
)

# ── Tab 1: Kanban Pipeline Board (fixed height, columns scroll inside) ───

with tab_board:
    if jobs_df.empty:
        st.info("No jobs in your pipeline yet. Hit **Scan for new jobs** in the sidebar to let the copilot hunt for you.")
    else:
        board_stages = [
            JobStatus.DISCOVERED.value, JobStatus.DRAFTING.value, JobStatus.APPLIED.value,
            JobStatus.INTERVIEWING.value, JobStatus.OFFER.value, JobStatus.REJECTED.value,
        ]
        st_cols = st.columns(len(board_stages), gap="small")

        for idx, stage in enumerate(board_stages):
            with st_cols[idx]:
                stage_jobs = jobs_df[jobs_df["status"] == stage]
                st.markdown(f"###### {STAGE_LABELS[stage]} · {len(stage_jobs)}")
                with st.container(height=BOARD_HEIGHT, border=False):
                    st.markdown("<span class='js-pane-board'></span>", unsafe_allow_html=True)
                    if stage_jobs.empty:
                        st.caption("Empty")
                    else:
                        for _, row in stage_jobs.sort_values("match_score", ascending=False).iterrows():
                            render_card(row, stage)

# ── Tab 2: Applications Tracker Table ────────────────────────────────────

with tab_tracker:
    if jobs_df.empty:
        st.info("Nothing tracked yet — run a scan first.")
    else:
        fcol, _ = st.columns([3, 1])
        stage_filter = fcol.multiselect(
            "Stages",
            options=list(STAGE_LABELS.keys()),
            default=["applied", "interviewing", "offer", "rejected"],
            format_func=lambda v: STAGE_LABELS.get(v, v),
            label_visibility="collapsed",
        )
        view = jobs_df[jobs_df["status"].isin(stage_filter)] if stage_filter else jobs_df

        if view.empty:
            st.warning("No applications in the selected stages yet. Apply to drafted jobs from the Pipeline Board.")
        else:
            table = view.copy()
            table["stage"] = table["status"].map(lambda s: STAGE_LABELS.get(s, s))
            table["match"] = table["match_score"].map(lambda s: f"{s:.0f}%")
            table["salary"] = table["salary"].map(lambda v: v or "Not listed")
            table["applied on"] = table["applied_at"].map(fmt_ts)
            table["last update"] = table["updated_at"].map(fmt_ts)

            st.dataframe(
                table[["company", "title", "stage", "match", "salary", "location", "applied on", "last update", "url"]]
                .rename(columns={"company": "Company", "title": "Role", "stage": "Stage",
                                 "match": "Match", "salary": "Salary", "location": "Location",
                                 "applied on": "Applied On", "last update": "Last Update", "url": "Listing"}),
                use_container_width=True,
                hide_index=True,
                height=min(46 + 35 * len(table), 560),
                column_config={"Listing": st.column_config.LinkColumn("Listing", display_text="Open ↗")},
            )
            st.caption(f"{len(table)} application(s) shown · sorted by most recent update")

# ── Tab 3: Job Details & Stage Timeline ──────────────────────────────────

with tab_detail:
    if jobs_df.empty:
        st.info("No jobs to inspect yet.")
    else:
        options = {
            f"{r['title']} — {r['company']}": r["job_id"]
            for _, r in jobs_df.iterrows()
        }
        pick = st.selectbox("Inspect a job", list(options.keys()), label_visibility="collapsed")
        job_id = options[pick]
        job = api_get(f"/jobs/{job_id}")
        history = api_get(f"/jobs/{job_id}/history")

        left, right = st.columns([3, 2], gap="medium")

        with left, st.container(height=DETAIL_HEIGHT, border=False):
            st.markdown("<span class='js-pane-detail'></span>", unsafe_allow_html=True)
            st.markdown(f"### {job['title']}")
            st.markdown(
                f"{status_pill(job['status'])} &nbsp; {score_span(job['match_score'])} match",
                unsafe_allow_html=True,
            )
            m1, m2 = st.columns(2)
            m1.markdown(f"**🏢 Company**<br>{job['company']}", unsafe_allow_html=True)
            m2.markdown(f"**📍 Location**<br>{job['location']}", unsafe_allow_html=True)
            m3, m4 = st.columns(2)
            m3.markdown(f"**💰 Salary**<br>{job.get('salary') or 'Not listed'}", unsafe_allow_html=True)
            m4.markdown(f"**🔗 Listing**<br>[Open ↗]({job['url']})", unsafe_allow_html=True)

            st.markdown("**📝 Description**")
            st.write(job["description"] or "No description captured.")
            st.markdown("**🤖 AI Match Reasoning**")
            st.write(job["match_reasoning"] or "Not evaluated.")

            if job.get("cover_letter"):
                with st.expander("✍️ Drafted cover letter"):
                    st.text(job["cover_letter"])
            if job.get("custom_answers"):
                with st.expander("🗒️ Drafted application answers"):
                    for q, a in job["custom_answers"].items():
                        st.markdown(f"**{q}**")
                        st.write(a)

        with right, st.container(height=DETAIL_HEIGHT, border=False):
            st.markdown("<span class='js-pane-detail'></span>", unsafe_allow_html=True)
            shot = artifact_url(job.get("screenshot_path"))
            if shot:
                st.markdown("#### 📸 Form-Fill Proof")
                st.image(shot, use_container_width=True)
            if job.get("apply_log"):
                with st.expander("🧾 Form-fill run log", expanded=not shot):
                    st.code(job["apply_log"], language=None)

            st.markdown("#### 📅 Stage Timeline")
            if not history:
                st.caption("No stage transitions recorded yet.")
            for event in reversed(history):
                st.markdown(
                    f"{status_pill(event['status'])} "
                    f"<small>{fmt_ts(event['occurred_at'])} — {event.get('note', '')}</small>",
                    unsafe_allow_html=True,
                )

# ── Tab 4: Profile Editor ────────────────────────────────────────────────

with tab_profile:
    pcol, rcol = st.columns([3, 2], gap="large")

    with pcol:
        st.markdown("##### Candidate profile")
        st.caption("The AI copilot scores every scraped job against this resume and signs cover letters with your name.")
        with st.form("edit_profile"):
            ep_name = st.text_input("Full name", selected_user["name"])
            ep_email = st.text_input("Email", selected_user["email"])
            ep_phone = st.text_input("Phone", selected_user.get("phone") or "")
            ep_keywords = st.text_input("Default keywords", selected_user.get("default_keywords") or "")
            ep_location = st.text_input("Default location", selected_user.get("default_location") or "")
            ep_resume = st.text_area("Resume / skills summary", selected_user.get("resume_text") or "", height=180)
            if st.form_submit_button("Save profile", type="primary"):
                try:
                    api_send("PUT", f"/users/{USER_ID}", {
                        "name": ep_name, "email": ep_email, "phone": ep_phone,
                        "resume_text": ep_resume,
                        "default_keywords": ep_keywords, "default_location": ep_location,
                    })
                    st.toast("Profile updated!", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {error_detail(e)}")

    with rcol:
        st.markdown("##### Resume file")
        current = selected_user.get("resume_path") or ""
        if current:
            st.success(f"On file: `{Path(current).name}` — attached to every form-fill.")
        else:
            st.info("No resume file yet. Upload one so the copilot can attach it to applications.")
        uploaded = st.file_uploader("Upload resume", type=["pdf", "doc", "docx", "txt"],
                                    label_visibility="collapsed")
        if uploaded is not None and st.button("📎 Save resume file", use_container_width=True, type="primary"):
            try:
                resp = httpx.post(
                    f"{API}/users/{USER_ID}/resume",
                    files={"file": (uploaded.name, uploaded.getvalue())},
                    timeout=60.0,
                )
                resp.raise_for_status()
                st.toast("Resume uploaded!", icon="📎")
                st.rerun()
            except Exception as e:
                st.error(f"Upload failed: {error_detail(e)}")
