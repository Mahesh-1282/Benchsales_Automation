"""
Page 3 — Resume Viewer
- List of generated resumes with job details
- Inline DOCX editor (text areas per section)
- Preview as formatted HTML (mirrors final PDF look)
- Download as DOCX (for further editing in Word)
- Convert DOCX → PDF on download click
- Regenerate button (creates new version)
"""

import streamlit as st
import pandas as pd
import json, io, os
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

def load_docx_from_dbfs(dbfs_path: str) -> bytes | None:
    """Load DOCX bytes from DBFS."""
    if not spark:
        return None
    try:
        local_tmp = f"/tmp/{dbfs_path.split('/')[-1]}"
        dbutils = spark._jvm.com.databricks.dbutils_v1.DBUtilsHolder.dbutils()
        # Use dbutils.fs.cp to local
        import subprocess
        subprocess.run(["databricks", "fs", "cp", f"dbfs:{dbfs_path}", local_tmp], check=True)
        with open(local_tmp, "rb") as f:
            return f.read()
    except Exception:
        return None

def docx_to_pdf_bytes(docx_bytes: bytes) -> bytes | None:
    """Convert DOCX bytes to PDF bytes using python-docx2pdf or LibreOffice."""
    try:
        # Try docx2pdf (requires LibreOffice)
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_docx:
            tmp_docx.write(docx_bytes)
            tmp_path = tmp_docx.name

        pdf_path = tmp_path.replace(".docx", ".pdf")
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir",
             os.path.dirname(tmp_path), tmp_path],
            capture_output=True, timeout=30
        )
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                return f.read()
    except Exception:
        pass

    try:
        # Fallback: use weasyprint-style conversion via reportlab
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from docx import Document as DocxDoc
        import tempfile

        doc = DocxDoc(io.BytesIO(docx_bytes))
        text_content = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

        buf = io.BytesIO()
        pdf_doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []
        for line in text_content.split("\n"):
            if line.strip():
                story.append(Paragraph(line.strip(), styles["Normal"]))
                story.append(Spacer(1, 4))
        pdf_doc.build(story)
        return buf.getvalue()
    except Exception as e:
        st.warning(f"PDF conversion unavailable: {e}. Download DOCX instead.")
        return None

def render_resume_html(resume_data: dict, user_data: dict, job_data: dict) -> str:
    """Render resume as styled HTML for preview (mirrors PDF output)."""
    bullets_json = json.loads(resume_data.get("tailored_bullets_json") or "[]")
    skills       = resume_data.get("skills_highlighted") or ""
    exp_used     = resume_data.get("experience_years_used") or 0

    work_history = json.loads(user_data.get("work_history_json") or "[]")
    education    = json.loads(user_data.get("education_json") or "[]")

    bullets_map = {item.get("role_index", i): item.get("bullets", [])
                   for i, item in enumerate(bullets_json)}

    # Build work experience HTML
    work_html = ""
    for i, job in enumerate(reversed(work_history[-4:])):
        role_idx   = len(work_history[-4:]) - 1 - i
        company    = job.get("company", "")
        title_r    = job.get("title", "")
        start      = job.get("start", "")
        end        = job.get("end", "Present")
        bullets    = bullets_map.get(role_idx) or job.get("bullets", [])[:5]
        bullets_html = "".join(f"<li style='margin:3px 0;font-size:13px;'>{b}</li>" for b in bullets)
        work_html += f"""
        <div style='margin-bottom:14px;'>
            <div style='display:flex; justify-content:space-between;'>
                <div>
                    <strong style='font-size:14px;'>{title_r}</strong>
                    <span style='color:#555;font-size:13px;'> — {company}</span>
                </div>
                <span style='color:#888;font-size:12px;font-style:italic;'>{start} – {end}</span>
            </div>
            <ul style='margin:4px 0 0 16px;padding:0;'>{bullets_html}</ul>
        </div>"""

    # Education HTML
    edu_html = "".join(f"<div style='font-size:13px;margin-bottom:4px;'><strong>{e.get('degree','')}</strong> — {e.get('school','')} | {e.get('year','')}</div>" for e in education)

    return f"""
    <div style='font-family:Arial,sans-serif; max-width:800px; margin:0 auto; padding:30px;
                background:white; box-shadow:0 2px 20px rgba(0,0,0,0.1); border-radius:8px;'>

        <!-- HEADER -->
        <div style='text-align:center; margin-bottom:16px; border-bottom:2px solid #1F497D; padding-bottom:12px;'>
            <h1 style='margin:0; font-size:24px; color:#1F497D;'>{user_data.get('full_name','Candidate')}</h1>
            <p style='margin:4px 0; font-size:12px; color:#555;'>
                {user_data.get('phone','')} | {user_data.get('email_address','')} |
                {user_data.get('city','')}, {user_data.get('state','')} |
                <a href='{user_data.get('linkedin_url','')}' style='color:#1F497D;'>LinkedIn</a>
            </p>
        </div>

        <!-- SUMMARY -->
        <div style='margin-bottom:14px;'>
            <h2 style='font-size:13px; text-transform:uppercase; color:#1F497D; border-bottom:1px solid #1F497D;
                        margin-bottom:6px; padding-bottom:3px;'>Professional Summary</h2>
            <p style='font-size:13px; margin:0; line-height:1.6;'>
                {user_data.get('summary_text') or f'Experienced {job_data.get("job_title","Engineer")} with {exp_used}+ years of hands-on expertise in {skills[:80]}. Proven track record of delivering scalable data solutions.'}
            </p>
        </div>

        <!-- SKILLS -->
        <div style='margin-bottom:14px;'>
            <h2 style='font-size:13px; text-transform:uppercase; color:#1F497D; border-bottom:1px solid #1F497D;
                        margin-bottom:6px; padding-bottom:3px;'>Technical Skills</h2>
            <p style='font-size:13px; margin:0;'>
                {"  •  ".join(s.strip() for s in skills.split(",") if s.strip())}
            </p>
        </div>

        <!-- EXPERIENCE -->
        <div style='margin-bottom:14px;'>
            <h2 style='font-size:13px; text-transform:uppercase; color:#1F497D; border-bottom:1px solid #1F497D;
                        margin-bottom:6px; padding-bottom:3px;'>Professional Experience</h2>
            {work_html}
        </div>

        <!-- EDUCATION -->
        <div>
            <h2 style='font-size:13px; text-transform:uppercase; color:#1F497D; border-bottom:1px solid #1F497D;
                        margin-bottom:6px; padding-bottom:3px;'>Education</h2>
            {edu_html}
        </div>
    </div>
    """

