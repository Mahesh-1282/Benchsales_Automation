"""
SYNTRA — Page 2: Jobs Dashboard
Three-panel: Job List | Full Job Details | Resume Panel
"""

import streamlit as st
import sys, os, json, uuid, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_df, execute_sql, insert_row, esc
from syntara_styles import inject_styles

inject_styles()  # Dark theme on every page

CATALOG = "jobs_automation_db"


def status_badge(status: str) -> str:
    m = {
        "resume_ready":       '<span class="badge badge-green">✅ Resume Ready</span>',
        "matched":            '<span class="badge badge-yellow">⏳ Pending</span>',
        "resume_pending":     '<span class="badge badge-blue">🔄 Generating</span>',
        "applied":            '<span class="badge badge-purple">📤 Applied</span>',
        "skipped":            '<span class="badge badge-gray">⏭️ Skipped</span>',
        "recruiter_replied":  '<span class="badge badge-green">💬 Replied</span>',
    }
    return m.get(status, f'<span class="badge badge-gray">{status}</span>')


def exp_fit_badge(fit: str) -> str:
    m = {
        "exact": '<span class="badge badge-green">✅ Exact Fit</span>',
        "near":  '<span class="badge badge-yellow">🔶 Near Fit</span>',
        "over":  '<span class="badge badge-blue">🔼 Over-qualified</span>',
        "under": '<span class="badge badge-yellow">🔽 Under</span>',
    }
    return m.get(fit, "")


def score_color(s: int) -> str:
    if s >= 70: return "#10b981"
    if s >= 50: return "#f59e0b"
    return "#ef4444"


# ── Header ────────────────────────────────────────────────────
st.markdown("<h2 style='color:#f1f5f9; margin-bottom:4px;'>💼 Jobs Dashboard</h2>", unsafe_allow_html=True)

# ── User selector + Download format ──────────────────────────
hcol1, hcol2, hcol3 = st.columns([3, 2, 2])

users_df = query_df(f"SELECT user_id, full_name, total_experience_years FROM users WHERE is_active = true")
if users_df.empty:
    st.warning("No users yet. Complete Onboarding first.")
    st.stop()

user_opts = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
with hcol1:
    sel_name = st.selectbox("👤 User", list(user_opts.keys()))
    user_id  = user_opts[sel_name]
    st.session_state["current_user_id"] = user_id

with hcol2:
    default_fmt = st.session_state.get("default_download_format", "DOCX")
    fmt_choice  = st.radio("⬇️ Default Download", ["DOCX", "PDF"], horizontal=True,
                           index=0 if default_fmt == "DOCX" else 1)
    st.session_state["default_download_format"] = fmt_choice

with hcol3:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# ── Metrics ───────────────────────────────────────────────────
m_df = query_df(f"""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN status = 'resume_ready' THEN 1 ELSE 0 END) AS ready,
        SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied,
        SUM(CASE WHEN status = 'recruiter_replied' THEN 1 ELSE 0 END) AS replied,
        SUM(CASE WHEN status = 'matched' THEN 1 ELSE 0 END) AS pending,
        AVG(match_score) AS avg_score
    FROM user_job_matches
    WHERE user_id = '{user_id}'
""")

if not m_df.empty:
    r = m_df.iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.markdown(f"<div class='metric-card'><div class='value'>{int(float(r.get('total') or 0))}</div><div class='label'>Total</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'><div class='value' style='color:#10b981;'>{int(float(r.get('ready') or 0))}</div><div class='label'>✅ Resume Ready</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='metric-card'><div class='value' style='color:#f59e0b;'>{int(float(r.get('pending') or 0))}</div><div class='label'>⏳ Pending</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='metric-card'><div class='value' style='color:#a78bfa;'>{int(float(r.get('applied') or 0))}</div><div class='label'>📤 Applied</div></div>", unsafe_allow_html=True)
    c5.markdown(f"<div class='metric-card'><div class='value' style='color:#10b981;'>{int(float(r.get('replied') or 0))}</div><div class='label'>💬 Replied</div></div>", unsafe_allow_html=True)
    c6.markdown(f"<div class='metric-card'><div class='value'>{float(r.get('avg_score') or 0):.0f}%</div><div class='label'>Avg Score</div></div>", unsafe_allow_html=True)

