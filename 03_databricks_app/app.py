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
    page_title="SYNTARA",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from syntara_styles import inject_styles
inject_styles()

# ── Global state init ─────────────────────────────────────────
if "default_download_format" not in st.session_state:
    st.session_state["default_download_format"] = "DOCX"

# ── Sidebar Setup ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='padding:24px 16px 16px; display:flex; align-items:center; gap:12px; margin-bottom:12px;'>
        <div style='width:40px; height:40px; border-radius:12px; background:#7c3aed; display:flex; align-items:center; justify-content:center; color:white; font-size:20px; box-shadow:0 4px 6px rgba(124,58,237,0.2);'>
            ⚡
        </div>
        <div>
            <div style='font-size:20px; font-weight:800; color:#7c3aed; letter-spacing:-0.5px; line-height:1;'>SYNTARA</div>
            <div style='font-size:11px; color:#94a3b8; font-weight:600; margin-top:2px;'>AI Bench Sales Automation</div>
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

# ── Navigation (SPA Mode) ─────────────────────────────────────
# Streamlit 1.36+ explicitly uses st.navigation to prevent sidebar reloading
pages = {
    "App": [
        st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True),
        st.Page("pages/1_Onboarding.py", title="Onboarding", icon="👤"),
        st.Page("pages/2_Jobs_Dashboard.py", title="Jobs Dashboard", icon="💼"),
        st.Page("pages/3_Resume_Viewer.py", title="Resume Viewer", icon="📄"),
        st.Page("pages/4_Email_Outreach.py", title="Email Outreach", icon="📧"),
        st.Page("pages/5_Admin.py", title="Admin", icon="👑"),
    ]
}

pg = st.navigation(pages)
pg.run()
