"""
SYNTARA — Page 1: User Onboarding
AI-powered resume parsing + local SQLite DB
"""

import streamlit as st
import uuid, json, re, io, os, requests, sys
from datetime import datetime
from pathlib import Path

# Add parent dir to path for db_utils + styles
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute_sql, insert_row, query_df, esc
from syntara_styles import inject_styles

inject_styles()  # Apply dark theme on every page load

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

# ══════════════════════════════════════════════════════════════
# AI RESUME PARSER
# ══════════════════════════════════════════════════════════════

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract raw text from PDF."""
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return text
    except ImportError:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            return file_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        return file_bytes.decode("utf-8", errors="ignore")

def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract raw text from DOCX."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return ""

def ai_parse_resume(raw_text: str) -> dict:
    """
    Send resume text to NVIDIA NIM → get fully structured JSON back.
    Uses Llama 3.1 70B with a Senior HR prompt.
    """
    trimmed = raw_text[:8000]

    prompt = f"""You are a Senior Technical HR Recruiter and an expert Details Digger.
Your job is to read the following resume and meticulously extract ALL relevant information. Do not hallucinate or skip any companies, roles, or bullet points.
Extract every single technical skill mentioned.

RESUME TEXT:
---
{trimmed}
---

Return ONLY a valid JSON object with the following exact structure. Fill every field. If a field is not found, use an empty string or empty array.
{{
  "full_name": "<candidate full name from top of resume>",
  "preferred_name": "<first name only>",
  "current_title": "<current or most recent job title>",
  "phone": "<phone number with country code if present>",
  "email": "<email address>",
  "linkedin_url": "<full LinkedIn URL>",
  "github_url": "<GitHub URL if present, else ''>",
  "city": "<city>",
  "state": "<state abbreviation like TX, CA>",
  "total_experience_years": <float number like 5.0 or 7.5 (estimate based on work history if not explicitly stated)>,
  "summary": "<professional summary text, 2-3 sentences>",
  "skills": "<ALL technical skills comma-separated: languages, frameworks, tools, databases, cloud platforms>",
  "certifications": "<certifications comma-separated>",
  "work_history": [
    {{
      "company": "<exact company name>",
      "title": "<job title>",
      "start": "<start date like 'Jan 2021' or '2021-01'>",
      "end": "<end date or 'Present'>",
      "bullets": [
        "<bullet point 1 — full text>",
        "<bullet point 2 — full text>"
      ]
    }}
  ],
  "education": [
    {{
      "degree": "<degree name like B.Tech, M.S. in Data Science>",
      "school": "<university name>",
      "year": "<graduation year>",
      "gpa": "<GPA if present>"
    }}
  ]
}}

IMPORTANT RULES:
1. work_history must have ALL jobs listed in the resume. 
2. Include ALL bullet points for each job.
3. Return ONLY the JSON, nothing else. No markdown blocks outside the JSON."""

    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY is not set. Please add it to your .env file.")
        return {}

    try:
        url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}
        }
        resp = requests.post(url, json=payload, timeout=60)
        
        if resp.status_code == 200:
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Try to find JSON block if Gemini includes markdown
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                return json.loads(m.group())
            else:
                return json.loads(content)
        else:
            st.warning(f"AI parse error: {resp.status_code} - {resp.text}")
    except Exception as e:
        st.warning(f"AI parse exception: {e}")
    return {}

def ai_generate_keywords(domain: str) -> str:
    """Uses AI to generate optimal scraping keywords based on the user's target domain."""
    if not GEMINI_API_KEY or not domain:
        return domain

    prompt = f"""You are a Senior Talent Acquisition Architect.
A user wants to scrape job portals (like Dice, LinkedIn, Indeed) for the following domain/interest: '{domain}'.
Generate a comma-separated list of the 5-7 best exact match search phrases or keywords they should use in the search bar.
Examples for Data Engineering: "Data Engineer", "Senior Data Engineer", "PySpark Developer", "Data Warehouse Engineer", "ETL Developer".

Return ONLY the comma-separated list of keywords, nothing else."""

    try:
        url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3}
        }
        resp = requests.post(url, json=payload, timeout=20)
        
        if resp.status_code == 200:
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return content.replace('"', '')
    except Exception:
        pass
    return domain


