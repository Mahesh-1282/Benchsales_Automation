import streamlit as st
import os
import sys
import subprocess
import json
from pathlib import Path
from db_utils import query_df, get_env_status
from syntara_styles import inject_styles
from ui_components import render_job_card

SEARCH_HISTORY_FILE = os.path.join(Path(__file__).parent.parent.parent, "search_history.json")

def get_search_history():
    if os.path.exists(SEARCH_HISTORY_FILE):
        try:
            with open(SEARCH_HISTORY_FILE, "r") as f:
                return json.load(f)
        except: pass
    return []

def add_search_history(term):
    if not term: return
    history = get_search_history()
    if term in history: history.remove(term)
    history.insert(0, term)
    with open(SEARCH_HISTORY_FILE, "w") as f:
        json.dump(history[:15], f)

inject_styles()

st.markdown("<h1 class='syntara-logo' style='font-size:36px;'>⚡ SYNTARA</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; margin-top:-8px; font-size:14px;'>AI-Powered Bench Sales Automation Platform</p>", unsafe_allow_html=True)

st.markdown("---")

# ── Stats row ──
c1, c2, c3, c4, c5 = st.columns(5)
try:
    stats = query_df(f"""
        SELECT
            (SELECT COUNT(*) FROM users WHERE is_active=true) AS users,
            (SELECT COUNT(*) FROM jobs_clean_silver WHERE active=true) AS active_jobs,
            (SELECT COUNT(*) FROM user_job_matches) AS total_matches,
            (SELECT COUNT(*) FROM generated_resumes WHERE is_latest=true) AS resumes,
            (SELECT COUNT(*) FROM job_submissions) AS applied
    """)
    if not stats.empty:
        r = stats.iloc[0]
        with c1: st.markdown(f"<div class='metric-card'><div class='value'>{r.get('users',0)}</div><div class='label'>👤 Users</div></div>", unsafe_allow_html=True)
        with c2: st.markdown(f"<div class='metric-card'><div class='value'>{r.get('active_jobs',0)}</div><div class='label'>💼 Active Jobs</div></div>", unsafe_allow_html=True)
        with c3: st.markdown(f"<div class='metric-card'><div class='value'>{r.get('total_matches',0)}</div><div class='label'>🎯 Matches</div></div>", unsafe_allow_html=True)
        with c4: st.markdown(f"<div class='metric-card'><div class='value'>{r.get('resumes',0)}</div><div class='label'>📄 Resumes</div></div>", unsafe_allow_html=True)
        with c5: st.markdown(f"<div class='metric-card'><div class='value'>{r.get('applied',0)}</div><div class='label'>📤 Applied</div></div>", unsafe_allow_html=True)
except Exception:
    with c1: st.markdown("<div class='metric-card'><div class='value'>—</div><div class='label'>👤 Users</div></div>", unsafe_allow_html=True)
    with c2: st.markdown("<div class='metric-card'><div class='value'>—</div><div class='label'>💼 Jobs</div></div>", unsafe_allow_html=True)
    with c3: st.markdown("<div class='metric-card'><div class='value'>—</div><div class='label'>🎯 Matches</div></div>", unsafe_allow_html=True)
    with c4: st.markdown("<div class='metric-card'><div class='value'>—</div><div class='label'>📄 Resumes</div></div>", unsafe_allow_html=True)
    with c5: st.markdown("<div class='metric-card'><div class='value'>—</div><div class='label'>📤 Applied</div></div>", unsafe_allow_html=True)

st.markdown("---")

# ── User Selection ──
users_df = query_df("SELECT user_id, full_name, ai_scraping_keywords FROM users WHERE is_active = 1")
user_id = st.session_state.get("current_user_id")

if not user_id and not users_df.empty:
    user_id = users_df.iloc[0]["user_id"]
    st.session_state["current_user_id"] = user_id
    
if users_df.empty:
    st.warning("No users found. Please go to **Onboarding** to create a profile.")
    st.stop()

opts = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
rev_opts = {v: k for k, v in opts.items()}

col1, col2 = st.columns([1, 2])
with col1:
    sel = st.selectbox("Active User:", list(opts.keys()), index=list(opts.keys()).index(rev_opts.get(user_id, list(opts.keys())[0])))
    st.session_state["current_user_id"] = opts[sel]
    user_id = opts[sel]

    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
    st.markdown("**Search for Jobs**")
    custom_kw = st.text_input("Enter New Search Keyword", placeholder="e.g. Python Developer")
    history = get_search_history()
    past_kw = st.selectbox("Or choose from history", ["Data Engineer"] + history)
    
    kw = custom_kw.strip() if custom_kw.strip() else past_kw
    if kw:
        add_search_history(kw)

# ── Local Scraper & Pipeline ──
with col2:
    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🕷️ Run Scraper", type="primary", use_container_width=True):
            st.session_state["run_scraper"] = True
    with b2:
        if st.button("⚙️ Run Matching Pipeline", use_container_width=True):
            with st.spinner("Running pipeline (Bronze -> Silver -> Matching)..."):
                pipeline_script = os.path.join(Path(__file__).parent.parent, "local_pipeline.py")
                p = subprocess.run([sys.executable, pipeline_script], capture_output=True, text=True)
                if p.returncode == 0:
                    st.success("✅ Pipeline Complete!")
                else:
                    st.error(f"❌ Pipeline Failed: {p.stderr}")

if st.session_state.get("run_scraper", False):
    st.markdown("### 📜 Live Scraping Logs")
    log_container = st.empty()
    scraper_script = os.path.join(Path(__file__).parent.parent.parent, "01_local_scraper", "job_scrapper.py")
    env = os.environ.copy()
    if kw:
        env["SCRAPER_KEYWORDS"] = kw
    
    process = subprocess.Popen([sys.executable, scraper_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    logs = []
    for line in iter(process.stdout.readline, ''):
        logs.append(line)
        log_container.code("".join(logs[-50:]), language="bash")
        
    process.stdout.close()
    process.wait()
    st.session_state["run_scraper"] = False
    
    if process.returncode == 0:
        st.success("✅ Scraping Complete! Click 'Run Matching Pipeline' to see matches.")
    else:
        st.error(f"❌ Scraping Failed with code {process.returncode}")
    if st.button("🔄 Close Logs"):
        st.rerun()

st.markdown("---")

# ── Matched Job Cards ──
st.markdown("<h3 style='margin-bottom:16px;'>🎯 Top Job Matches</h3>", unsafe_allow_html=True)

jobs_df = query_df(f"""
    SELECT
        m.match_id, m.match_score, m.status,
        j.job_hash, j.job_title, j.company_name, j.location, j.remote_type,
        j.salary_range, j.tech_stack, j.apply_link, j.job_description, j.portal, j.posted_date
    FROM user_job_matches m
    JOIN jobs_clean_silver j ON m.job_hash = j.job_hash
    WHERE m.user_id = '{user_id}'
    ORDER BY m.match_score DESC
    LIMIT 20
""")

if jobs_df.empty:
    st.info("No job matches found. Try running the Scraper and Pipeline.")
else:
    for _, job in jobs_df.iterrows():
        render_job_card(job, user_id)
