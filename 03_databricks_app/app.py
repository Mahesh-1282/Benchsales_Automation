"""
SYNTRA — AI-Powered Bench Sales Automation
Main Streamlit entry point
"""

import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "01_local_scraper", ".env"))

st.set_page_config(
    page_title="SYNTRA",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════
# GLOBAL PREMIUM CSS — SYNTRA DARK THEME
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

/* ── Root Variables ── */
:root {
    --bg-primary:    #0a0f1e;
    --bg-secondary:  #0f172a;
    --bg-card:       #131c31;
    --bg-glass:      rgba(19,28,49,0.8);
    --border:        rgba(99,102,241,0.2);
    --border-hover:  rgba(99,102,241,0.5);
    --accent:        #6366f1;
    --accent-light:  #818cf8;
    --accent-glow:   rgba(99,102,241,0.3);
    --success:       #10b981;
    --warning:       #f59e0b;
    --danger:        #ef4444;
    --text-primary:  #f1f5f9;
    --text-secondary:#94a3b8;
    --text-muted:    #475569;
}

/* ── Global Reset ── */
html, body, [class*="css"], .main {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

/* ── App Container ── */
.main .block-container {
    padding: 1.5rem 2rem !important;
    max-width: 1400px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #070d1a 0%, #0d1526 100%) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] li a {
    border-radius: 8px !important;
    margin: 2px 8px !important;
    padding: 8px 12px !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] li a:hover {
    background: var(--accent-glow) !important;
    border-left: 3px solid var(--accent) !important;
}

/* ── Cards ── */
.syntra-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px 24px;
    margin-bottom: 16px;
    transition: all 0.25s ease;
    backdrop-filter: blur(10px);
}
.syntra-card:hover {
    border-color: var(--border-hover);
    box-shadow: 0 0 20px var(--accent-glow);
    transform: translateY(-2px);
}

/* ── Metric Cards ── */
.metric-card {
    background: linear-gradient(135deg, var(--bg-card) 0%, rgba(99,102,241,0.08) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 20px;
    text-align: center;
}
.metric-card .value { font-size: 32px; font-weight: 800; color: var(--accent-light); }
.metric-card .label { font-size: 12px; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.8px; }

/* ── Badges ── */
.badge { display:inline-block; padding:3px 12px; border-radius:20px; font-size:11px; font-weight:600; margin:2px; }
.badge-green  { background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); }
.badge-yellow { background:rgba(245,158,11,0.15); color:#f59e0b; border:1px solid rgba(245,158,11,0.3); }
.badge-blue   { background:rgba(99,102,241,0.15); color:#818cf8; border:1px solid rgba(99,102,241,0.3); }
.badge-red    { background:rgba(239,68,68,0.15);  color:#f87171; border:1px solid rgba(239,68,68,0.3); }
.badge-gray   { background:rgba(100,116,139,0.15);color:#94a3b8; border:1px solid rgba(100,116,139,0.3); }
.badge-purple { background:rgba(167,139,250,0.15);color:#a78bfa; border:1px solid rgba(167,139,250,0.3); }

/* ── Buttons ── */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.2s ease !important;
    border: 1px solid var(--border) !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    box-shadow: 0 0 12px var(--accent-glow) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4f46e5, #6366f1) !important;
    border: none !important;
    color: white !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #4338ca, #4f46e5) !important;
    box-shadow: 0 4px 20px rgba(99,102,241,0.5) !important;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background: rgba(15,23,42,0.8) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px var(--accent-glow) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-secondary) !important;
    border-radius: 12px !important;
    padding: 4px !important;
    gap: 4px !important;
    border: 1px solid var(--border) !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    padding: 8px 16px !important;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #4f46e5, #6366f1) !important;
    color: white !important;
}

/* ── Expander ── */
.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}
.streamlit-expanderContent {
    background: rgba(15,23,42,0.6) !important;
    border: 1px solid var(--border) !important;
    border-radius: 0 0 10px 10px !important;
}

/* ── Alerts ── */
.stAlert, [data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left: 4px solid var(--accent) !important;
    background: rgba(99,102,241,0.08) !important;
}

/* ── Dataframes ── */
[data-testid="stDataFrame"] { 
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] th { background: var(--bg-secondary) !important; color: var(--text-secondary) !important; }
[data-testid="stDataFrame"] td { background: var(--bg-card) !important; color: var(--text-primary) !important; }

/* ── Score bar ── */
.score-bar { height:5px; background:rgba(99,102,241,0.15); border-radius:3px; margin-top:6px; }
.score-fill { height:5px; border-radius:3px; transition:width 0.5s ease; }

/* ── Section headers ── */
.section-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-muted);
    margin: 20px 0 10px;
}

/* ── SYNTRA logo glow ── */
.syntra-logo {
    font-size: 28px;
    font-weight: 800;
    background: linear-gradient(135deg, #6366f1, #a78bfa, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
}

/* ── Sidebar header ── */
.sidebar-nav-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #334155 !important;
    text-transform: uppercase;
    padding: 12px 16px 4px;
}

/* ── Download format selector ── */
.download-opts {
    display: flex;
    gap: 8px;
    align-items: center;
    background: var(--bg-card);
    padding: 8px 16px;
    border-radius: 10px;
    border: 1px solid var(--border);
}

/* ── Spinner ── */
.stSpinner > div { border-top-color: var(--accent) !important; }

/* ── Success / Error ── */
.stSuccess { background: rgba(16,185,129,0.1) !important; border-left-color: #10b981 !important; }
.stError   { background: rgba(239,68,68,0.1) !important; border-left-color: #ef4444 !important; }
.stWarning { background: rgba(245,158,11,0.1) !important; border-left-color: #f59e0b !important; }
.stInfo    { background: rgba(99,102,241,0.1) !important; border-left-color: #6366f1 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* ── Hide Streamlit branding ── */
#MainMenu, footer, header { visibility: hidden !important; }
</style>
""", unsafe_allow_html=True)

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