# ══════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════
st.markdown("<h2 style='color:#f1f5f9; margin-bottom:4px;'>👤 User Onboarding</h2>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; margin-bottom:20px;'>Set up your profile, upload resume, configure clipboards and email accounts.</p>", unsafe_allow_html=True)

# ── User selector ───────────────────────────
existing_users = query_df(f"SELECT user_id, full_name FROM users WHERE is_active = 1 ORDER BY created_at DESC LIMIT 50")

user_opts = {"➕ Create New User": None}
if not existing_users.empty:
    for _, r in existing_users.iterrows():
        user_opts[r["full_name"]] = r["user_id"]

sel = st.selectbox("Select existing user or create new:", list(user_opts.keys()))
if sel != "➕ Create New User":
    st.session_state["current_user_id"] = user_opts[sel]
    st.success(f"✅ Editing profile for **{sel}** (User ID: `{user_opts[sel]}`)")

st.markdown("---")

step = st.session_state.setdefault("onboarding_step", 1)

# ════════════════════════════════════════════════════════
# STEP 1: AI Resume Upload & Parse
# ════════════════════════════════════════════════════════
if step == 1:
    st.markdown("<div class='syntara-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Upload & AI-Parse Resume</div>", unsafe_allow_html=True)
    st.markdown("Upload your existing resume to automatically extract your skills, work history, and contact info.")
    
    st.markdown("<br>", unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "Drop your PDF or DOCX resume here",
        type=["pdf", "docx"],
        help="AI will extract ALL details automatically",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if uploaded:
        file_bytes = uploaded.read()
        file_type  = uploaded.name.split(".")[-1].lower()

        with st.spinner("🤖 AI parsing your resume (Powered by Llama 3.1 70B)..."):
            if file_type == "pdf":
                raw_text = extract_text_from_pdf(file_bytes)
            else:
                raw_text = extract_text_from_docx(file_bytes)

            parsed = ai_parse_resume(raw_text)

        if parsed:
            st.session_state["parsed_resume"]    = parsed
            st.session_state["resume_file_name"] = uploaded.name
            st.session_state["resume_file_type"] = file_type
            st.session_state["resume_bytes"]     = file_bytes
            st.session_state["resume_raw_text"]  = raw_text

            st.success("✅ Resume parsed! Review the extracted data below, then go to **Profile Details** to confirm and save.")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<div class='syntara-card'>", unsafe_allow_html=True)
                st.markdown("**📋 Personal Info Extracted**")
                st.write(f"👤 **Name:** {parsed.get('full_name', '—')}")
                st.write(f"💼 **Title:** {parsed.get('current_title', '—')}")
                st.write(f"📞 **Phone:** {parsed.get('phone', '—') or '⚠️ Not found'}")
                st.write(f"📧 **Email:** {parsed.get('email', '—')}")
                st.write(f"🔗 **LinkedIn:** {parsed.get('linkedin_url', '—') or '—'}")
                st.write(f"🏙️ **Location:** {parsed.get('city', '')}, {parsed.get('state', '')}")
                st.write(f"⏱️ **Experience:** {parsed.get('total_experience_years', 0)} years")
                st.markdown("</div>", unsafe_allow_html=True)

            with col2:
                st.markdown("<div class='syntara-card'>", unsafe_allow_html=True)
                st.markdown("**🛠️ Skills Extracted**")
                skills = parsed.get("skills", "")
                if skills:
                    for s in skills.split(",")[:16]:
                        st.markdown(f"<span class='badge badge-blue'>{s.strip()}</span>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            wh = parsed.get("work_history", [])
            if wh:
                st.markdown(f"<div class='section-title'>Work History — {len(wh)} positions found</div>", unsafe_allow_html=True)
                for job in wh:
                    with st.expander(f"**{job.get('title','Role')}** @ {job.get('company','Company')} | {job.get('start','')} – {job.get('end','')}"):
                        for b in job.get("bullets", [])[:6]:
                            st.write(f"• {b}")
            edu = parsed.get("education", [])
            if edu:
                st.markdown("<div class='section-title'>Education</div>", unsafe_allow_html=True)
                for e in edu:
                    st.write(f"🎓 {e.get('degree','')}, {e.get('school','')}, {e.get('year','')}")
            
            st.markdown("---")
            if st.button("Next: Profile Details ➡️", type="primary", use_container_width=True):
                st.session_state["onboarding_step"] = 2
                st.rerun()

# ════════════════════════════════════════════════════════
# STEP 2: Profile Details Form
# ════════════════════════════════════════════════════════
elif step == 2:
    st.markdown("<div class='section-title'>Profile Details</div>", unsafe_allow_html=True)

    parsed = st.session_state.get("parsed_resume", {})
    user_id = st.session_state.get("current_user_id", "")
    existing_target = ""
    existing_ai_kw = ""

    if user_id and not parsed:
        existing = query_df(f"""
            SELECT u.*, r.skills_extracted, r.work_history_json, r.education_json, r.certifications, r.years_experience, r.resume_label
            FROM users u
            LEFT JOIN user_resumes r ON u.user_id = r.user_id AND r.is_primary = 1
            WHERE u.user_id = '{user_id}'
        """)
        if not existing.empty:
            r = existing.iloc[0]
            parsed = {
                "full_name":            r.get("full_name", ""),
                "preferred_name":       r.get("preferred_name", ""),
                "current_title":        r.get("current_title", ""),
                "phone":                r.get("phone", ""),
                "email":                r.get("email", ""),
                "linkedin_url":         r.get("linkedin_url", ""),
                "github_url":           r.get("github_url", ""),
                "city":                 r.get("city", ""),
                "state":                r.get("state", ""),
                "total_experience_years": float(r.get("years_experience") or r.get("total_experience_years") or 0),
                "skills":               r.get("skills_extracted", ""),
                "work_history":         json.loads(r.get("work_history_json") or "[]"),
                "education":            json.loads(r.get("education_json") or "[]"),
                "certifications":       r.get("certifications", ""),
            }
            existing_target = r.get("target_domains", "")
            existing_ai_kw = r.get("ai_scraping_keywords", "")

    with st.form("profile_form", clear_on_submit=False):
        st.markdown("**👤 Personal Information**")
        c1, c2 = st.columns(2)
        with c1:
            full_name      = st.text_input("Full Name *", value=parsed.get("full_name", ""))
            preferred_name = st.text_input("Preferred Name", value=parsed.get("preferred_name", ""))
            phone          = st.text_input("Phone", value=parsed.get("phone", ""))
            city           = st.text_input("City", value=parsed.get("city", ""))
            state          = st.text_input("State", value=parsed.get("state", ""))
        with c2:
            current_title  = st.text_input("Current Job Title", value=parsed.get("current_title", ""))
            total_exp      = st.number_input("Total Experience (years) *", min_value=0.0, max_value=50.0, value=float(parsed.get("total_experience_years", 0) or 0), step=0.5)
            linkedin_url   = st.text_input("LinkedIn URL", value=parsed.get("linkedin_url", ""))
            github_url     = st.text_input("GitHub URL", value=parsed.get("github_url", ""))

        st.markdown("---")
        st.markdown("**🎯 Scraper Target & Keywords (AI Powered)**")
        st.info("Tell us your target domain. AI will automatically generate the best search keywords for the scraper.")
        target_domains = st.text_input("Target Domain (e.g., Data Engineer, Machine Learning, Full Stack Java)", value=existing_target or parsed.get("current_title", "Data Engineer"))
        
        c3, c4 = st.columns(2)
        with c3:
            skills = st.text_area("Skills (comma-separated)", value=parsed.get("skills", ""), height=90)
            resume_label = st.text_input("Resume Label", value="Primary Resume")
            certifications = st.text_input("Certifications", value=parsed.get("certifications", ""))
        with c4:
            min_match_score = st.slider("Minimum Match Score to Show (%)", 20, 90, 40)
            daily_limit     = st.number_input("Daily Resume Generation Limit", 5, 50, 10)

        st.markdown("---")
        st.markdown("**💼 Work History**")
        wh_raw = parsed.get("work_history", [])
        wh_for_editor = []
        for job in wh_raw:
            wh_for_editor.append({
                "Company": job.get("company", ""),
                "Title": job.get("title", ""),
                "Start": job.get("start", ""),
                "End": job.get("end", ""),
                "Bullets (newline separated)": "\\n".join(job.get("bullets", []))
            })
            
        edited_wh = st.data_editor(wh_for_editor, num_rows="dynamic", use_container_width=True, height=250, column_config={"Bullets (newline separated)": st.column_config.TextColumn("Bullets", width="large")})

        st.markdown("**🎓 Education**")
        edu_raw = parsed.get("education", [])
        edited_edu = st.data_editor(edu_raw, num_rows="dynamic", use_container_width=True, height=150)

        st.markdown("---")
        b1, b2 = st.columns(2)
        with b1:
            if st.form_submit_button("⬅️ Back to Upload", use_container_width=True):
                st.session_state["onboarding_step"] = 1
                st.rerun()
        with b2:
            save_btn = st.form_submit_button("💾 Save Profile & Generate Keywords", use_container_width=True, type="primary")

    if save_btn:
        if not full_name or not target_domains:
            st.error("Full Name and Target Domain are required!")
        else:
            with st.spinner("🤖 Generating scraping keywords from your domain..."):
                final_ai_kw = ai_generate_keywords(target_domains)

            wh_parsed = []
            for row in edited_wh:
                if row.get("Company") or row.get("Title"):
                    bullets = [b.strip() for b in row.get("Bullets (newline separated)", "").split("\\n") if b.strip()]
                    wh_parsed.append({
                        "company": row.get("Company", ""),
                        "title": row.get("Title", ""),
                        "start": row.get("Start", ""),
                        "end": row.get("End", ""),
                        "bullets": bullets
                    })

            if not user_id:
                user_id = str(uuid.uuid4())

            resume_id = str(uuid.uuid4())
            now = datetime.now()

            user_row = {
                "user_id":               user_id,
                "full_name":             full_name,
                "preferred_name":        preferred_name or full_name.split()[0],
                "current_title":         current_title,
                "target_title":          target_domains, # Use domain as target
                "total_experience_years":total_exp,
                "phone":                 phone,
                "city":                  city,
                "state":                 state,
                "linkedin_url":          linkedin_url,
                "github_url":            github_url,
                "portfolio_url":         "",
                "min_match_score":       int(min_match_score),
                "daily_resume_limit":    int(daily_limit),
                "created_at":            now,
                "updated_at":            now,
                "is_active":             True,
                "target_domains":        target_domains,
                "ai_scraping_keywords":  final_ai_kw
            }

            resume_row = {
                "resume_id":          resume_id,
                "user_id":            user_id,
                "file_name":          st.session_state.get("resume_file_name", "resume.pdf"),
                "file_path":          f"local/{user_id}/",
                "file_type":          st.session_state.get("resume_file_type", "pdf"),
                "resume_label":       resume_label,
                "years_experience":   total_exp,
                "skills_extracted":   skills,
                "summary_text":       parsed.get("summary", ""),
                "work_history_json":  json.dumps(wh_parsed),
                "education_json":     json.dumps(edited_edu),
                "certifications":     certifications,
                "uploaded_at":        now,
                "is_primary":         True,
            }

            with st.spinner("Saving to SQLite..."):
                ok_user, err_user = insert_row(f"users", user_row)
                if not ok_user and "UNIQUE constraint failed" in err_user:
                    e_name  = esc(full_name)
                    e_tgt   = esc(target_domains)
                    e_phone = esc(phone)
                    e_kw    = esc(final_ai_kw)
                    update_sql = f"UPDATE users SET full_name='{e_name}', target_domains='{e_tgt}', total_experience_years={total_exp}, phone='{e_phone}', ai_scraping_keywords='{e_kw}', updated_at='{now.isoformat()}' WHERE user_id='{user_id}'"
                    ok_user, _, err_user = execute_sql(update_sql)

                ok_res, err_res = insert_row(f"user_resumes", resume_row)

            if ok_user:
                st.session_state["current_user_id"] = user_id
                st.success(f"✅ Profile saved! AI Keywords generated: `{final_ai_kw}`")
                st.balloons()
            else:
                st.error(f"❌ Save failed: {err_user}")

