"""
Page 3 — Resume Viewer
- List of generated resumes with job details
- Inline markdown editor
- Download as DOCX/PDF
"""

import streamlit as st
import pandas as pd
import json, io, os
from datetime import datetime
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_df, execute_sql
from syntara_styles import inject_styles

inject_styles()

st.title("📄 Resume Viewer & Editor")

# User selector
users_df = query_df("SELECT user_id, full_name FROM users WHERE is_active = 1")
if users_df.empty:
    st.warning("No users. Complete onboarding first.")
    st.stop()

user_options = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
sel_name     = st.selectbox("👤 Select User", list(user_options.keys()))
user_id      = user_options[sel_name]

# Load resumes for this user
resumes_df = query_df(f"""
    SELECT gr.resume_id, gr.job_hash, gr.resume_content,
           gr.resume_version, gr.is_latest,
           gr.generated_at, gr.is_user_edited,
           j.job_title, j.company_name, j.location, j.tech_stack,
           j.apply_link, j.hr_email, j.match_id
    FROM generated_resumes gr
    JOIN jobs_clean_silver j ON gr.job_hash = j.job_hash
    WHERE gr.user_id = '{user_id}' AND gr.is_latest = 1
    ORDER BY gr.generated_at DESC
""")

if resumes_df.empty:
    st.info("No resumes generated yet. Go to Jobs Dashboard and click 'Generate Resume'.")
    st.stop()

st.markdown(f"**{len(resumes_df)} resumes generated** for {sel_name}")

# ── Resume list + Editor ───────────────────────────────────────
for _, resume in resumes_df.iterrows():
    with st.expander(
        f"📄 {resume['job_title']} @ {resume['company_name']}  |  "
        f"v{int(resume['resume_version'] or 1)}  |  "
        f"{'✏️ Edited' if resume['is_user_edited'] else '🤖 AI Generated'}  |  "
        f"{str(resume['generated_at'])[:10]}",
        expanded=False
    ):
        tab_prev, tab_edit, tab_down = st.tabs(["👁️ Preview", "✏️ Edit", "⬇️ Download"])

        res_content = str(resume.get("resume_content", ""))

        # ── PREVIEW ───────────────────────────────────────────
        with tab_prev:
            st.markdown("<div style='background:white; padding:20px; border-radius:8px; color:black;'>", unsafe_allow_html=True)
            st.markdown(res_content)
            st.markdown("</div>", unsafe_allow_html=True)
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Job:** {resume['job_title']} @ {resume['company_name']}")
                st.markdown(f"**Location:** {resume['location']}")
            with col_b:
                if resume.get('hr_email'):
                    st.markdown(f"**HR Email:** `{resume['hr_email']}`")
                    st.markdown(f"🔗 [Apply Here]({resume['apply_link']})")
                else:
                    st.markdown(f"📌 No HR email found — [Apply via link]({resume['apply_link']})")

        # ── EDIT ──────────────────────────────────────────────
        with tab_edit:
            st.info("✏️ Edit your resume content below. Changes are saved instantly.")
            
            edited_text = st.text_area(
                "Resume Content (Markdown)", 
                value=res_content, 
                height=500, 
                key=f"edit_area_{resume['resume_id']}"
            )

            if st.button("💾 Save Edits", key=f"save_{resume['resume_id']}", type="primary"):
                safe_text = edited_text.replace("'", "''")
                execute_sql(f"""
                    UPDATE generated_resumes
                    SET resume_content = '{safe_text}',
                        last_edited_at = CURRENT_TIMESTAMP,
                        is_user_edited = 1
                    WHERE resume_id = '{resume['resume_id']}'
                """)
                st.success("✅ Edits saved!")
                st.rerun()

        # ── DOWNLOAD ──────────────────────────────────────────
        with tab_down:
            st.markdown("**Download Options**")
            
            col_d1, col_d2, col_d3 = st.columns(3)
            
            filename_base = f"{sel_name.replace(' ','_')}_{resume['company_name'].replace(' ','_')}"

            with col_d1:
                st.download_button(
                    "⬇️ Download DOCX (Markdown)",
                    data=res_content,
                    file_name=f"{filename_base}.docx",
                    mime="text/plain",
                    key=f"dl_docx_btn_{resume['resume_id']}"
                )

            with col_d2:
                st.download_button(
                    "⬇️ Download PDF (Markdown)",
                    data=res_content,
                    file_name=f"{filename_base}.pdf",
                    mime="text/plain",
                    key=f"dl_pdf_btn_{resume['resume_id']}"
                )

            with col_d3:
                if st.button("🔄 Regenerate", key=f"regen_{resume['resume_id']}"):
                    execute_sql(f"UPDATE generated_resumes SET is_latest = 0 WHERE resume_id = '{resume['resume_id']}'")
                    execute_sql(f"UPDATE user_job_matches SET resume_generated = 0, status = 'matched', resume_id = NULL WHERE match_id = '{resume['match_id']}'")
                    st.success("Queued for regeneration! Run pipeline to generate.")
