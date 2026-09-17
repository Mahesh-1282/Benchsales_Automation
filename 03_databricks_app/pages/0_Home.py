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

# ── Top Header ──
users_df = query_df("SELECT user_id, full_name, ai_scraping_keywords FROM users WHERE is_active = 1")
opts = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()} if not users_df.empty else {}
user_id = st.session_state.get("current_user_id")
if not user_id and opts:
    user_id = list(opts.values())[0]
    st.session_state["current_user_id"] = user_id

col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
with col_c1:
    st.markdown("<div style='display:flex; align-items:center; gap:8px; margin-top:16px;'><span style='font-size:12px; font-weight:700; color:#94a3b8; text-transform:uppercase;'>CANDIDATE:</span></div>", unsafe_allow_html=True)
    if opts:
        rev_opts = {v: k for k, v in opts.items()}
        sel = st.selectbox("Candidate", list(opts.keys()), index=list(opts.keys()).index(rev_opts.get(user_id, list(opts.keys())[0])), label_visibility="collapsed", key="candidate_select")
        user_id = opts[sel]
        st.session_state["current_user_id"] = user_id
    else:
        st.warning("No users found. Go to Onboarding.")
        st.stop()
        
with col_c2:
    st.markdown("""
        <div style="display:flex; align-items:center; gap:8px; padding:6px 16px; background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; border-radius:9999px; font-size:12px; font-weight:600; width:max-content; margin-top:20px; float:right;">
            <span style="width:8px; height:8px; border-radius:50%; background:#10b981; animation: pulse 2s infinite;"></span>
            Agent Active & Listening
        </div>
    """, unsafe_allow_html=True)
    
with col_c3:
    u_name = sel.split(' ')[0] if opts else 'User'
    u_init = sel[:2].upper() if opts else 'UN'
    st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; margin-top:20px; justify-content:flex-end;">
            <div style="font-size:20px; color:#94a3b8; cursor:pointer; position:relative;">
                🔔
                <span style="position:absolute; top:-2px; right:-2px; width:8px; height:8px; background:#7c3aed; border-radius:50%; border:2px solid white;"></span>
            </div>
            <div style="display:flex; align-items:center; gap:8px; border-left:1px solid #e2e8f0; padding-left:12px;">
                <div style="width:32px; height:32px; border-radius:50%; background:#f5f3ff; border:1px solid #ddd6fe; color:#7c3aed; font-weight:700; display:flex; align-items:center; justify-content:center; font-size:12px;">
                    {u_init}
                </div>
                <span style="font-size:14px; font-weight:600; color:#334155;">{u_name}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:16px 0 24px 0;'/>", unsafe_allow_html=True)

# ── Hero Banner ──
hero_html = """
<div style="background: linear-gradient(to right, #4c1d95, #5b21b6, #312e81); border-radius: 16px; padding: 32px 40px; color: white; margin-bottom: 32px; position: relative; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);">
    <div style="position: relative; z-index: 10;">
        <div style="display: inline-flex; align-items: center; gap: 8px; padding: 4px 12px; background: rgba(255,255,255,0.1); backdrop-filter: blur(8px); border-radius: 9999px; font-size: 12px; font-weight: 500; color: #ddd6fe; margin-bottom: 16px; border: 1px solid rgba(255,255,255,0.1);">
            <span style="width: 6px; height: 6px; border-radius: 50%; background: #34d399;"></span>
            Agent Active • Bench Pipeline Synchronized
        </div>
        <h1 style="font-size: 36px; font-weight: 800; letter-spacing: -0.025em; color: white; margin: 0 0 8px 0;">
            AI Bench Sales Automation
        </h1>
        <p style="color: #ede9fe; font-size: 16px; margin: 0; max-width: 600px; line-height: 1.5;">
            Automated pipeline matching, daily multi-board job scraping, and customized 1-click tailored resumes.
        </p>
    </div>
    <div style="position: absolute; right: -40px; bottom: -40px; width: 250px; height: 250px; background: rgba(139,92,246,0.2); border-radius: 50%; filter: blur(40px); pointer-events: none;"></div>
</div>
"""
st.markdown(hero_html, unsafe_allow_html=True)

# ── Stats row ──
st.markdown("""
<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
    <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-size:12px; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Pipeline Snapshot</span>
        <span style="width:8px; height:8px; border-radius:50%; background:#10b981;"></span>
    </div>
    <span style="font-size:12px; font-weight:600; color:#7c3aed; cursor:pointer;">Live Updates</span>
</div>
""", unsafe_allow_html=True)