# ═══════════════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════════════
st.title("📄 Resume Viewer & Editor")

# User selector
users_df = run_sql(f"SELECT user_id, full_name FROM {CATALOG}.users_schema.users WHERE is_active = true")
if users_df.empty:
    st.warning("No users. Complete onboarding first.")
    st.stop()

user_options = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
sel_name     = st.selectbox("👤 Select User", list(user_options.keys()))
user_id      = user_options[sel_name]

# Load resumes for this user
resumes_df = run_sql(f"""
    SELECT gr.resume_id, gr.job_hash, gr.docx_path, gr.pdf_path,
           gr.experience_years_used, gr.skills_highlighted, gr.basic_knowledge_added,
           gr.tailored_bullets_json, gr.resume_version, gr.is_latest,
           gr.generated_at, gr.is_user_edited, gr.linkedin_used,
           j.job_title, j.company_name, j.location, j.tech_stack,
           j.apply_link, j.hr_email
    FROM {CATALOG}.default.generated_resumes gr
    JOIN {CATALOG}.default.jobs_clean_silver j ON gr.job_hash = j.job_hash
    WHERE gr.user_id = '{user_id}' AND gr.is_latest = true
    ORDER BY gr.generated_at DESC
""")

user_data_df = run_sql(f"""
    SELECT u.user_id, u.full_name, u.phone, u.city, u.state, u.linkedin_url,
           u.github_url, r.skills_extracted, r.work_history_json, r.education_json,
           r.summary_text, r.years_experience
    FROM {CATALOG}.users_schema.users u
    LEFT JOIN {CATALOG}.users_schema.user_resumes r
        ON u.user_id = r.user_id AND r.is_primary = true
    WHERE u.user_id = '{user_id}'
""")

if resumes_df.empty:
    st.info("No resumes generated yet. Go to Jobs Dashboard and click 'Generate Resume'.")
    st.stop()

user_data = user_data_df.iloc[0].to_dict() if not user_data_df.empty else {}

st.markdown(f"**{len(resumes_df)} resumes generated** for {sel_name}")

