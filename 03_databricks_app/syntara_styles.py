"""
syntara_styles.py — Shared SYNTARA Light & Violet theme CSS
Import this in every page: from syntara_styles import inject_styles; inject_styles()
"""
import streamlit as st


LIGHT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Root Variables ── */
:root {
    --bg-primary:    #ffffff;
    --bg-secondary:  #f8fafc;
    --bg-card:       #ffffff;
    --border:        #e2e8f0;
    --border-hover:  #8b5cf6;
    --accent:        #8b5cf6; /* Violet */
    --accent-light:  #a78bfa;
    --accent-glow:   rgba(139, 92, 246, 0.15);
    --success:       #10b981;
    --warning:       #f59e0b;
    --danger:        #ef4444;
    --text-primary:  #0f172a;
    --text-secondary:#475569;
    --text-muted:    #64748b;
}

/* ── Global Reset ── */
html, body, [class*="css"], .main, .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}
.main .block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1400px !important;
}
[data-testid="stAppViewBlockContainer"] {
    padding-top: 1.5rem !important;
}
/* ── Hide Streamlit chrome (Deploy, Header, Toolbar, Footer) ── */
header[data-testid="stHeader"],
.stAppDeployButton,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu,
footer {
    display: none !important;
    visibility: hidden !important;
}

/* ── Container Overrides ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 20px !important;
    border-color: #e2e8f0 !important;
    background: #ffffff !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 1rem !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    display: flex !important;
    flex-direction: column !important;
}
[data-testid="stSidebarNav"] {
    order: 2 !important;
    margin-top: 16px !important;
}
[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
[data-testid="stSidebar"] a {
    border-radius: 12px !important;
    transition: all 0.2s !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] a:hover {
    background: #f1f5f9 !important;
    color: var(--text-primary) !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] li a {
    border-radius: 12px !important;
    margin: 4px 16px !important;
    padding: 10px 16px !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] li a:hover {
    background: #f1f5f9 !important;
    border-left: none !important;
    color: var(--text-primary) !important;
}
/* Style active sidebar link */
[data-testid="stSidebarNav"] li a[aria-current="page"] {
    background: #f5f3ff !important;
    color: #7c3aed !important;
    font-weight: 600 !important;
}
[data-testid="stSidebarNav"] li a[aria-current="page"] span {
    color: #7c3aed !important;
}

/* ── Headings ── */
h1, h2, h3, h4 { color: var(--text-primary); }

/* ── Cards ── */
.syntara-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
    transition: all 0.25s ease;
}
.syntara-card:hover {
    border-color: var(--border-hover);
    box-shadow: 0 10px 15px -3px rgba(139,92,246,0.1), 0 4px 6px -2px rgba(139,92,246,0.05);
    transform: translateY(-2px);
}
.metric-card {
    background: linear-gradient(135deg, var(--bg-card) 0%, rgba(139,92,246,0.05) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.02);
}
.metric-card .value { font-size: 32px; font-weight: 800; color: var(--accent); }
.metric-card .label { font-size: 12px; color: var(--text-muted); margin-top:4px; text-transform:uppercase; letter-spacing:0.8px; }