metric_tmpl = "<div style='background:{bg}; border:1px solid {border}; border-radius:16px; padding:20px; text-align:center; box-shadow:0 1px 2px rgba(0,0,0,0.02);'><div style='font-size:32px; font-weight:800; color:{vcolor};'>{value}</div><div style='margin-top:4px; font-size:12px; font-weight:600; color:{lcolor}; display:flex; align-items:center; justify-content:center; gap:6px;'>{icon} {label}</div></div>"

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
        with c1: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#6d28d9", lcolor="#64748b", value=r.get('users',0), icon="👤", label="USERS"), unsafe_allow_html=True)
        with c2: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#6d28d9", lcolor="#64748b", value=r.get('active_jobs',0), icon="💼", label="ACTIVE JOBS"), unsafe_allow_html=True)
        with c3: st.markdown(metric_tmpl.format(bg="#f5f3ff", border="#ddd6fe", vcolor="#7c3aed", lcolor="#6d28d9", value=r.get('total_matches',0), icon="🎯", label="MATCHES"), unsafe_allow_html=True)
        with c4: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#334155", lcolor="#64748b", value=r.get('resumes',0), icon="📄", label="RESUMES"), unsafe_allow_html=True)
        with c5: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#334155", lcolor="#64748b", value=r.get('applied',0), icon="🚀", label="APPLIED"), unsafe_allow_html=True)
except Exception:
    with c1: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#6d28d9", lcolor="#64748b", value="—", icon="👤", label="USERS"), unsafe_allow_html=True)
    with c2: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#6d28d9", lcolor="#64748b", value="—", icon="💼", label="ACTIVE JOBS"), unsafe_allow_html=True)
    with c3: st.markdown(metric_tmpl.format(bg="#f5f3ff", border="#ddd6fe", vcolor="#7c3aed", lcolor="#6d28d9", value="—", icon="🎯", label="MATCHES"), unsafe_allow_html=True)
    with c4: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#334155", lcolor="#64748b", value="—", icon="📄", label="RESUMES"), unsafe_allow_html=True)
    with c5: st.markdown(metric_tmpl.format(bg="#fff", border="#e2e8f0", vcolor="#334155", lcolor="#64748b", value="—", icon="🚀", label="APPLIED"), unsafe_allow_html=True)

st.markdown("<div style='margin-top:32px;'></div>", unsafe_allow_html=True)

# ── Actions & Search ──
with st.container(border=True):
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

    st.markdown("<hr style='margin:16px 0; border-color:#f1f5f9;'/>", unsafe_allow_html=True)

    st.markdown("<div style='font-size:14px; font-weight:700; color:#1e293b; margin-bottom:8px;'>Search for Jobs</div>", unsafe_allow_html=True)
    search_col, _ = st.columns([2, 1])
    kw = ""
    with search_col:
        with st.form("search_form", border=False):
            c_in, c_btn = st.columns([4, 1])
            with c_in:
                search_input = st.text_input("Search", placeholder="e.g. Python Developer, ETL, Spark...", label_visibility="collapsed")
            with c_btn:
                submitted = st.form_submit_button("Search", type="primary", use_container_width=True)
            if submitted and search_input:
                kw = search_input.strip()
                add_search_history(kw)

    history = get_search_history()
    if history:
        recent_kw = st.selectbox("Recent Searches", ["Select a recent search..."] + history, label_visibility="collapsed")
        if recent_kw and recent_kw != "Select a recent search..." and not submitted:
            kw = recent_kw

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

st.markdown("<div style='margin-top:32px;'></div>", unsafe_allow_html=True)

# ── Matched Job Cards ──
sort_c1, sort_c2 = st.columns([3, 1])
with sort_c1:
    st.markdown("<div style='display:flex; align-items:center; gap:12px;'><span style='font-size:24px;'>🎯</span><h2 style='margin:0; font-size:20px; font-weight:800; color:#0f172a;'>Top Job Matches</h2><span style='background:#f5f3ff; color:#7c3aed; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:700;'>13</span></div>", unsafe_allow_html=True)
with sort_c2:
    sort_by = st.selectbox("Sort by", ["Score ↓ (High to Low)", "Recently Posted", "Company Name"], label_visibility="collapsed")

order_clause = "m.match_score DESC"
if "Recently" in sort_by:
    order_clause = "j.posted_date DESC, m.match_score DESC"
elif "Company" in sort_by:
    order_clause = "j.company_name ASC, m.match_score DESC"

jobs_df = query_df(f"""
    SELECT
        m.match_id, m.match_score, m.status,
        j.job_hash, j.job_title, j.company_name, j.location, j.remote_type,
        j.salary_range, j.tech_stack, j.apply_link, j.job_description, j.portal, j.posted_date
    FROM user_job_matches m
    JOIN jobs_clean_silver j ON m.job_hash = j.job_hash
    WHERE m.user_id = '{user_id}'
    ORDER BY {order_clause}
    LIMIT 20
""")

if jobs_df.empty:
    st.info("No job matches found. Try running the Scraper and Pipeline.")
else:
    for _, job in jobs_df.iterrows():
        render_job_card(job, user_id)