st.markdown("---")

# ── Filters ───────────────────────────────────────────────────
with st.expander("🔍 Filters", expanded=False):
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    with fc1: min_score = st.slider("Min Match Score", 0, 100, 0, 5)
    with fc2: remote_f  = st.multiselect("Remote Type", ["Remote","Hybrid","Onsite","Not specified"], default=["Remote","Hybrid"])
    with fc3: status_f  = st.multiselect("Status", ["matched","resume_ready","resume_pending","applied","skipped"], default=["matched","resume_ready","resume_pending"])
    with fc4: exp_fit_f = st.multiselect("Exp Fit", ["exact","near","over","under"], default=["exact","near","over"])
    with fc5: skills_f  = st.text_input("Skills/Tech", placeholder="e.g. Python")

rf_str  = "', '".join(remote_f)  if remote_f  else "Remote"
sf_str  = "', '".join(status_f)  if status_f  else "matched"
ef_str  = "', '".join(exp_fit_f) if exp_fit_f else "exact"
skills_sql = f"AND LOWER(j.tech_stack) LIKE LOWER('%{skills_f}%')" if skills_f else ""

import subprocess

# ── Local Scraper ─────────────────────────────────────────────
with st.expander("🕷️ Run Local Scraper", expanded=False):
    st.markdown("Trigger the multi-portal job scraper locally. This streams logs in real-time.")
    
    kw = ""
    if "ai_scraping_keywords" in users_df.columns:
        matching_user = users_df.loc[users_df["user_id"] == user_id]
        if not matching_user.empty:
            kw = matching_user.iloc[0].get("ai_scraping_keywords", "")
    
    st.info(f"Using AI Keywords: **{kw or 'Data Engineer (Default)'}**")
    
    if st.button("▶️ Start Scraping", type="primary"):
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
            log_container.code("".join(logs[-100:]), language="bash")
            
        process.stdout.close()
        process.wait()
        
        if process.returncode == 0:
            st.success("✅ Scraping Complete!")
        else:
            st.error(f"❌ Scraping Failed with code {process.returncode}")
        
        if st.button("🔄 Reload Dashboard After Scrape"):
            st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ Pipeline")
    if st.button("▶️ Run Job Matching Pipeline", type="secondary"):
        with st.spinner("Running pipeline (Bronze -> Silver -> Matching -> Resume Gen)..."):
            pipeline_script = os.path.join(Path(__file__).parent.parent, "local_pipeline.py")
            p = subprocess.run([sys.executable, pipeline_script], capture_output=True, text=True)
            if p.returncode == 0:
                st.success("✅ Pipeline Complete!")
                with st.expander("Show Pipeline Logs"):
                    st.code(p.stdout, language="bash")
            else:
                st.error(f"❌ Pipeline Failed: {p.stderr}")

# ── Load jobs ─────────────────────────────────────────────────
jobs_df = query_df(f"""
    SELECT
        m.match_id, m.match_score, m.skill_match_pct, m.experience_fit,
        m.skill_overlap, m.skill_gap, m.status, m.resume_generated,
        m.matched_at, m.resume_id,
        j.job_hash, j.job_title, j.company_name, j.location, j.remote_type,
        j.salary_range, j.tech_stack, j.apply_link, j.easy_apply_link,
        j.hr_email, j.portal, j.experience_min, j.experience_max,
        j.ai_summary, j.visa_sponsorship, j.roles_summary,
        j.job_description, j.requirements_section
    FROM user_job_matches m
    JOIN jobs_clean_silver j ON m.job_hash = j.job_hash
    WHERE m.user_id = '{user_id}'
      AND m.match_score >= {min_score}
      AND m.status IN ('{sf_str}')
      AND m.experience_fit IN ('{ef_str}')
      {skills_sql}
    ORDER BY m.match_score DESC
    LIMIT 200
""")

if jobs_df.empty:
    st.info("No matched jobs found. Adjust filters or run the matching notebook.")
    st.stop()

st.markdown(f"<span class='badge badge-blue'>{len(jobs_df)} jobs</span>", unsafe_allow_html=True)

