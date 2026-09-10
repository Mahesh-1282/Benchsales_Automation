import streamlit as st
import os, sys
from pathlib import Path

# Load .env — check app dir first (works in Databricks Apps)
_app_dir = Path(__file__).parent
sys.path.insert(0, str(_app_dir))

try:
    from dotenv import load_dotenv
    for _env in [_app_dir / ".env", _app_dir.parent / "01_local_scraper" / ".env", _app_dir.parent / ".env"]:
        if _env.exists():
            load_dotenv(_env, override=False)
            break
except ImportError:
    pass

st.set_page_config(
    page_title="SYNTRA",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from syntra_styles import inject_styles
inject_styles()


# CSS is now handled centrally by syntra_styles.py
# ── Global state init ─────────────────────────────────────────
if "default_download_format" not in st.session_state:
    st.session_state["default_download_format"] = "DOCX"

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='padding:24px 16px 16px; border-bottom:1px solid rgba(99,102,241,0.2); margin-bottom:12px;'>
        <div class='syntra-logo'>⚡ SYNTRA</div>
        <div style='font-size:11px; color:#475569; margin-top:4px; font-weight:500;'>
            AI Bench Sales Automation
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Default download format — global
    st.markdown("<div class='sidebar-nav-label'>Resume Download Default</div>", unsafe_allow_html=True)
    fmt = st.radio(
        "Format",
        ["DOCX", "PDF"],
        index=0 if st.session_state.get("default_download_format") == "DOCX" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state["default_download_format"] = fmt

    st.markdown("<div class='sidebar-nav-label'>Navigation</div>", unsafe_allow_html=True)

# ── Home ──────────────────────────────────────────────────────
st.markdown("<h1 class='syntra-logo' style='font-size:36px;'>⚡ SYNTRA</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; margin-top:-8px; font-size:14px;'>AI-Powered Bench Sales Automation Platform</p>", unsafe_allow_html=True)

st.markdown("---")

# Stats row
from db_utils import query_df, get_env_status

env = get_env_status()
c1, c2, c3, c4, c5 = st.columns(5)

try:
    stats = query_df(f"""
        SELECT
            (SELECT COUNT(*) FROM jobs_automation_db.users_schema.users WHERE is_active=true) AS users,
            (SELECT COUNT(*) FROM jobs_automation_db.default.jobs_clean_silver WHERE active=true) AS active_jobs,
            (SELECT COUNT(*) FROM jobs_automation_db.default.user_job_matches) AS total_matches,
            (SELECT COUNT(*) FROM jobs_automation_db.default.generated_resumes WHERE is_latest=true) AS resumes,
            (SELECT COUNT(*) FROM jobs_automation_db.default.job_submissions) AS applied
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

# Connection status
st.markdown("<div class='section-title'>System Status</div>", unsafe_allow_html=True)
cs1, cs2, cs3, cs4 = st.columns(4)
with cs1:
    icon = "✅" if env["host_set"] else "❌"
    st.markdown(f"<div class='syntra-card' style='text-align:center;padding:12px;'>{icon}<br><span style='font-size:11px;color:#64748b;'>Databricks Host</span></div>", unsafe_allow_html=True)
with cs2:
    icon = "✅" if env["token_set"] else "❌"
    st.markdown(f"<div class='syntra-card' style='text-align:center;padding:12px;'>{icon}<br><span style='font-size:11px;color:#64748b;'>Access Token</span></div>", unsafe_allow_html=True)
with cs3:
    icon = "✅" if env["warehouse_set"] else "❌"
    st.markdown(f"<div class='syntra-card' style='text-align:center;padding:12px;'>{icon}<br><span style='font-size:11px;color:#64748b;'>SQL Warehouse</span></div>", unsafe_allow_html=True)
with cs4:
    icon = "✅" if env["nvidia_set"] else "❌"
    st.markdown(f"<div class='syntra-card' style='text-align:center;padding:12px;'>{icon}<br><span style='font-size:11px;color:#64748b;'>NVIDIA NIM</span></div>", unsafe_allow_html=True)

if not env["warehouse_set"]:
    st.warning("⚠️ **DATABRICKS_SQL_WAREHOUSE_ID** not set. Add it to your `.env` file — Databricks → SQL Warehouses → your warehouse → Connection Details → HTTP Path last segment.")

st.markdown("---")
st.markdown("""
<div style='display:grid; grid-template-columns:repeat(4,1fr); gap:16px;'>
    <div class='syntra-card'>
        <div style='font-size:24px;'>👤</div>
        <div style='font-weight:700;margin:6px 0 4px;'>Onboarding</div>
        <div style='font-size:12px;color:#64748b;'>Upload resume, set profile, configure clipboards & email</div>
    </div>
    <div class='syntra-card'>
        <div style='font-size:24px;'>💼</div>
        <div style='font-weight:700;margin:6px 0 4px;'>Jobs Dashboard</div>
        <div style='font-size:12px;color:#64748b;'>View matched jobs, full JD, generate & review resumes</div>
    </div>
    <div class='syntra-card'>
        <div style='font-size:24px;'>📧</div>
        <div style='font-weight:700;margin:6px 0 4px;'>Email Outreach</div>
        <div style='font-size:12px;color:#64748b;'>Send applications, track replies, AI reply drafts</div>
    </div>
    <div class='syntra-card'>
        <div style='font-size:24px;'>👑</div>
        <div style='font-weight:700;margin:6px 0 4px;'>Admin Panel</div>
        <div style='font-size:12px;color:#64748b;'>All users, stats, pipeline health (admin only)</div>
    </div>
</div>
""", unsafe_allow_html=True)
