"""Streamlit Operations Console for JobSentry.

Exposes a Kanban board pipeline showing job applications from Discovered through
Drafting, Applied, Interviewing, and Offers. Includes interactive buttons to trigger
search scrapes, edit cover letters, run Playwright automations, and check emails.
"""

from __future__ import annotations

import sqlite3
import pandas as pd
import streamlit as st
import httpx

from job_sentry.config import settings
from job_sentry.models import JobStatus

# Configure Streamlit page layout
st.set_page_config(
    page_title="JobSentry Console",
    page_icon="💼",
    layout="wide"
)

st.title("💼 JobSentry — Application Copilot")
st.markdown("AI-augmented autonomous job application aggregator, form-filler, and tracking console.")

db_path = st.sidebar.text_input("SQLite Database Path", "job_sentry.db")
api_url = st.sidebar.text_input("JobSentry API URL", f"http://127.0.0.1:{settings.port}")

# ── Data Fetching helpers ────────────────────────────────────────────────

def get_connection():
    return sqlite3.connect(db_path)

def load_jobs():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM jobs ORDER BY match_score DESC", conn)
    conn.close()
    return df

# ── Actions ──────────────────────────────────────────────────────────────

def trigger_search(keywords: str, location: str):
    try:
        url = f"{api_url.rstrip('/')}/search"
        resp = httpx.post(url, json={"keywords": keywords, "location_filter": location})
        if resp.status_code == 200:
            st.toast("Job scraping query successfully queued in background!", icon="🔍")
        else:
            st.error(f"Search failed: {resp.text}")
    except Exception as e:
        st.error(f"Error connecting to API: {str(e)}")

def trigger_apply(job_id: str):
    try:
        url = f"{api_url.rstrip('/')}/jobs/{job_id}/apply"
        with st.spinner("Launching Playwright form-filler task..."):
            resp = httpx.post(url, timeout=60.0)
            if resp.status_code == 200:
                st.success("Playwright auto-submit finished successfully!")
                st.rerun()
            else:
                st.error(f"Form submission failed: {resp.json().get('detail', resp.text)}")
    except Exception as e:
        st.error(f"Error during submission: {str(e)}")

def trigger_email_refresh():
    try:
        url = f"{api_url.rstrip('/')}/emails/refresh"
        with st.spinner("Connecting to IMAP server..."):
            resp = httpx.post(url, timeout=30.0)
            if resp.status_code == 200:
                updates = resp.json().get("updates_found", 0)
                st.toast(f"IMAP refresh completed! Found {updates} recruiter replies.", icon="✉️")
                st.rerun()
            else:
                st.error(f"Email sync failed: {resp.text}")
    except Exception as e:
        st.error(f"Error during sync: {str(e)}")

# ── Sidebar Control Panel ────────────────────────────────────────────────

st.sidebar.header("Aggregator Controls")
search_keywords = st.sidebar.text_input("Keywords", "AI Application Engineer")
search_location = st.sidebar.text_input("Location", "Remote")
if st.sidebar.button("Run Scraper Scans", use_container_width=True):
    trigger_search(search_keywords, search_location)
    
st.sidebar.markdown("---")
st.sidebar.header("Inbox Sync")
if st.sidebar.button("Refresh Recruiter Emails", use_container_width=True):
    trigger_email_refresh()

# ── Load Data ────────────────────────────────────────────────────────────

try:
    jobs_df = load_jobs()
except Exception as e:
    st.error(f"Failed to read database. Run a search scan to initialize the DB. Error: {str(e)}")
    st.stop()

# ── KPI Cards ────────────────────────────────────────────────────────────

if not jobs_df.empty:
    total_discovered = len(jobs_df)
    total_drafting = len(jobs_df[jobs_df["status"] == JobStatus.DRAFTING.value])
    total_applied = len(jobs_df[jobs_df["status"] == JobStatus.APPLIED.value])
    total_interviews = len(jobs_df[jobs_df["status"] == JobStatus.INTERVIEWING.value])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Jobs Discovered", total_discovered)
    with col2:
        st.metric("Pending Drafting", total_drafting)
    with col3:
        st.metric("Applied Listings", total_applied)
    with col4:
        st.metric("Active Interviews", total_interviews, delta="Recruiter Updates", delta_color="normal")
else:
    st.info("Zero jobs found in tracking pipeline. Trigger a search scan in the sidebar to populate.")
    st.stop()

# ── Kanban Columns ───────────────────────────────────────────────────────

st.subheader("Job Application Kanban Board Pipeline")

columns = {
    "Discovered": JobStatus.DISCOVERED.value,
    "Drafting / Review": JobStatus.DRAFTING.value,
    "Applied": JobStatus.APPLIED.value,
    "Interviewing": JobStatus.INTERVIEWING.value,
    "Rejected": JobStatus.REJECTED.value,
    "Offers Received": JobStatus.OFFER.value
}

st_cols = st.columns(len(columns))

for col_name, status_val in columns.items():
    col_idx = list(columns.keys()).index(col_name)
    with st_cols[col_idx]:
        st.markdown(f"#### {col_name}")
        st.markdown("---")
        
        # Filter jobs in this column
        sub_df = jobs_df[jobs_df["status"] == status_val]
        
        if not sub_df.empty:
            for _, row in sub_df.iterrows():
                job_id = row["job_id"]
                score = row["match_score"]
                
                # Card Container
                # Color score badge dynamically
                badge_color = "green" if score >= 75 else "orange" if score >= 60 else "gray"
                
                with st.container(border=True):
                    st.markdown(
                        f"**{row['title']}**<br>"
                        f"<small>{row['company']} — {row['location']}</small><br>"
                        f"<span style='color:{badge_color}; font-weight:bold;'>Match: {score:.0f}%</span>",
                        unsafe_allow_html=True
                    )
                    
                    # Expand details button
                    exp_key = f"details_{job_id}"
                    details_exp = st.expander("Expand Details")
                    with details_exp:
                        st.markdown("**Match Reasoning**")
                        st.write(row["match_reasoning"])
                        
                        st.markdown("**Application URL**")
                        st.write(row["url"])
                        
                        if status_val == JobStatus.DRAFTING.value:
                            st.markdown("**Drafted Cover Letter**")
                            st.text_area("Cover Letter", value=row["cover_letter"], height=150, key=f"cl_{job_id}")
                            
                            if st.button("Trigger Playwright Apply", key=f"apply_btn_{job_id}", use_container_width=True):
                                trigger_apply(job_id)
        else:
            st.caption("No jobs in this stage.")