# ── Batch Actions ─────────────────────────────────────────────
bac1, bac2, bac3 = st.columns([2, 2, 6])
with bac1:
    if st.button("🤖 Generate Selected Resumes", type="primary", use_container_width=True):
        selected_ids = [j["match_id"] for _, j in jobs_df.iterrows() if st.session_state.get(f"chk_{j['match_id']}")]
        if not selected_ids:
            st.warning("No jobs selected via checkboxes.")
        else:
            for mid in selected_ids:
                execute_sql(f"UPDATE user_job_matches SET status = 'resume_pending' WHERE match_id = '{mid}'")
            st.success(f"Queued {len(selected_ids)} resumes for generation!")
            st.rerun()
with bac2:
    if st.button("📤 Export All Jobs CSV", use_container_width=True):
        import pandas as pd
        csv = jobs_df[["job_title","company_name","location","match_score","status","apply_link"]].to_csv(index=False)
        st.download_button("⬇️ Download CSV", csv, "jobs.csv", "text/csv", use_container_width=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════
# THREE-PANEL LAYOUT
# ══════════════════════════════════════════════════════════════
list_col, detail_col, resume_col = st.columns([1.2, 2, 1.8])

# ── STATE: which job is selected ─────────────────────────────
if "selected_match_id" not in st.session_state:
    st.session_state["selected_match_id"] = jobs_df.iloc[0]["match_id"] if not jobs_df.empty else None

# ── PANEL 1: Job List ─────────────────────────────────────────
with list_col:
    st.markdown("<div class='section-title'>Job Matches</div>", unsafe_allow_html=True)
    for _, job in jobs_df.iterrows():
        score  = int(float(job["match_score"] or 0))
        sc     = score_color(score)
        is_sel = st.session_state.get("selected_match_id") == job["match_id"]
        border = "border-color:#6366f1; box-shadow:0 0 12px rgba(99,102,241,0.3);" if is_sel else ""

        st.markdown(f"""
        <div class='syntara-card' style='padding:12px 14px; cursor:pointer; {border}'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div>
                    <div style='font-weight:700; font-size:13px; color:#f1f5f9;'>{str(job['job_title'])[:35]}</div>
                    <div style='font-size:11px; color:#64748b; margin-top:2px;'>{str(job['company_name'])[:30]}</div>
                    <div style='font-size:10px; color:#475569;'>📍 {str(job['location'])[:25]}</div>
                </div>
                <div style='text-align:right;'>
                    <div style='font-size:20px; font-weight:800; color:{sc};'>{score}%</div>
                    <div class='score-bar'>
                        <div class='score-fill' style='width:{score}%; background:{sc};'></div>
                    </div>
                </div>
            </div>
            <div style='margin-top:6px;'>{status_badge(job['status'])}</div>
        </div>
        """, unsafe_allow_html=True)
        
        c_chk, c_btn = st.columns([1, 4])
        with c_chk:
            st.checkbox(" ", key=f"chk_{job['match_id']}", label_visibility="collapsed")
        with c_btn:
            if st.button("View Details →", key=f"sel_{job['match_id']}", use_container_width=True):
                st.session_state["selected_match_id"] = job["match_id"]
                st.rerun()

# ── Get selected job ─────────────────────────────────────────
sel_id  = st.session_state.get("selected_match_id")
sel_row = jobs_df[jobs_df["match_id"] == sel_id]
if sel_row.empty:
    sel_row = jobs_df.iloc[:1]
job = sel_row.iloc[0]

# ── PANEL 2: Job Details ──────────────────────────────────────
with detail_col:
    st.markdown("<div class='section-title'>Job Details</div>", unsafe_allow_html=True)

    score = int(float(job["match_score"] or 0))
    sc    = score_color(score)

    st.markdown(f"""
    <div class='syntara-card'>
        <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
            <div>
                <h3 style='margin:0; color:#f1f5f9;'>{job['job_title']}</h3>
                <div style='font-size:15px; color:#94a3b8; margin:4px 0;'>@ {job['company_name']}</div>
            </div>
            <div style='text-align:right;'>
                <div style='font-size:36px; font-weight:900; color:{sc};'>{score}%</div>
                <div style='font-size:11px; color:#64748b;'>Match Score</div>
            </div>
        </div>
        <div style='display:flex; flex-wrap:wrap; gap:6px; margin-top:10px;'>
            {status_badge(job['status'])}
            {exp_fit_badge(str(job.get('experience_fit') or ''))}
            <span class='badge badge-gray'>📍 {job['location']}</span>
            <span class='badge badge-gray'>🌐 {job['remote_type']}</span>
            <span class='badge badge-gray'>🏢 {job['portal']}</span>
            {'<span class="badge badge-green">📧 HR Email Available</span>' if job.get("hr_email") else ''}
            {'<span class="badge badge-blue">💚 Visa Sponsorship</span>' if str(job.get("visa_sponsorship")) == "true" else ''}
            {'<span class="badge badge-yellow">💰 ' + str(job['salary_range']) + '</span>' if job.get("salary_range") and str(job['salary_range']) not in ("Not Specified","None","") else ''}
        </div>
        <div style='font-size:12px; color:#64748b; margin-top:8px;'>
            <strong>Exp Required:</strong> {job.get('experience_min',0)}–{job.get('experience_max',99)} yrs
            &nbsp;|&nbsp; <strong>Skills Match:</strong> {int(float(job.get('skill_match_pct') or 0))}%
        </div>
        <div class='score-bar' style='margin-top:8px;'>
            <div class='score-fill' style='width:{score}%; background:{sc};'></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Match analysis
    if job.get("skill_overlap"):
        st.markdown("<div class='section-title'>Skills Matched</div>", unsafe_allow_html=True)
        for s in str(job["skill_overlap"]).split(","):
            s = s.strip()
            if s: st.markdown(f"<span class='badge badge-green'>{s}</span>", unsafe_allow_html=True)

    if job.get("skill_gap"):
        st.markdown("<div class='section-title'>Skills Gap</div>", unsafe_allow_html=True)
        for s in str(job["skill_gap"]).split(","):
            s = s.strip()
            if s: st.markdown(f"<span class='badge badge-red'>{s}</span>", unsafe_allow_html=True)

    # AI Summary
    if job.get("ai_summary"):
        st.markdown("<div class='section-title'>AI Summary</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='syntara-card' style='padding:12px; font-size:13px; color:#94a3b8;'>{job['ai_summary']}</div>", unsafe_allow_html=True)

    # Job tabs
    jt1, jt2, jt3 = st.tabs(["📋 Responsibilities", "📌 Requirements", "🔗 Apply"])

    with jt1:
        raw_roles = str(job.get("roles_summary") or job.get("job_description") or "Not available")
        roles = re.sub(r'<[^>]+>', '', raw_roles)[:3000]
        if "•" in roles:
            for line in roles.split("\n"):
                if line.strip():
                    st.write(line)
        else:
            st.markdown(f"<div style='font-size:13px; color:#94a3b8; white-space:pre-wrap;'>{roles[:2000]}</div>", unsafe_allow_html=True)

    with jt2:
        raw_req = str(job.get("requirements_section") or job.get("tech_stack") or "See job description")
        req = re.sub(r'<[^>]+>', '', raw_req)[:2000]
        st.markdown(f"<div style='font-size:13px; color:#94a3b8; white-space:pre-wrap;'>{req}</div>", unsafe_allow_html=True)

    with jt3:
        apply_url  = str(job.get("easy_apply_link") or job.get("apply_link") or "")
        hr_email   = str(job.get("hr_email") or "")

        if hr_email and hr_email not in ("None", ""):
            st.success(f"📧 HR Email found: **{hr_email}**")
            st.info("Go to Email Outreach page to send your application with resume attached.")

        if apply_url and apply_url not in ("None", ""):
            st.markdown(f"**[🔗 Open Job Listing]({apply_url})**")
            if st.button("📤 Mark as Applied (link)", key=f"apply_link_{job['match_id']}"):
                execute_sql(f"UPDATE user_job_matches SET status = 'applied' WHERE match_id = '{job['match_id']}'")
                try:
                    insert_row(f"job_submissions", {
                        "submission_id":      str(uuid.uuid4()),
                        "user_id":            user_id,
                        "job_hash":           str(job["job_hash"]),
                        "match_id":           str(job["match_id"]),
                        "resume_id":          str(job.get("resume_id") or ""),
                        "submitted_at":       datetime.now(),
                        "submission_method":  "link_opened",
                        "status":             "submitted",
                    })
                except Exception: pass
                st.success("✅ Marked as Applied!")
                st.rerun()
        else:
            st.warning("No direct apply link found in our database.")

    # Action row
    st.markdown("---")
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        if job["status"] not in ("resume_ready", "applied") and st.button("📄 Queue Resume Gen", key=f"gen_{job['match_id']}", use_container_width=True, type="primary"):
            execute_sql(f"UPDATE user_job_matches SET status = 'resume_pending' WHERE match_id = '{job['match_id']}'")
            st.success("Queued!")
            st.rerun()
    with ac2:
        if st.button("⏭️ Skip Job", key=f"skip_{job['match_id']}", use_container_width=True):
            execute_sql(f"UPDATE user_job_matches SET status = 'skipped' WHERE match_id = '{job['match_id']}'")
            st.rerun()
    with ac3:
        if st.button("♻️ Re-match", key=f"rematch_{job['match_id']}", use_container_width=True):
            execute_sql(f"UPDATE user_job_matches SET status = 'matched' WHERE match_id = '{job['match_id']}'")
            st.rerun()

# ── PANEL 3: Resume Panel ─────────────────────────────────────
with resume_col:
    st.markdown("<div class='section-title'>Resume for This Job</div>", unsafe_allow_html=True)

    resume_id = str(job.get("resume_id") or "")

    if job["status"] == "resume_ready" and resume_id and resume_id not in ("None", ""):
        # Load resume data
        res_df = query_df(f"""
            SELECT gr.resume_id, gr.docx_path, gr.pdf_path,
                   gr.experience_years_used, gr.skills_highlighted,
                   gr.tailored_bullets_json, gr.resume_version,
                   gr.is_user_edited, gr.generated_at, gr.basic_knowledge_added
            FROM generated_resumes gr
            WHERE gr.resume_id = '{resume_id}' AND gr.is_latest = true
        """)

        if res_df.empty:
            res_df = query_df(f"""
                SELECT gr.resume_id, gr.docx_path, gr.pdf_path,
                       gr.experience_years_used, gr.skills_highlighted,
                       gr.tailored_bullets_json, gr.resume_version,
                       gr.is_user_edited, gr.generated_at, gr.basic_knowledge_added
                FROM generated_resumes gr
                WHERE gr.user_id = '{user_id}' AND gr.job_hash = '{job["job_hash"]}' AND gr.is_latest = true
                LIMIT 1
            """)

        if not res_df.empty:
            r = res_df.iloc[0]
            gen_dt = str(r.get("generated_at") or "")[:10]
            edit_tag = "✏️ Edited" if r.get("is_user_edited") else "🤖 AI Gen"

            st.markdown(f"""
            <div class='syntara-card'>
                <div style='font-weight:700;'>📄 v{int(float(r.get('resume_version') or 1))}</div>
                <div style='font-size:11px; color:#64748b;'>Generated {gen_dt} · {edit_tag}</div>
                <div style='margin-top:8px; font-size:12px;'>
                    <strong>Exp shown:</strong> {r.get('experience_years_used',0)} yrs
                </div>
                <div style='font-size:11px; color:#94a3b8; margin-top:4px;'>
                    <strong>Skills:</strong> {(str(r.get('skills_highlighted') or ''))[:150]}
                </div>
                {'<div style="font-size:11px;color:#f59e0b;margin-top:4px;">+ Familiar with: ' + str(r.get("basic_knowledge_added") or "")[:80] + '</div>' if r.get("basic_knowledge_added") else ''}
            </div>
            """, unsafe_allow_html=True)

            # Tailored bullets preview
            bullets_json = json.loads(r.get("tailored_bullets_json") or "[]")
            if bullets_json:
                st.markdown("<div class='section-title'>Tailored Bullets (AI)</div>", unsafe_allow_html=True)
                for item in bullets_json[:2]:  # Show first 2 roles
                    bullets = item.get("bullets", [])
                    st.markdown(f"**Role {item.get('role_index', 0)+1}**")
                    for b in bullets[:3]:
                        st.markdown(f"<div style='font-size:11px; color:#94a3b8; margin:2px 0;'>• {b[:120]}</div>", unsafe_allow_html=True)

            # Download buttons
            st.markdown("<div class='section-title'>Download</div>", unsafe_allow_html=True)
            default_fmt = st.session_state.get("default_download_format", "DOCX")

            d1, d2 = st.columns(2)
            with d1:
                # Primary download (global default)
                if st.button(f"⬇️ {default_fmt}", key=f"dl_def_{resume_id}", use_container_width=True, type="primary"):
                    st.info(f"Download {default_fmt} from DBFS path:\n`{r.get('docx_path','—')}`")
            with d2:
                alt_fmt = "PDF" if default_fmt == "DOCX" else "DOCX"
                if st.button(f"⬇️ {alt_fmt}", key=f"dl_alt_{resume_id}", use_container_width=True):
                    st.info(f"Download {alt_fmt} from DBFS path:\n`{r.get('pdf_path','—')}`")

            # Edit button — opens form in expander
            with st.expander("✏️ Edit Bullets", expanded=False):
                for i, item in enumerate(bullets_json):
                    st.markdown(f"**Role {item.get('role_index', i)+1}**")
                    new_bullets = []
                    for j, bullet in enumerate(item.get("bullets", [])):
                        new_b = st.text_area(
                            f"B{j+1}",
                            value=bullet,
                            height=70,
                            key=f"b_{resume_id}_{i}_{j}",
                            label_visibility="collapsed",
                        )
                        new_bullets.append(new_b)
                    bullets_json[i]["bullets"] = new_bullets

                if st.button("💾 Save Edits", key=f"save_edit_{resume_id}", type="primary"):
                    # Pre-escape JSON string (Python 3.11: no backslash in f-string)
                    bullets_str = esc(json.dumps(bullets_json))
                    execute_sql(
                        f"UPDATE generated_resumes "
                        f"SET tailored_bullets_json = '{bullets_str}', "
                        f"is_user_edited = true, "
                        f"last_edited_at = current_timestamp() "
                        f"WHERE resume_id = '{resume_id}'"
                    )
                    st.success("✅ Saved!")

            if st.button("🔄 Regenerate (new version)", key=f"regen_{resume_id}", use_container_width=True):
                execute_sql(f"UPDATE generated_resumes SET is_latest = false WHERE resume_id = '{resume_id}'")
                execute_sql(f"UPDATE user_job_matches SET status = 'matched', resume_generated = false, resume_id = NULL WHERE match_id = '{job['match_id']}'")
                st.success("Queued for regeneration!")
                st.rerun()

    elif job["status"] == "resume_pending":
        st.markdown("""
        <div class='syntara-card' style='text-align:center; padding:30px;'>
            <div style='font-size:32px;'>🔄</div>
            <div style='font-weight:700; margin:8px 0;'>Generating Resume</div>
            <div style='color:#64748b; font-size:12px;'>AI is tailoring your resume for this job. Check back in ~15 min.</div>
        </div>
        """, unsafe_allow_html=True)

    elif job["status"] == "applied":
        st.markdown("""
        <div class='syntara-card' style='text-align:center; padding:30px;'>
            <div style='font-size:32px;'>📤</div>
            <div style='font-weight:700; margin:8px 0; color:#a78bfa;'>Applied!</div>
            <div style='color:#64748b; font-size:12px;'>Application submitted. Watch for recruiter replies.</div>
        </div>
        """, unsafe_allow_html=True)

    else:
        st.markdown("""
        <div class='syntara-card' style='text-align:center; padding:30px;'>
            <div style='font-size:32px;'>📄</div>
            <div style='font-weight:700; margin:8px 0;'>No Resume Yet</div>
            <div style='color:#64748b; font-size:12px;'>Click "Queue Resume Gen" to create an AI-tailored resume for this job.</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🤖 Generate Resume Now", key=f"gen_now_{job['match_id']}", type="primary", use_container_width=True):
            execute_sql(f"UPDATE user_job_matches SET status = 'resume_pending' WHERE match_id = '{job['match_id']}'")
            st.success("✅ Queued! Resume will be ready in ~15 minutes.")
            st.rerun()
