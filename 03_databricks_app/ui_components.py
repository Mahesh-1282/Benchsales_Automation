import streamlit as st
from db_utils import query_df, update_row
import time
import os

@st.dialog("📄 View / Edit Resume", width="large")
def resume_modal(match_id):
    # Fetch resume from DB
    resume = query_df(f"SELECT * FROM generated_resumes WHERE match_id = '{match_id}' AND is_latest = 1")
    if resume.empty:
        st.warning("No generated resume found for this job.")
        if st.button("Close"):
            st.rerun()
        return
        
    resume_id = resume.iloc[0]["resume_id"]
    resume_text = resume.iloc[0]["resume_content"]
    
    # Session state to track changes
    state_key = f"resume_text_{resume_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = resume_text

    edited_text = st.text_area("Resume Content (Markdown)", value=st.session_state[state_key], height=400, key=f"area_{resume_id}")
    
    st.markdown("---")
    c1, c2, c3 = st.columns([1, 1, 2])
    
    with c1:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            update_row("generated_resumes", {"resume_content": edited_text}, f"resume_id = '{resume_id}'")
            st.session_state[state_key] = edited_text
            st.success("Resume saved successfully!")
            time.sleep(1.5)
            st.rerun()
            
    with c2:
        if st.button("❌ Close", use_container_width=True):
            if edited_text != st.session_state[state_key]:
                st.session_state[f"confirm_close_{resume_id}"] = True
            else:
                st.rerun()
                
    if st.session_state.get(f"confirm_close_{resume_id}"):
        st.warning("⚠️ You have unsaved changes. Are you sure you want to discard them?")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("Yes, Discard"):
                st.session_state[state_key] = resume_text # reset
                del st.session_state[f"confirm_close_{resume_id}"]
                st.rerun()
        with cc2:
            if st.button("No, Keep Editing"):
                del st.session_state[f"confirm_close_{resume_id}"]
                st.rerun()

import re

def render_job_card(job, user_id):
    # Get logo char
    portal = str(job['portal'])
    company = str(job['company_name'])
    c_letter = company[0].upper() if company else "🏢"
    
    # Tags
    loc = job.get('location') or 'Not specified'
    rem = job.get('remote_type') or 'Onsite'
    posted = job.get('posted_date') or 'Recently'
    salary = job.get('salary_range') or 'Not Disclosed'
    
    # Clean HTML from description
    raw_desc = str(job.get('job_description', ''))
    clean_desc = re.sub(r'<[^>]+>', '', raw_desc)[:250] + "..."
    
    # Horizontal Skills
    tech_stack = str(job.get('tech_stack', 'N/A'))
    skills_html = "".join([
        f"<span style='padding:4px 10px; background:#f5f3ff; color:#6d28d9; border:1px solid #ddd6fe; border-radius:6px; font-weight:500; font-size:12px;'>{s.strip()}</span>"
        for s in tech_stack.split(',') if s.strip()
    ])
    
    match_score = job.get('match_score', 0)
    badge_class = "badge-green" if match_score >= 80 else ("badge-yellow" if match_score >= 50 else "badge-red")
    
    st.markdown(f"""
    <div class="job-card" style="display:flex; flex-direction:column; gap:16px; padding:24px; border-radius:16px; background:#fff; border:1px solid #e2e8f0; box-shadow:0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom:20px; transition:all 0.2s;">
        <div class="job-card-header" style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div style="display:flex; gap:16px; align-items:center;">
                <div class="job-card-logo" style="width:56px; height:56px; border-radius:12px; display:flex; justify-content:center; align-items:center; font-size:26px; font-weight:800; color:#8b5cf6; background:rgba(139,92,246,0.12);">
                    {c_letter}
                </div>
                <div>
                    <h4 class="job-card-title" style="margin:0; font-size:20px; font-weight:700; color:#0f172a;">{job['job_title']}</h4>
                    <div class="job-card-company" style="font-size:14px; color:#475569; margin-top:4px;">
                        <strong>{company}</strong> • <span style="color:#64748b;">via {portal}</span>
                    </div>
                </div>
            </div>
            <div>
                <span class="badge {badge_class}" style="font-size:14px; padding:6px 12px; border-radius:20px; font-weight:600;">🎯 {match_score}% Match</span>
            </div>
        </div>
        
        <div class="job-card-tags" style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
            <span style="background:#f8fafc; padding:4px 12px; border-radius:16px; font-size:12px; color:#475569; font-weight:500; border:1px solid #e2e8f0;">📍 {loc}</span>
            <span style="background:#f8fafc; padding:4px 12px; border-radius:16px; font-size:12px; color:#475569; font-weight:500; border:1px solid #e2e8f0;">💰 {salary}</span>
            <span style="background:#f8fafc; padding:4px 12px; border-radius:16px; font-size:12px; color:#475569; font-weight:500; border:1px solid #e2e8f0;">💼 {rem}</span>
            <span style="background:#ecfdf5; padding:4px 12px; border-radius:16px; font-size:12px; color:#047857; font-weight:500; border:1px solid #a7f3d0;">⏱️ {posted}</span>
        </div>
        
        <div style="padding:14px; background:#f8fafc; border-radius:12px; border:1px solid #f1f5f9; font-size:14px; color:#475569; line-height:1.6; margin-top:4px;">
            <strong style="color:#1e293b;">Overview:</strong> {clean_desc}
        </div>
        
        <div style="margin-top:4px;">
            <span style="display:block; font-size:11px; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Tech Stack:</span>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
                {skills_html}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Check if a resume exists
    resume = query_df(f"SELECT * FROM generated_resumes WHERE match_id = '{job['match_id']}' AND is_latest = 1")
    has_resume = not resume.empty
    
    # Actions row using container with buttons
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        if not has_resume:
            if st.button("📄 Generate", key=f"res_{job['match_id']}", use_container_width=True):
                st.info("Resume generation started (Placeholder).")
        else:
            if st.button("📝 View / Edit", key=f"edit_{job['match_id']}", type="secondary", use_container_width=True):
                resume_modal(job['match_id'])
    with c2:
        if has_resume:
            fmt = st.session_state.get("default_download_format", "DOCX")
            res_content = str(resume.iloc[0].get("resume_content", ""))
            file_ext = "docx" if fmt == "DOCX" else "pdf"
            st.download_button(
                label=f"⬇️ Download {fmt}",
                data=res_content,
                file_name=f"{company}_Resume.{file_ext}",
                mime="text/plain",
                key=f"dl_btn_{job['match_id']}",
                use_container_width=True
            )
    with c3:
        if st.button("✅ Apply", key=f"sel_{job['match_id']}", type="primary", use_container_width=True):
            st.write(f"Apply Link: [Click Here]({job.get('apply_link', '#')})")
    with c4:
        pass # spacer
    st.write("") # Spacer below card
