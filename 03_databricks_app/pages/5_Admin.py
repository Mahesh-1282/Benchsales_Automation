"""
SYNTRA — Page 5: Admin Panel
Admin-only view: all users, stats, pipeline health
"""

import streamlit as st, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_df, execute_sql
from syntra_styles import inject_styles

inject_styles()  # Dark theme

CATALOG    = "jobs_automation_db"
ADMIN_PASS = os.getenv("SYNTRA_ADMIN_PASSWORD", "syntra_admin_2024")


st.markdown("<h2 style='color:#f1f5f9;'>👑 Admin Panel</h2>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b;'>System overview — restricted to admins.</p>", unsafe_allow_html=True)

# Auth
if "admin_authed" not in st.session_state:
    st.session_state["admin_authed"] = False

if not st.session_state["admin_authed"]:
    with st.form("admin_login"):
        pwd = st.text_input("Admin Password", type="password")
        if st.form_submit_button("🔓 Login", type="primary"):
            if pwd == ADMIN_PASS:
                st.session_state["admin_authed"] = True
                st.rerun()
            else:
                st.error("Wrong password")
    st.stop()

st.success("✅ Admin access granted")
st.markdown("---")

# ── System Metrics ────────────────────────────────────────────
stats = query_df(f"""
    SELECT
        (SELECT COUNT(*) FROM {CATALOG}.users_schema.users WHERE is_active=true) AS users,
        (SELECT COUNT(*) FROM {CATALOG}.default.jobs_clean_silver WHERE active=true) AS silver_active,
        (SELECT COUNT(*) FROM {CATALOG}.default.jobs_harvested_bronze) AS bronze_total,
        (SELECT COUNT(*) FROM {CATALOG}.default.user_job_matches) AS matches,
        (SELECT COUNT(*) FROM {CATALOG}.default.generated_resumes WHERE is_latest=true) AS resumes,
        (SELECT COUNT(*) FROM {CATALOG}.default.job_submissions) AS submissions,
        (SELECT COUNT(*) FROM {CATALOG}.default.email_drafts WHERE status='sent') AS emails_sent,
        (SELECT COUNT(*) FROM {CATALOG}.default.email_drafts WHERE status='draft') AS email_drafts
""")

if not stats.empty:
    r = stats.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"<div class='metric-card'><div class='value'>{r.get('users',0)}</div><div class='label'>👤 Users</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'><div class='value'>{r.get('silver_active',0)}</div><div class='label'>💼 Active Jobs</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='metric-card'><div class='value'>{r.get('matches',0)}</div><div class='label'>🎯 Matches</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='metric-card'><div class='value'>{r.get('resumes',0)}</div><div class='label'>📄 Resumes</div></div>", unsafe_allow_html=True)
    c5, c6, c7, c8 = st.columns(4)
    c5.markdown(f"<div class='metric-card'><div class='value'>{r.get('submissions',0)}</div><div class='label'>📤 Applied</div></div>", unsafe_allow_html=True)
    c6.markdown(f"<div class='metric-card'><div class='value'>{r.get('emails_sent',0)}</div><div class='label'>📧 Emails Sent</div></div>", unsafe_allow_html=True)
    c7.markdown(f"<div class='metric-card'><div class='value'>{r.get('email_drafts',0)}</div><div class='label'>📝 Drafts</div></div>", unsafe_allow_html=True)
    c8.markdown(f"<div class='metric-card'><div class='value'>{r.get('bronze_total',0)}</div><div class='label'>🥉 Bronze</div></div>", unsafe_allow_html=True)

st.markdown("---")
at1, at2, at3, at4 = st.tabs(["👤 Users", "💼 Pipeline Health", "📊 Job Analytics", "⚙️ Settings"])

