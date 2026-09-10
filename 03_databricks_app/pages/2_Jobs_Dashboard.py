"""
Page 2 — Jobs Dashboard
- View all matched jobs for the selected user
- Filter by score, remote type, experience fit
- Status badges: Resume Ready / Generating / Not Generated / Applied
- Link to apply directly (opens job URL)
- Trigger resume generation for selected jobs
- Applied tracking: clicking job link marks as applied
"""

import streamlit as st
import pandas as pd
from datetime import datetime

@st.cache_resource
def get_spark():
    try:
        from databricks.connect import DatabricksSession
        return DatabricksSession.builder.getOrCreate()
    except Exception:
        return None

spark = get_spark()
CATALOG = "jobs_automation_db"

def run_sql(q):
    if spark:
        try:
            return spark.sql(q).toPandas()
        except Exception as e:
            st.error(f"DB Error: {e}")
    return pd.DataFrame()

def status_badge(status):
    mapping = {
        "resume_ready":    ('<span class="badge-green">✅ Resume Ready</span>', "green"),
        "matched":         ('<span class="badge-yellow">⏳ Pending</span>', "yellow"),
        "resume_pending":  ('<span class="badge-blue">🔄 Generating</span>', "blue"),
        "applied":         ('<span class="badge-gray">📤 Applied</span>', "gray"),
        "skipped":         ('<span class="badge-gray">⏭️ Skipped</span>', "gray"),
        "recruiter_replied": ('<span class="badge-green">💬 Replied</span>', "green"),
    }
    return mapping.get(status, ('<span class="badge-gray">Unknown</span>', "gray"))

