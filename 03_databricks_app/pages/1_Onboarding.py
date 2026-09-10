"""
SYNTRA — Page 1: User Onboarding
AI-powered resume parsing + fixed DB save via REST API
"""

import streamlit as st
import uuid, json, re, io, os, requests, sys
from datetime import datetime
from pathlib import Path

# Add parent dir to path for db_utils + styles
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute_sql, insert_row, query_df, esc
from syntra_styles import inject_styles

inject_styles()  # Apply dark theme on every page load

CATALOG = "jobs_automation_db"
NVIDIA_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
NVIDIA_URL     = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL   = "meta/llama-3.1-8b-instruct"


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
    This is FAR more reliable than regex-based parsing.
    """
    # Trim to 6000 chars for API
    trimmed = raw_text[:6000]

    prompt = f"""You are an expert resume parser. Extract ALL information from this resume and return ONLY valid JSON.

RESUME TEXT:
---
{trimmed}
---

Return this exact JSON structure (fill every field, empty string if not found):
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
  "total_experience_years": <float number like 5.0 or 7.5>,
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
        "<bullet point 2 — full text>",
        "<bullet point 3 — full text>",
        "<bullet point 4 — full text>",
        "<bullet point 5 — full text>"
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

IMPORTANT: work_history must have ALL jobs listed in the resume. Include ALL bullet points."""

    if not NVIDIA_API_KEY:
        # Fallback to regex parsing
        return regex_parse_resume(raw_text)

    try:
        resp = requests.post(
            NVIDIA_URL,
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":       NVIDIA_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens":  3000,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Extract JSON from response
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                return parsed
    except json.JSONDecodeError as e:
        st.warning(f"AI parse JSON error: {e}. Using regex fallback.")
    except Exception as e:
        st.warning(f"AI parse error: {e}. Using regex fallback.")

    return regex_parse_resume(raw_text)


def regex_parse_resume(text: str) -> dict:
    """Regex fallback parser — handles most common resume formats."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    result = {
        "full_name": "", "preferred_name": "", "current_title": "",
        "phone": "", "email": "", "linkedin_url": "", "github_url": "",
        "city": "", "state": "", "total_experience_years": 0.0,
        "summary": "", "skills": "", "certifications": "",
        "work_history": [], "education": [],
    }

    # Name — usually first non-empty line
    if lines:
        first = lines[0]
        if len(first.split()) <= 5 and not "@" in first and not "http" in first.lower():
            result["full_name"] = first.title()
            result["preferred_name"] = first.split()[0].title()

    # Second line often has title
    if len(lines) > 1:
        second = lines[1]
        if "|" in second or "·" in second or "," in second:
            result["current_title"] = second.split("|")[0].split("·")[0].strip()

    # Phone — more permissive regex
    phone_m = re.search(r"(?:\+1[\s\-]?)?(?:\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})", text)
    if phone_m:
        result["phone"] = phone_m.group().strip()

    # Email
    email_m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    if email_m:
        result["email"] = email_m.group().lower()

    # LinkedIn
    li_m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+", text, re.I)
    if li_m:
        url = li_m.group()
        result["linkedin_url"] = url if url.startswith("http") else "https://" + url

    # GitHub
    gh_m = re.search(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+", text, re.I)
    if gh_m:
        url = gh_m.group()
        result["github_url"] = url if url.startswith("http") else "https://" + url

    # Location
    loc_m = re.search(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*([A-Z]{2})\b", text)
    if loc_m:
        result["city"]  = loc_m.group(1)
        result["state"] = loc_m.group(2)

    # Experience years
    exp_m = re.search(r"(\d+\.?\d*)\+?\s*years?\s+(?:of\s+)?(?:total\s+)?experience", text, re.I)
    if exp_m:
        result["total_experience_years"] = float(exp_m.group(1))

    # Skills — scan for known tech
    known_techs = [
        "Python", "PySpark", "Spark", "SQL", "T-SQL", "dbt", "Databricks",
        "Azure", "AWS", "GCP", "Kafka", "Airflow", "Scala", "Java",
        "Delta Lake", "Snowflake", "Redshift", "BigQuery", "Pandas", "NumPy",
        "TensorFlow", "PyTorch", "Docker", "Kubernetes", "Git", "Tableau",
        "Power BI", "Hadoop", "Hive", "Terraform", "Jenkins", "REST API",
        "FastAPI", "PostgreSQL", "MySQL", "MongoDB", "Elasticsearch",
        "Azure Data Factory", "Azure Synapse", "AWS Glue", "EMR",
        "IBM DataStage", "Informatica", "Kinesis", "Event Hub",
        "DataStage", "Microsoft Fabric", "Oracle", "SQL Server",
        "PL/SQL", "ANSI SQL", "MLflow", "Scikit-learn", "Streamlit",
    ]
    found_skills = [t for t in known_techs if t.lower() in text.lower()]
    result["skills"] = ", ".join(found_skills)

    # Work history — look for date patterns to find job blocks
    job_blocks = []
    current_block = None

    # Date pattern: Month Year – Month Year / Present
    date_pattern = re.compile(
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|"
        r"\d{4})\s*[–\-—]\s*"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|"
        r"\d{4}|Present|Current|Now)",
        re.I
    )

    for i, line in enumerate(lines):
        dm = date_pattern.search(line)
        if dm:
            if current_block:
                job_blocks.append(current_block)
            # Look back for title and company
            title_line   = lines[i-1] if i >= 1 else ""
            company_line = lines[i-2] if i >= 2 else ""

            # Sometimes title and company are in same line separated by ·  |  —
            if "·" in title_line or "|" in title_line or "—" in title_line:
                parts = re.split(r"[·|—]", title_line)
                title_part   = parts[0].strip()
                company_part = parts[1].strip() if len(parts) > 1 else company_line
            else:
                title_part   = title_line
                company_part = company_line

            current_block = {
                "company": company_part[:80],
                "title":   title_part[:80],
                "start":   dm.group(1),
                "end":     dm.group(2),
                "bullets": [],
            }
        elif current_block and (line.startswith("•") or line.startswith("-") or line.startswith("◦") or line.startswith("–")):
            bullet = re.sub(r"^[•\-◦–]\s*", "", line).strip()
            if len(bullet) > 20:
                current_block["bullets"].append(bullet)

    if current_block:
        job_blocks.append(current_block)

    result["work_history"] = [b for b in job_blocks if b.get("company") or b.get("bullets")]

    # Education
    edu = []
    edu_keywords = ["B.Tech", "B.E", "M.Tech", "M.S.", "MBA", "Bachelor", "Master",
                    "Ph.D", "B.Sc", "M.Sc", "B.Com", "BCA", "MCA", "BE", "ME"]
    for i, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in edu_keywords):
            yr_m = re.search(r"\b(19|20)\d{2}\b", line)
            gpa_m = re.search(r"GPA[:\s]+(\d+\.?\d*)", line, re.I)
            edu.append({
                "degree": line[:120],
                "school": lines[i+1][:80] if i + 1 < len(lines) else "",
                "year":   yr_m.group() if yr_m else "",
                "gpa":    gpa_m.group(1) if gpa_m else "",
            })

    result["education"] = edu[:3]

    return result


# ══════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════
st.markdown("<h2 style='color:#f1f5f9; margin-bottom:4px;'>👤 User Onboarding</h2>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; margin-bottom:20px;'>Set up your profile, upload resume, configure clipboards and email accounts.</p>", unsafe_allow_html=True)

# ── User selector (returning user) ───────────────────────────
existing_users = query_df(f"SELECT user_id, full_name FROM {CATALOG}.users_schema.users WHERE is_active = true ORDER BY created_at DESC LIMIT 50")

if not existing_users.empty:
    user_opts = {"➕ Create New User": None}
    for _, r in existing_users.iterrows():
        user_opts[r["full_name"]] = r["user_id"]

    sel = st.selectbox("Select existing user or create new:", list(user_opts.keys()))
    if sel != "➕ Create New User":
        st.session_state["current_user_id"] = user_opts[sel]
        st.success(f"✅ Editing profile for **{sel}** (User ID: `{user_opts[sel]}`)")

st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["📄 Resume Upload", "👤 Profile Details", "📧 Email Setup", "🗂️ Clipboards"])

