"""
Benchsales Automation — Databricks App (Streamlit)
Main entry point. Run with: streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Benchsales Automation",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
/* Google Font */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Dark sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
    border-right: 1px solid #334155;
}
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

/* Main bg */
.main { background: #f8fafc; }

/* Metric cards */
.metric-card {
    background: white;
    border-radius: 12px;
    padding: 20px 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
    border-left: 4px solid #3b82f6;
    margin-bottom: 12px;
}
.metric-card h3 { margin: 0; font-size: 28px; font-weight: 700; color: #1e293b; }
.metric-card p  { margin: 4px 0 0; font-size: 13px; color: #64748b; }

/* Status badges */
.badge-green  { background:#dcfce7; color:#166534; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-yellow { background:#fef9c3; color:#854d0e; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-blue   { background:#dbeafe; color:#1e40af; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-gray   { background:#f1f5f9; color:#475569; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-red    { background:#fee2e2; color:#991b1b; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }

/* Buttons */
.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.2s !important;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important; }

/* Data table */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }

/* Sidebar nav */
.sidebar-header {
    padding: 20px 16px 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.2px;
    color: #94a3b8 !important;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='padding:20px 0 8px; text-align:center;'>
        <div style='font-size:32px;'>🚀</div>
        <div style='font-size:18px; font-weight:700; color:#f1f5f9; margin-top:4px;'>Benchsales</div>
        <div style='font-size:12px; color:#64748b; margin-top:2px;'>Automation Suite</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("<div class='sidebar-header'>Navigation</div>", unsafe_allow_html=True)

# ── Home Dashboard ────────────────────────────────────────────
st.markdown("## 🏠 Welcome to Benchsales Automation")
st.markdown("Your end-to-end job search automation platform. Use the sidebar pages to navigate.")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("""<div class='metric-card'>
        <h3>1</h3><p>📋 Onboarding</p>
        <p style='font-size:11px;margin-top:8px;'>Upload resume, set profile, add email credentials</p>
    </div>""", unsafe_allow_html=True)

with col2:
    st.markdown("""<div class='metric-card' style='border-left-color:#10b981;'>
        <h3>2</h3><p>💼 Jobs Dashboard</p>
        <p style='font-size:11px;margin-top:8px;'>View matched jobs, trigger resume generation</p>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown("""<div class='metric-card' style='border-left-color:#8b5cf6;'>
        <h3>3</h3><p>📄 Resume Viewer</p>
        <p style='font-size:11px;margin-top:8px;'>Edit, preview and download tailored resumes</p>
    </div>""", unsafe_allow_html=True)

with col4:
    st.markdown("""<div class='metric-card' style='border-left-color:#f59e0b;'>
        <h3>4</h3><p>📧 Email Outreach</p>
        <p style='font-size:11px;margin-top:8px;'>Review drafts, send applications, track replies</p>
    </div>""", unsafe_allow_html=True)

st.markdown("---")
st.info("👈 Use the sidebar to navigate between pages. Start with **1_Onboarding** if you're a new user.")