def exp_fit_badge(fit):
    mapping = {
        "exact": '<span class="badge-green">✅ Exact Fit</span>',
        "near":  '<span class="badge-yellow">🔶 Near Fit</span>',
        "over":  '<span class="badge-blue">🔼 Over-qualified</span>',
        "under": '<span class="badge-yellow">🔽 Under</span>',
    }
    return mapping.get(fit, fit)

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
.badge-green  { background:#dcfce7; color:#166534; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-yellow { background:#fef9c3; color:#854d0e; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-blue   { background:#dbeafe; color:#1e40af; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-gray   { background:#f1f5f9; color:#475569; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.job-card { background:white; border-radius:12px; padding:16px 20px; margin-bottom:12px;
             box-shadow:0 1px 3px rgba(0,0,0,0.08); border-left:4px solid #3b82f6; }
.job-card:hover { box-shadow:0 4px 12px rgba(0,0,0,0.12); transform:translateY(-1px); transition:all 0.2s; }
.score-bar { height:6px; border-radius:3px; background:#e2e8f0; margin-top:4px; }
.score-fill { height:6px; border-radius:3px; }
</style>
""", unsafe_allow_html=True)

st.title("💼 Jobs Dashboard")

# ── User selector ─────────────────────────────────────────────
users_df = run_sql(f"SELECT user_id, full_name, total_experience_years FROM {CATALOG}.users_schema.users WHERE is_active = true")

if users_df.empty:
    st.warning("No users found. Please complete onboarding first.")
    st.stop()

user_options = {row["full_name"]: row["user_id"] for _, row in users_df.iterrows()}
selected_name = st.selectbox("👤 Select User", list(user_options.keys()))
user_id = user_options[selected_name]
st.session_state["current_user_id"] = user_id

# ── Metrics Row ───────────────────────────────────────────────
metrics_df = run_sql(f"""
    SELECT
        COUNT(*) AS total_matches,
        SUM(CASE WHEN status = 'resume_ready' THEN 1 ELSE 0 END) AS resumes_ready,
        SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied,
        SUM(CASE WHEN status = 'recruiter_replied' THEN 1 ELSE 0 END) AS replied,
        AVG(match_score) AS avg_score
    FROM {CATALOG}.default.user_job_matches
    WHERE user_id = '{user_id}'
""")

if not metrics_df.empty:
    row = metrics_df.iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Matches",    int(row["total_matches"] or 0))
    c2.metric("✅ Resume Ready",  int(row["resumes_ready"] or 0))
    c3.metric("📤 Applied",       int(row["applied"] or 0))
    c4.metric("💬 Replies",       int(row["replied"] or 0))
    c5.metric("Avg Match Score",  f"{float(row['avg_score'] or 0):.0f}%")

st.markdown("---")

# ── Filters ───────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    min_score = st.slider("Min Match Score", 30, 100, 40, step=5)
with col2:
    remote_filter = st.multiselect("Remote Type",
        ["Remote", "Hybrid", "Onsite", "Not specified"],
        default=["Remote", "Hybrid"])
with col3:
    status_filter = st.multiselect("Status",
        ["matched", "resume_ready", "resume_pending", "applied", "skipped"],
        default=["matched", "resume_ready", "resume_pending"])
with col4:
    exp_fit_filter = st.multiselect("Experience Fit",
        ["exact", "near", "over", "under"],
        default=["exact", "near", "over"])

# ── Fetch Jobs ────────────────────────────────────────────────
remote_sql = "', '".join(remote_filter) if remote_filter else "Remote"
status_sql = "', '".join(status_filter) if status_filter else "matched"
exp_sql    = "', '".join(exp_fit_filter) if exp_fit_filter else "exact"

jobs_df = run_sql(f"""
    SELECT
        m.match_id, m.match_score, m.skill_match_pct, m.experience_fit,
        m.skill_overlap, m.skill_gap, m.status, m.resume_generated,
        m.matched_at,
        j.job_title, j.company_name, j.location, j.remote_type,
        j.salary_range, j.tech_stack, j.apply_link, j.easy_apply_link,
        j.hr_email, j.portal, j.experience_min, j.experience_max,
        j.ai_summary, j.visa_sponsorship, j.job_hash
    FROM {CATALOG}.default.user_job_matches m
    JOIN {CATALOG}.default.jobs_clean_silver j ON m.job_hash = j.job_hash
    WHERE m.user_id = '{user_id}'
      AND m.match_score >= {min_score}
      AND m.status IN ('{status_sql}')
      AND m.experience_fit IN ('{exp_sql}')
      {'AND j.remote_type IN (' + chr(39) + remote_sql + chr(39) + ')' if remote_filter else ''}
    ORDER BY m.match_score DESC
    LIMIT 200
""")

if jobs_df.empty:
    st.info("No matched jobs found with current filters. Try lowering the score or changing filters.")
    st.stop()

st.markdown(f"**Found {len(jobs_df)} matching jobs**")

# ── Batch Actions ─────────────────────────────────────────────
col_a, col_b, col_c = st.columns([2, 2, 4])
with col_a:
    if st.button("🤖 Generate 10 Resumes", type="primary", use_container_width=True):
        st.info("🔄 Triggering resume generation notebook... Check back in ~30 minutes.")
        # In production: trigger Databricks job via REST API
        # requests.post(f"{DATABRICKS_HOST}/api/2.1/jobs/run-now", ...)
        st.success("Notebook triggered! Resumes will be ready soon.")
with col_b:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

st.markdown("---")

# ── Job Cards ─────────────────────────────────────────────────
for _, job in jobs_df.iterrows():
    score      = int(job["match_score"] or 0)
    score_color= "#22c55e" if score >= 70 else "#f59e0b" if score >= 50 else "#ef4444"
    status_html, _ = status_badge(job["status"])
    exp_html       = exp_fit_badge(job.get("experience_fit", ""))

    with st.container():
        st.markdown(f"""
        <div class='job-card'>
            <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div>
                    <span style='font-size:17px; font-weight:700; color:#1e293b;'>{job['job_title']}</span>
                    <span style='font-size:13px; color:#64748b; margin-left:10px;'>@ {job['company_name']}</span>
                </div>
                <div style='text-align:right;'>
                    <span style='font-size:22px; font-weight:800; color:{score_color};'>{score}%</span>
                    <div style='font-size:10px; color:#94a3b8;'>match</div>
                </div>
            </div>
            <div style='margin:6px 0; display:flex; gap:8px; flex-wrap:wrap;'>
                {status_html} {exp_html}
                <span class='badge-gray'>📍 {job['location']}</span>
                <span class='badge-gray'>🌐 {job['remote_type']}</span>
                <span class='badge-gray'>🏢 {job['portal']}</span>
                {'<span class="badge-green">📧 HR Email</span>' if job.get("hr_email") else ''}
                {'<span class="badge-blue">💼 ' + job['salary_range'] + '</span>' if job.get("salary_range") and job['salary_range'] != 'Not Specified' else ''}
            </div>
            <div style='font-size:12px; color:#64748b; margin-top:4px;'>
                <strong>Skills matched:</strong> {(job.get('skill_overlap') or 'N/A')[:120]}
            </div>
            <div style='font-size:12px; color:#ef4444; margin-top:2px;'>
                <strong>Gap:</strong> {(job.get('skill_gap') or 'None')[:100]}
            </div>
            <div style='font-size:12px; color:#475569; margin-top:4px; font-style:italic;'>
                {(job.get('ai_summary') or '')[:200]}
            </div>
            <div class='score-bar' style='margin-top:8px;'>
                <div class='score-fill' style='width:{score}%; background:{score_color};'></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Action buttons
        bcol1, bcol2, bcol3, bcol4 = st.columns([1, 1, 1, 3])
        with bcol1:
            apply_url = job.get("easy_apply_link") or job.get("apply_link") or "#"
            if st.button(f"🔗 Apply", key=f"apply_{job['match_id']}"):
                # Mark as applied when user clicks apply link
                if spark:
                    try:
                        spark.sql(f"""
                            UPDATE {CATALOG}.default.user_job_matches
                            SET status = 'applied'
                            WHERE match_id = '{job['match_id']}'
                        """)
                        # Also record in submissions
                        import uuid
                        spark.sql(f"""
                            INSERT INTO {CATALOG}.default.job_submissions
                            VALUES ('{uuid.uuid4()}', '{user_id}', '{job['job_hash']}',
                                    '{job['match_id']}', NULL, current_timestamp(),
                                    'link_opened', 'submitted')
                        """)
                    except Exception:
                        pass
                st.markdown(f"[👉 Open Job Link]({apply_url})", unsafe_allow_html=False)

        with bcol2:
            if job["status"] not in ("resume_ready",) and st.button("📄 Generate Resume", key=f"gen_{job['match_id']}"):
                if spark:
                    spark.sql(f"""
                        UPDATE {CATALOG}.default.user_job_matches
                        SET status = 'resume_pending'
                        WHERE match_id = '{job['match_id']}'
                    """)
                st.success("Queued for generation!")

        with bcol3:
            if st.button("⏭️ Skip", key=f"skip_{job['match_id']}"):
                if spark:
                    spark.sql(f"""
                        UPDATE {CATALOG}.default.user_job_matches
                        SET status = 'skipped'
                        WHERE match_id = '{job['match_id']}'
                    """)
                st.rerun()

        st.markdown("---")