# ════════════════════════════════════════════════════════
# TAB 1: AI Resume Upload & Parse
# ════════════════════════════════════════════════════════
with tab1:
    st.markdown("<div class='syntra-card'>", unsafe_allow_html=True)
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

        with st.spinner("🤖 AI parsing your resume (this takes ~15 seconds)..."):
            if file_type == "pdf":
                raw_text = extract_text_from_pdf(file_bytes)
            else:
                raw_text = extract_text_from_docx(file_bytes)

            parsed = ai_parse_resume(raw_text)

        # Store in session
        st.session_state["parsed_resume"]    = parsed
        st.session_state["resume_file_name"] = uploaded.name
        st.session_state["resume_file_type"] = file_type
        st.session_state["resume_bytes"]     = file_bytes
        st.session_state["resume_raw_text"]  = raw_text

        st.success("✅ Resume parsed! Review the extracted data below, then go to **Profile Details** to confirm and save.")

        # Preview in two columns
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='syntra-card'>", unsafe_allow_html=True)
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
            st.markdown("<div class='syntra-card'>", unsafe_allow_html=True)
            st.markdown("**🛠️ Skills Extracted**")
            skills = parsed.get("skills", "")
            if skills:
                for s in skills.split(",")[:16]:
                    st.markdown(f"<span class='badge badge-blue'>{s.strip()}</span>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # Work history preview
        wh = parsed.get("work_history", [])
        if wh:
            st.markdown(f"<div class='section-title'>Work History — {len(wh)} positions found</div>", unsafe_allow_html=True)
            for job in wh:
                with st.expander(f"**{job.get('title','Role')}** @ {job.get('company','Company')} | {job.get('start','')} – {job.get('end','')}"):
                    for b in job.get("bullets", [])[:6]:
                        st.write(f"• {b}")
                    if not job.get("bullets"):
                        st.write("*No bullets extracted*")
        else:
            st.warning("⚠️ Work history not extracted. You can paste it manually in the Profile Details tab.")

        # Education preview
        edu = parsed.get("education", [])
        if edu:
            st.markdown("<div class='section-title'>Education</div>", unsafe_allow_html=True)
            for e in edu:
                st.write(f"🎓 {e.get('degree','')}, {e.get('school','')}, {e.get('year','')}")

        st.info("👉 Go to **Profile Details** tab to confirm, edit if needed, and save.")

    else:
        st.markdown("""
        <div class='syntra-card' style='text-align:center; padding:40px;'>
            <div style='font-size:48px;'>📄</div>
            <div style='font-size:16px; font-weight:600; margin:12px 0 8px;'>Upload Your Resume</div>
            <div style='color:#64748b; font-size:13px;'>Supported: PDF, DOCX • AI extracts name, phone, skills, work history, education</div>
        </div>
        """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════
# TAB 2: Profile Details Form
# ════════════════════════════════════════════════════════
with tab2:
    st.markdown("<div class='section-title'>Profile Details</div>", unsafe_allow_html=True)

    parsed = st.session_state.get("parsed_resume", {})
    user_id = st.session_state.get("current_user_id", "")

    # If editing existing user, load from DB
    if user_id and not parsed:
        existing = query_df(f"""
            SELECT u.*, r.skills_extracted, r.work_history_json, r.education_json, r.certifications, r.years_experience, r.resume_label
            FROM {CATALOG}.users_schema.users u
            LEFT JOIN {CATALOG}.users_schema.user_resumes r ON u.user_id = r.user_id AND r.is_primary = true
            WHERE u.user_id = '{user_id}'
        """)
        if not existing.empty:
            r = existing.iloc[0]
            parsed = {
                "full_name":            r.get("full_name", ""),
                "preferred_name":       r.get("preferred_name", ""),
                "current_title":        r.get("current_title", ""),
                "phone":                r.get("phone", ""),
                "email":                r.get("email_address", ""),
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

    with st.form("profile_form", clear_on_submit=False):
        st.markdown("**👤 Personal Information**")
        c1, c2 = st.columns(2)
        with c1:
            full_name      = st.text_input("Full Name *", value=parsed.get("full_name", ""))
            preferred_name = st.text_input("Preferred Name", value=parsed.get("preferred_name", ""))
            phone          = st.text_input("Phone", value=parsed.get("phone", ""),
                                            help="Optional — not required to save")
            city           = st.text_input("City", value=parsed.get("city", ""))
            state          = st.text_input("State", value=parsed.get("state", ""))
        with c2:
            current_title  = st.text_input("Current Job Title", value=parsed.get("current_title", ""))
            target_title   = st.text_input("Target Job Title *", value="Data Engineer")
            total_exp      = st.number_input(
                "Total Experience (years) *",
                min_value=0.0, max_value=50.0,
                value=float(parsed.get("total_experience_years", 0) or 0),
                step=0.5
            )
            linkedin_url   = st.text_input("LinkedIn URL", value=parsed.get("linkedin_url", ""))
            github_url     = st.text_input("GitHub URL", value=parsed.get("github_url", ""))

        st.markdown("---")
        st.markdown("**🛠️ Skills & Preferences**")
        c3, c4 = st.columns(2)
        with c3:
            skills = st.text_area(
                "Skills (comma-separated)",
                value=parsed.get("skills", ""),
                height=90,
                help="Edit if needed — auto-extracted from resume"
            )
            resume_label = st.text_input("Resume Label", value="Primary Resume",
                                          help="E.g. '8yr Resume', 'Sindhu — Senior DE'")
            certifications = st.text_input(
                "Certifications (comma-separated)",
                value=parsed.get("certifications", ""),
                placeholder="AWS Solutions Architect, Databricks Certified..."
            )
        with c4:
            min_match_score = st.slider("Minimum Match Score to Show (%)", 20, 90, 40)
            daily_limit     = st.number_input("Daily Resume Generation Limit", 5, 50, 10)

        st.markdown("---")
        st.markdown("**💼 Work History** (review AI-extracted data)")
        wh_default = json.dumps(parsed.get("work_history", []), indent=2)
        work_history_json = st.text_area(
            "Work History JSON",
            value=wh_default,
            height=220,
            help='JSON array — each entry: {"company":"..","title":"..","start":"..","end":"..","bullets":["..."]}'
        )

        st.markdown("**🎓 Education**")
        edu_default = json.dumps(parsed.get("education", []), indent=2)
        education_json = st.text_area(
            "Education JSON",
            value=edu_default,
            height=90,
            help='[{"degree":"M.S. in Data Science","school":"UNT","year":"2025","gpa":"3.66"}]'
        )

        st.markdown("---")
        save_btn = st.form_submit_button("💾 Save Profile", use_container_width=True, type="primary")

    if save_btn:
        if not full_name or not target_title:
            st.error("Full Name and Target Job Title are required!")
        else:
            # Parse JSONs safely
            try:
                wh_parsed = json.loads(work_history_json)
            except Exception:
                wh_parsed = parsed.get("work_history", [])
                st.warning("Work history JSON was invalid — using AI-extracted version")

            try:
                edu_parsed = json.loads(education_json)
            except Exception:
                edu_parsed = parsed.get("education", [])

            # Generate or reuse user_id
            if not user_id:
                user_id = str(uuid.uuid4())

            resume_id = str(uuid.uuid4())
            now = datetime.now()

            user_row = {
                "user_id":               user_id,
                "full_name":             full_name,
                "preferred_name":        preferred_name or full_name.split()[0],
                "current_title":         current_title,
                "target_title":          target_title,
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
            }

            resume_row = {
                "resume_id":          resume_id,
                "user_id":            user_id,
                "file_name":          st.session_state.get("resume_file_name", "resume.pdf"),
                "file_path":          f"/FileStore/resumes/uploads/{user_id}/",
                "file_type":          st.session_state.get("resume_file_type", "pdf"),
                "resume_label":       resume_label,
                "years_experience":   total_exp,
                "skills_extracted":   skills,
                "summary_text":       parsed.get("summary", ""),
                "work_history_json":  json.dumps(wh_parsed),
                "education_json":     json.dumps(edu_parsed),
                "certifications":     certifications,
                "uploaded_at":        now,
                "is_primary":         True,
            }

            with st.spinner("Saving to Databricks..."):
                # Try INSERT first; if user exists, UPDATE
                ok_user, err_user = insert_row(f"{CATALOG}.users_schema.users", user_row)
                if not ok_user:
                    # Pre-escape all strings (Python 3.11: no backslash inside f-string)
                    e_name  = esc(full_name)
                    e_pref  = esc(preferred_name or full_name.split()[0])
                    e_curr  = esc(current_title)
                    e_tgt   = esc(target_title)
                    e_phone = esc(phone)
                    e_city  = esc(city)
                    e_state = esc(state)
                    e_li    = esc(linkedin_url)
                    e_gh    = esc(github_url)
                    update_sql = (
                        f"UPDATE {CATALOG}.users_schema.users SET "
                        f"full_name = '{e_name}', "
                        f"preferred_name = '{e_pref}', "
                        f"current_title = '{e_curr}', "
                        f"target_title = '{e_tgt}', "
                        f"total_experience_years = {total_exp}, "
                        f"phone = '{e_phone}', "
                        f"city = '{e_city}', "
                        f"state = '{e_state}', "
                        f"linkedin_url = '{e_li}', "
                        f"github_url = '{e_gh}', "
                        f"min_match_score = {int(min_match_score)}, "
                        f"daily_resume_limit = {int(daily_limit)}, "
                        f"updated_at = current_timestamp() "
                        f"WHERE user_id = '{user_id}'"
                    )
                    ok_user, _, err_user = execute_sql(update_sql)

                ok_res, err_res = insert_row(f"{CATALOG}.users_schema.user_resumes", resume_row)

            if ok_user:
                st.session_state["current_user_id"] = user_id
                st.success(f"✅ Profile saved! **{full_name}** → User ID: `{user_id}`")
                st.balloons()

                # GitHub fetch
                if github_url:
                    with st.spinner("🐙 Fetching GitHub profile..."):
                        try:
                            uname = github_url.rstrip("/").split("/")[-1]
                            gr = requests.get(f"https://api.github.com/users/{uname}/repos?sort=stars&per_page=10", timeout=10).json()
                            langs = {}
                            if isinstance(gr, list):
                                for repo in gr:
                                    lang = repo.get("language") or ""
                                    if lang: langs[lang] = langs.get(lang, 0) + 1
                            top_langs = ", ".join(l for l, _ in sorted(langs.items(), key=lambda x:-x[1])[:8])
                            gh_row = {
                                "github_profile_id": str(uuid.uuid4()),
                                "user_id":           user_id,
                                "github_url":        github_url,
                                "github_username":   uname,
                                "top_languages":     top_langs,
                                "top_repos_json":    json.dumps(gr[:5] if isinstance(gr, list) else []),
                                "skills_inferred":   top_langs,
                                "contribution_summary": "",
                                "scraped_at":        datetime.now(),
                            }
                            insert_row(f"{CATALOG}.users_schema.user_github_profiles", gh_row)
                            st.success(f"🐙 GitHub saved: {top_langs}")
                        except Exception as ge:
                            st.warning(f"GitHub fetch skipped: {ge}")
            else:
                st.error(f"❌ Save failed: {err_user}")
                st.info("Check: Is DATABRICKS_SQL_WAREHOUSE_ID set in your .env? Is the warehouse running?")

# ════════════════════════════════════════════════════════
# TAB 3: Email Setup
# ════════════════════════════════════════════════════════
with tab3:
    st.markdown("<div class='section-title'>Email Accounts for Outreach</div>", unsafe_allow_html=True)
    st.info("📌 Email is **optional** — you can apply via links too. If added, emails will be sent with your resume attached.")

    user_id = st.session_state.get("current_user_id", "")
    if not user_id:
        st.warning("Save your profile first (Tab 2), then come back to add email.")
    else:
        with st.form("email_form"):
            c1, c2 = st.columns(2)
            with c1:
                email_addr   = st.text_input("Email Address", placeholder="yourname@gmail.com")
                display_name = st.text_input("Your Name (shows in email From:)", placeholder="Sindhu Singamaneni")
                email_label  = st.text_input("Label", value="Primary Gmail")
            with c2:
                smtp_opts = {
                    "Gmail (smtp.gmail.com)":          ("smtp.gmail.com", 587),
                    "Outlook (smtp.office365.com)":    ("smtp.office365.com", 587),
                    "Yahoo (smtp.mail.yahoo.com)":     ("smtp.mail.yahoo.com", 587),
                    "Custom":                           ("", 587),
                }
                smtp_choice = st.selectbox("Email Provider", list(smtp_opts.keys()))
                smtp_host_default, smtp_port_default = smtp_opts[smtp_choice]
                if smtp_choice == "Custom":
                    smtp_host = st.text_input("SMTP Host")
                else:
                    smtp_host = smtp_host_default
                    st.info(f"SMTP: `{smtp_host_default}:{smtp_port_default}`")
                smtp_port    = smtp_port_default
                app_password = st.text_input("App Password", type="password",
                                              help="Gmail: My Account → Security → 2-Step → App Passwords → Generate")
                is_primary = st.checkbox("Set as Primary", value=True)

            with st.expander("📌 How to get Gmail App Password"):
                st.markdown("""
                1. Go to **myaccount.google.com** → Security
                2. Enable **2-Step Verification** (required)
                3. Search for **App Passwords**
                4. Select **Mail** → **Generate**
                5. Copy the 16-character password (spaces don't matter)
                """)

            add_email = st.form_submit_button("➕ Add Email Account", type="primary")

        if add_email:
            if not email_addr:
                st.error("Email address is required.")
            else:
                enc_pw = app_password  # Store as-is; in prod: use Fernet with Databricks Secret
                try:
                    from cryptography.fernet import Fernet
                    key = os.getenv("EMAIL_ENCRYPTION_KEY", "")
                    if key:
                        enc_pw = Fernet(key.encode()).encrypt(app_password.encode()).decode()
                except Exception:
                    import base64
                    enc_pw = base64.b64encode(app_password.encode()).decode()

                email_row = {
                    "email_id":               str(uuid.uuid4()),
                    "user_id":                user_id,
                    "email_address":          email_addr,
                    "display_name":           display_name,
                    "smtp_host":              smtp_host,
                    "smtp_port":              int(smtp_port),
                    "app_password_encrypted": enc_pw,
                    "email_label":            email_label,
                    "is_primary":             is_primary,
                    "is_active":              True,
                    "added_at":              datetime.now(),
                }
                ok, err = insert_row(f"{CATALOG}.users_schema.user_emails", email_row)
                if ok:
                    st.success(f"✅ Email `{email_addr}` added!")
                else:
                    st.error(f"Failed: {err}")

        # Show existing emails
        emails_df = query_df(f"SELECT email_address, display_name, email_label, smtp_host, is_primary FROM {CATALOG}.users_schema.user_emails WHERE user_id = '{user_id}' AND is_active = true")
        if not emails_df.empty:
            st.markdown("<div class='section-title'>Your Email Accounts</div>", unsafe_allow_html=True)
            st.dataframe(emails_df, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════
# TAB 4: Clipboards (Multi-Resume / Multi-LinkedIn)
# ════════════════════════════════════════════════════════
with tab4:
    st.markdown("<div class='section-title'>Application Clipboards</div>", unsafe_allow_html=True)
    st.markdown("""
    <div class='syntra-card'>
        <p style='color:#94a3b8; font-size:13px; margin:0;'>
        Clipboards let you apply with <strong>different personas</strong> for the same candidate.
        Create one clipboard per experience level or resume style you want to present.
        <br><br>
        Example: <strong>"Sindhu — 8yr Senior"</strong> claims 8 years, uses senior LinkedIn profile.
        <strong>"Sindhu — 5yr Mid"</strong> claims 5 years, uses a different email.
        </p>
    </div>
    """, unsafe_allow_html=True)

    user_id = st.session_state.get("current_user_id", "")
    if not user_id:
        st.warning("Save profile first.")
    else:
        # Load user's resumes and emails for dropdowns
        resumes_df = query_df(f"SELECT resume_id, resume_label FROM {CATALOG}.users_schema.user_resumes WHERE user_id = '{user_id}'")
        emails_df  = query_df(f"SELECT email_id, email_address, email_label FROM {CATALOG}.users_schema.user_emails WHERE user_id = '{user_id}' AND is_active = true")

        with st.form("clipboard_form"):
            st.markdown("**Create New Clipboard**")
            c1, c2 = st.columns(2)
            with c1:
                clip_name    = st.text_input("Clipboard Name *", placeholder="Sindhu — Senior 8yr")
                exp_override = st.number_input("Experience Years (override)", 0.0, 30.0, 0.0, 0.5,
                                                help="Leave 0 to use resume's actual experience")
                location_ov  = st.text_input("Location Override", placeholder="Irving, TX")
                phone_ov     = st.text_input("Phone Override", placeholder="Leave blank = use profile phone")

                # Resume selector
                resume_opts = {"-- Use Primary Resume --": None}
                if not resumes_df.empty:
                    for _, r in resumes_df.iterrows():
                        resume_opts[f"{r['resume_label']} ({r['resume_id'][:8]}...)"] = r["resume_id"]
                sel_resume = st.selectbox("Resume to Use", list(resume_opts.keys()))

            with c2:
                # Email selector
                email_opts = {"-- Use Primary Email --": None}
                if not emails_df.empty:
                    for _, r in emails_df.iterrows():
                        email_opts[f"{r['email_label']} ({r['email_address']})"] = r["email_id"]
                sel_email = st.selectbox("Email to Send From", list(email_opts.keys()))

                basic_skills = st.text_area(
                    "Add as 'Familiar With' Skills",
                    placeholder="Docker, Kubernetes, Terraform\n(Skills you know basics of — added as 'Familiar with X')",
                    height=80,
                )
                extra_bullets = st.text_area(
                    "Extra Bullet Points to Inject",
                    placeholder="One per line:\nContributed to open source data pipeline projects",
                    height=80,
                )
                is_default = st.checkbox("Set as Default Clipboard", value=False)

            add_clip = st.form_submit_button("➕ Create Clipboard", type="primary", use_container_width=True)

        if add_clip and clip_name:
            bullets_json = json.dumps([
                {"context": "general", "bullet": b.strip()}
                for b in (extra_bullets or "").split("\n") if b.strip()
            ])
            clip_row = {
                "clipboard_id":             str(uuid.uuid4()),
                "user_id":                  user_id,
                "clipboard_name":           clip_name,
                "years_experience_override":float(exp_override) if exp_override > 0 else None,
                "resume_id_to_use":         resume_opts.get(sel_resume),
                "linkedin_id_to_use":       None,
                "email_id_to_use":          email_opts.get(sel_email),
                "extra_bullets_json":       bullets_json,
                "basic_knowledge_skills":   basic_skills,
                "phone_override":           phone_ov or None,
                "location_override":        location_ov or None,
                "is_default":               is_default,
                "created_at":              datetime.now(),
                "updated_at":              datetime.now(),
            }
            ok, err = insert_row(f"{CATALOG}.users_schema.user_application_clipboard", clip_row)
            if ok:
                st.success(f"✅ Clipboard **'{clip_name}'** created!")
            else:
                st.error(f"Failed: {err}")

        # Show existing clipboards
        clips_df = query_df(f"""
            SELECT clipboard_name, years_experience_override, location_override,
                   basic_knowledge_skills, is_default, created_at
            FROM {CATALOG}.users_schema.user_application_clipboard
            WHERE user_id = '{user_id}'
            ORDER BY created_at DESC
        """)
        if not clips_df.empty:
            st.markdown("<div class='section-title'>Your Clipboards</div>", unsafe_allow_html=True)
            for _, clip in clips_df.iterrows():
                default_badge = "<span class='badge badge-green'>DEFAULT</span>" if clip.get("is_default") else ""
                st.markdown(f"""
                <div class='syntra-card' style='padding:14px 18px;'>
                    <div style='display:flex; justify-content:space-between;'>
                        <strong>{clip['clipboard_name']}</strong> {default_badge}
                        <span class='badge badge-blue'>{clip.get('years_experience_override') or 'Original'} yrs</span>
                    </div>
                    <div style='color:#64748b; font-size:12px; margin-top:6px;'>
                        📍 {clip.get('location_override') or 'No override'} &nbsp;|&nbsp;
                        🛠 Familiar with: {(clip.get('basic_knowledge_skills') or 'None')[:60]}
                    </div>
                </div>
                """, unsafe_allow_html=True)