/* ── Badges ── */
.badge { display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; margin:2px; }
.badge-green  { background:rgba(16,185,129,0.15); color:#059669; border:1px solid rgba(16,185,129,0.3); }
.badge-yellow { background:rgba(245,158,11,0.15);  color:#d97706; border:1px solid rgba(245,158,11,0.3); }
.badge-blue   { background:rgba(59,130,246,0.15);  color:#2563eb; border:1px solid rgba(59,130,246,0.3); }
.badge-red    { background:rgba(239,68,68,0.15);   color:#dc2626; border:1px solid rgba(239,68,68,0.3); }
.badge-gray   { background:rgba(100,116,139,0.15); color:#475569; border:1px solid rgba(100,116,139,0.3); }
.badge-purple { background:rgba(139,92,246,0.15);  color:#7c3aed; border:1px solid rgba(139,92,246,0.3); }

/* ── Buttons ── */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.2s ease !important;
    border: 1px solid var(--border) !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    box-shadow: 0 4px 6px -1px var(--accent-glow) !important;
    transform: translateY(-1px) !important;
    color: var(--accent) !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #8b5cf6, #a78bfa) !important;
    border: none !important; color: white !important;
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #7c3aed, #8b5cf6) !important;
    box-shadow: 0 4px 15px rgba(139,92,246,0.4) !important;
    color: white !important;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', sans-serif !important;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.03) !important;
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
    font-weight: 500 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-secondary) !important;
    border-radius: 12px !important;
    padding: 6px !important;
    gap: 8px !important;
    border: 1px solid var(--border) !important;
    margin-bottom: 12px !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    padding: 8px 20px !important;
    margin: 0 !important;
    border: none !important;
    background: transparent !important;
    transition: all 0.2s ease !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: var(--accent) !important;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #8b5cf6, #a78bfa) !important;
    color: white !important;
    box-shadow: 0 2px 4px rgba(139,92,246,0.2) !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    display: none !important; /* Hide the default streamlit bottom line */
}

/* ── Expander ── */
.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}
.streamlit-expanderContent {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-top: none !important;
    border-radius: 0 0 10px 10px !important;
}

/* ── Alerts ── */
.stAlert { border-radius: 10px !important; }
[data-testid="stAlert"] { border-radius: 10px !important; }
.stSuccess { background: rgba(16,185,129,0.1) !important; border-left-color:#10b981 !important; color:var(--text-primary) !important; }
.stError   { background: rgba(239,68,68,0.1) !important;  border-left-color:#ef4444 !important; color:var(--text-primary) !important; }
.stWarning { background: rgba(245,158,11,0.1) !important; border-left-color:#f59e0b !important; color:var(--text-primary) !important; }
.stInfo    { background: rgba(139,92,246,0.1) !important; border-left-color:#8b5cf6 !important; color:var(--text-primary) !important; }

/* ── Dataframes ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] th {
    background-color: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    font-weight: 600 !important;
}

/* ── Score bar ── */
.score-bar  { height:6px; background:rgba(139,92,246,0.15); border-radius:3px; margin-top:8px; }
.score-fill { height:6px; border-radius:3px; background: linear-gradient(90deg, #a78bfa, #8b5cf6); }

/* ── Section title ── */
.section-title {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: var(--text-muted); margin: 20px 0 10px;
}

/* ── SYNTARA logo ── */
.syntara-logo {
    font-size: 32px; font-weight: 800;
    background: linear-gradient(135deg, #8b5cf6, #c084fc, #3b82f6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; letter-spacing: -1px;
}

/* ── Divider ── */
hr { border: none !important; border-bottom: 1px solid var(--border) !important; margin: 2rem 0 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:8px; height:8px; }
::-webkit-scrollbar-track { background: var(--bg-secondary); }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius:4px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* Chrome hiding moved to top of file */

/* ── Upload Area Tweaks ── */
section[data-testid="stFileUploadDropzone"] {
    background-color: var(--bg-secondary) !important;
    border: 2px dashed #cbd5e1 !important;
    border-radius: 12px !important;
    padding: 24px !important;
    transition: all 0.2s ease !important;
}
section[data-testid="stFileUploadDropzone"]:hover {
    border-color: var(--accent) !important;
    background-color: var(--accent-glow) !important;
}
section[data-testid="stFileUploadDropzone"] svg {
    fill: var(--accent) !important;
}/* ── Job Cards ── */
.job-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    transition: box-shadow 0.2s, transform 0.2s;
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.job-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    transform: translateY(-2px);
    border-color: var(--border-hover);
}
.job-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}
.job-card-title {
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0;
    line-height: 1.3;
}
.job-card-company {
    font-size: 14px;
    color: var(--text-secondary);
    font-weight: 500;
    margin-top: 4px;
}
.job-card-logo {
    width: 48px;
    height: 48px;
    border-radius: 8px;
    border: 1px solid var(--border);
    object-fit: contain;
    padding: 4px;
    background: #fff;
}
.job-card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
}
.job-card-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 6px;
}
.job-card-snippet {
    font-size: 13px;
    color: var(--text-muted);
    line-height: 1.5;
    margin: 8px 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.job-card-skills {
    font-size: 12px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.job-card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 8px;
    padding-top: 12px;
    border-top: 1px dashed var(--border);
}
.job-card-time {
    font-size: 12px;
    color: var(--text-muted);
}
.job-card-actions {
    display: flex;
    gap: 8px;
}
</style>
"""


def inject_styles():
    """Call at the top of every page to apply SYNTARA light violet theme."""
    st.markdown(LIGHT_CSS, unsafe_allow_html=True)