with at1:
    st.markdown("<div class='section-title'>All Users</div>", unsafe_allow_html=True)
    users_df = query_df(f"""
        SELECT u.user_id, u.full_name, u.target_title, u.total_experience_years,
               u.city, u.state, u.created_at, u.is_active,
               COUNT(DISTINCT m.match_id) AS matches,
               COUNT(DISTINCT gr.resume_id) AS resumes,
               COUNT(DISTINCT js.submission_id) AS applied
        FROM {CATALOG}.users_schema.users u
        LEFT JOIN {CATALOG}.default.user_job_matches m ON u.user_id = m.user_id
        LEFT JOIN {CATALOG}.default.generated_resumes gr ON u.user_id = gr.user_id AND gr.is_latest = true
        LEFT JOIN {CATALOG}.default.job_submissions js ON u.user_id = js.user_id
        GROUP BY u.user_id, u.full_name, u.target_title, u.total_experience_years, u.city, u.state, u.created_at, u.is_active
        ORDER BY u.created_at DESC
    """)
    if not users_df.empty:
        st.dataframe(users_df, use_container_width=True, hide_index=True)

        # Deactivate user
        st.markdown("<div class='section-title'>Manage User</div>", unsafe_allow_html=True)
        user_opts = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
        sel       = st.selectbox("Select user:", list(user_opts.keys()))
        mc1, mc2  = st.columns(2)
        with mc1:
            if st.button("🚫 Deactivate User", use_container_width=True):
                execute_sql(f"UPDATE {CATALOG}.users_schema.users SET is_active = false WHERE user_id = '{user_opts[sel]}'")
                st.success("Deactivated.")
        with mc2:
            if st.button("✅ Activate User", use_container_width=True):
                execute_sql(f"UPDATE {CATALOG}.users_schema.users SET is_active = true WHERE user_id = '{user_opts[sel]}'")
                st.success("Activated.")

with at2:
    st.markdown("<div class='section-title'>Recent Bronze Loads</div>", unsafe_allow_html=True)
    audit_df = query_df(f"""
        SELECT loaded_at, portal, keyword, rows_inserted, rows_updated, file_name
        FROM {CATALOG}.default.bronze_load_audit
        ORDER BY loaded_at DESC LIMIT 30
    """)
    if not audit_df.empty:
        st.dataframe(audit_df, use_container_width=True, hide_index=True)

    st.markdown("<div class='section-title'>Silver Quality</div>", unsafe_allow_html=True)
    quality_df = query_df(f"""
        SELECT validation_status, remote_type, COUNT(*) AS jobs, AVG(validation_score) AS avg_score
        FROM {CATALOG}.default.jobs_clean_silver
        WHERE active = true
        GROUP BY validation_status, remote_type
        ORDER BY jobs DESC
    """)
    if not quality_df.empty:
        st.dataframe(quality_df, use_container_width=True, hide_index=True)

with at3:
    st.markdown("<div class='section-title'>Top Portals</div>", unsafe_allow_html=True)
    portal_df = query_df(f"""
        SELECT portal, COUNT(*) AS jobs
        FROM {CATALOG}.default.jobs_clean_silver WHERE active=true
        GROUP BY portal ORDER BY jobs DESC
    """)
    if not portal_df.empty:
        st.bar_chart(portal_df.set_index("portal"))

    st.markdown("<div class='section-title'>Top Job Titles</div>", unsafe_allow_html=True)
    title_df = query_df(f"""
        SELECT job_title, COUNT(*) AS count
        FROM {CATALOG}.default.jobs_clean_silver WHERE active=true
        GROUP BY job_title ORDER BY count DESC LIMIT 15
    """)
    if not title_df.empty:
        st.dataframe(title_df, use_container_width=True, hide_index=True)

with at4:
    st.markdown("<div class='section-title'>Environment Variables</div>", unsafe_allow_html=True)
    from db_utils import get_env_status
    env = get_env_status()
    for k, v in env.items():
        icon = "✅" if v else "❌"
        st.write(f"{icon} `{k}` = `{v}`")

    st.markdown("---")
    st.markdown("**Add to .env file:**")
    st.code("""
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_SQL_WAREHOUSE_ID=abc123...   # Compute → SQL Warehouses → HTTP Path last segment
NVIDIA_NIM_API_KEY=nvapi-...
SYNTRA_ADMIN_PASSWORD=your_password_here
EMAIL_ENCRYPTION_KEY=...  # Optional: 32-char Fernet key for AES-256
""", language="bash")

    st.info("**SQL Warehouse ID**: In Databricks → Compute → SQL Warehouses → click your warehouse → Connection Details → HTTP Path = `/sql/1.0/warehouses/YOUR_ID`")
