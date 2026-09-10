"""
syntra_styles.py — Shared SYNTRA dark theme CSS
Import this in every page: from syntra_styles import inject_styles; inject_styles()
"""
import streamlit as st


DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Root Variables ── */
:root {
    --bg-primary:    #0a0f1e;
    --bg-secondary:  #0f172a;
    --bg-card:       #131c31;
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
html, body, [class*="css"], .main, .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}
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
[data-testid="stSidebar"] a {
    border-radius: 8px !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebar"] a:hover {
    background: var(--accent-glow) !important;
}

/* ── Headings ── */
h1, h2, h3, h4 { color: var(--text-primary) !important; }

/* ── Cards ── */
.syntra-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px 24px;
    margin-bottom: 16px;
    transition: all 0.25s ease;
}
.syntra-card:hover {
    border-color: var(--border-hover);
    box-shadow: 0 0 20px var(--accent-glow);
    transform: translateY(-2px);
}
.metric-card {
    background: linear-gradient(135deg, var(--bg-card) 0%, rgba(99,102,241,0.08) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 20px;
    text-align: center;
}
.metric-card .value { font-size: 30px; font-weight: 800; color: var(--accent-light); }
.metric-card .label { font-size: 11px; color: var(--text-secondary); margin-top:4px; text-transform:uppercase; letter-spacing:0.8px; }

/* ── Badges ── */
.badge { display:inline-block; padding:3px 12px; border-radius:20px; font-size:11px; font-weight:600; margin:2px; }
.badge-green  { background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); }
.badge-yellow { background:rgba(245,158,11,0.15);  color:#f59e0b; border:1px solid rgba(245,158,11,0.3); }
.badge-blue   { background:rgba(99,102,241,0.15);  color:#818cf8; border:1px solid rgba(99,102,241,0.3); }
.badge-red    { background:rgba(239,68,68,0.15);   color:#f87171; border:1px solid rgba(239,68,68,0.3); }
.badge-gray   { background:rgba(100,116,139,0.15); color:#94a3b8; border:1px solid rgba(100,116,139,0.3); }
.badge-purple { background:rgba(167,139,250,0.15); color:#a78bfa; border:1px solid rgba(167,139,250,0.3); }

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
    border: none !important; color: white !important;
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

/* ── Form labels ── */
label, .stSelectbox label, .stTextInput label, .stTextArea label,
.stNumberInput label, .stSlider label, .stRadio label, .stCheckbox label {
    color: var(--text-secondary) !important;
    font-size: 13px !important;
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
.stAlert { border-radius: 10px !important; }
[data-testid="stAlert"] { border-radius: 10px !important; }
.stSuccess { background: rgba(16,185,129,0.1) !important; border-left-color:#10b981 !important; color:var(--text-primary) !important; }
.stError   { background: rgba(239,68,68,0.1) !important;  border-left-color:#ef4444 !important; color:var(--text-primary) !important; }
.stWarning { background: rgba(245,158,11,0.1) !important; border-left-color:#f59e0b !important; color:var(--text-primary) !important; }
.stInfo    { background: rgba(99,102,241,0.1) !important; border-left-color:#6366f1 !important; color:var(--text-primary) !important; }

/* ── Dataframes ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* ── Score bar ── */
.score-bar  { height:5px; background:rgba(99,102,241,0.15); border-radius:3px; margin-top:6px; }
.score-fill { height:5px; border-radius:3px; }

/* ── Section title ── */
.section-title {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: var(--text-muted); margin: 18px 0 8px;
}

/* ── SYNTRA logo ── */
.syntra-logo {
    font-size: 28px; font-weight: 800;
    background: linear-gradient(135deg, #6366f1, #a78bfa, #06b6d4);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; letter-spacing: -0.5px;
}

/* ── Divider ── */
hr { border-color: var(--border) !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background:#334155; border-radius:4px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer { visibility: hidden !important; }
</style>
"""


def inject_styles():
    """Call at the top of every page to apply SYNTRA dark theme."""
    st.markdown(DARK_CSS, unsafe_allow_html=True)