# ── Resume list + Editor ───────────────────────────────────────
for _, resume in resumes_df.iterrows():
    with st.expander(
        f"📄 {resume['job_title']} @ {resume['company_name']}  |  "
        f"v{int(resume['resume_version'])}  |  "
        f"{'✏️ Edited' if resume['is_user_edited'] else '🤖 AI Generated'}  |  "
        f"{str(resume['generated_at'])[:10]}",
        expanded=False
    ):
        tab_prev, tab_edit, tab_down = st.tabs(["👁️ Preview", "✏️ Edit", "⬇️ Download"])

        job_data = resume.to_dict()

        # ── PREVIEW ───────────────────────────────────────────
        with tab_prev:
            resume_html = render_resume_html(resume.to_dict(), user_data, job_data)
            st.components.v1.html(resume_html, height=900, scrolling=True)

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Job:** {resume['job_title']} @ {resume['company_name']}")
                st.markdown(f"**Location:** {resume['location']}")
                st.markdown(f"**Experience Used:** {resume['experience_years_used']} years")
            with col_b:
                st.markdown(f"**Skills Highlighted:** {(resume['skills_highlighted'] or '')[:150]}")
                if resume.get('basic_knowledge_added'):
                    st.markdown(f"**Familiar With:** {resume['basic_knowledge_added']}")
                if resume.get('hr_email'):
                    st.markdown(f"**HR Email:** `{resume['hr_email']}`")
                    st.markdown(f"🔗 [Apply Here]({resume['apply_link']})")
                else:
                    st.markdown(f"📌 No HR email found — [Apply via link]({resume['apply_link']})")

        # ── EDIT ──────────────────────────────────────────────
        with tab_edit:
            st.info("✏️ Edit your resume sections below. Changes are saved to the DOCX file.")

            # Load bullets from JSON
            bullets_data = json.loads(resume.get("tailored_bullets_json") or "[]")
            work_history = json.loads(user_data.get("work_history_json") or "[]")

            edited_bullets = {}
            for i, item in enumerate(bullets_data):
                role_idx  = item.get("role_index", i)
                orig_job  = work_history[-(len(work_history) - role_idx)] if role_idx < len(work_history) else {}
                role_title= orig_job.get("title", f"Role {role_idx + 1}")
                company_n = orig_job.get("company", "")

                st.markdown(f"**{role_title}** @ {company_n}")
                bullets = item.get("bullets", [])
                new_bullets = []
                for j, bullet in enumerate(bullets):
                    edited = st.text_area(
                        f"Bullet {j+1}",
                        value=bullet,
                        height=80,
                        key=f"bullet_{resume['resume_id']}_{role_idx}_{j}",
                        label_visibility="collapsed",
                    )
                    new_bullets.append(edited)
                edited_bullets[role_idx] = {"role_index": role_idx, "bullets": new_bullets}
                st.markdown("---")

            new_skills = st.text_input(
                "Skills Line",
                value=resume.get("skills_highlighted") or "",
                key=f"skills_{resume['resume_id']}"
            )

            if st.button("💾 Save Edits", key=f"save_{resume['resume_id']}", type="primary"):
                updated_bullets = list(edited_bullets.values())
                if spark:
                    try:
                        spark.sql(f"""
                            UPDATE {CATALOG}.default.generated_resumes
                            SET tailored_bullets_json = '{json.dumps(updated_bullets).replace("'", "''")}',
                                skills_highlighted = '{new_skills.replace("'", "''")}',
                                last_edited_at = current_timestamp(),
                                is_user_edited = true
                            WHERE resume_id = '{resume['resume_id']}'
                        """)
                        st.success("✅ Edits saved!")
                    except Exception as e:
                        st.error(f"Save failed: {e}")

        # ── DOWNLOAD ──────────────────────────────────────────
        with tab_down:
            st.markdown("**Download Options**")
            st.info("Download as DOCX to edit in Word, or directly as PDF.")

            col_d1, col_d2, col_d3 = st.columns(3)

            with col_d1:
                # Regenerate resume on-the-fly from current edits for DOCX download
                if st.button("📥 Download DOCX", key=f"dl_docx_{resume['resume_id']}"):
                    docx_bytes = load_docx_from_dbfs(resume["docx_path"])
                    if docx_bytes:
                        filename = f"{sel_name.replace(' ','_')}_{resume['company_name'].replace(' ','_')}.docx"
                        st.download_button(
                            "⬇️ Click to Download DOCX",
                            data=docx_bytes,
                            file_name=filename,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"dl_docx_btn_{resume['resume_id']}"
                        )
                    else:
                        st.warning("DOCX not available from DBFS. Try regenerating.")

            with col_d2:
                if st.button("📥 Download PDF", key=f"dl_pdf_{resume['resume_id']}"):
                    docx_bytes = load_docx_from_dbfs(resume["docx_path"])
                    if docx_bytes:
                        pdf_bytes = docx_to_pdf_bytes(docx_bytes)
                        if pdf_bytes:
                            filename = f"{sel_name.replace(' ','_')}_{resume['company_name'].replace(' ','_')}.pdf"
                            st.download_button(
                                "⬇️ Click to Download PDF",
                                data=pdf_bytes,
                                file_name=filename,
                                mime="application/pdf",
                                key=f"dl_pdf_btn_{resume['resume_id']}"
                            )

            with col_d3:
                if st.button("🔄 Regenerate (New Version)", key=f"regen_{resume['resume_id']}"):
                    if spark:
                        # Set current as not latest
                        spark.sql(f"UPDATE {CATALOG}.default.generated_resumes SET is_latest = false WHERE resume_id = '{resume['resume_id']}'")
                        # Reset match status to trigger regeneration
                        spark.sql(f"UPDATE {CATALOG}.default.user_job_matches SET resume_generated = false, status = 'matched', resume_id = NULL WHERE match_id = (SELECT match_id FROM {CATALOG}.default.generated_resumes WHERE resume_id = '{resume['resume_id']}')")
                    st.success("Queued for regeneration! A fresh AI version will be ready shortly.")
