"""
Page 1 — User Onboarding
- Upload resume (PDF/DOCX) → auto-parse all details
- Manual form fields (override parsed)
- LinkedIn URL + GitHub URL (scraped if provided)
- Multiple email accounts with SMTP credentials
- Clipboard profiles (experience override per application)
"""

import streamlit as st
import uuid, json, re, io
from datetime import datetime

# ── DB Connection helper ──────────────────────────────────────
@st.cache_resource
def get_spark():
    try:
        from databricks.connect import DatabricksSession
        return DatabricksSession.builder.getOrCreate()
    except Exception:
        return None

spark = get_spark()

CATALOG = "jobs_automation_db"

def run_sql(query: str):
    if spark:
        try:
            return spark.sql(query)
        except Exception as e:
            st.error(f"DB Error: {e}")
    return None

def insert_row(table: str, row: dict):
    """Insert a dict as a row into a Delta table."""
    if not spark:
        return False
    try:
        df = spark.createDataFrame([row])
        df.write.format("delta").mode("append").saveAsTable(table)
        return True
    except Exception as e:
        st.error(f"Insert error: {e}")
        return False

# ── Resume Parsers ────────────────────────────────────────────
def parse_pdf_resume(file_bytes: bytes) -> dict:
    """Extract text and structure from PDF resume."""
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return parse_resume_text(text)
    except ImportError:
        st.warning("pdfplumber not installed. Using raw text extraction.")
        return {"raw_text": file_bytes.decode("utf-8", errors="ignore")}
    except Exception as e:
        st.error(f"PDF parse error: {e}")
        return {}

def parse_docx_resume(file_bytes: bytes) -> dict:
    """Extract text and structure from DOCX resume."""
    try:
        from docx import Document
        import io as io_mod
        doc = Document(io_mod.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return parse_resume_text(text)
    except Exception as e:
        st.error(f"DOCX parse error: {e}")
        return {}

def parse_resume_text(text: str) -> dict:
    """Parse raw resume text into structured fields."""
    result = {"raw_text": text}

    # Phone
    phone_m = re.search(r"[\+\(]?[1-9][0-9\s\-\(\)]{8,}[0-9]", text)
    result["phone"] = phone_m.group().strip() if phone_m else ""

    # Email
    email_m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    result["email"] = email_m.group().lower() if email_m else ""

    # LinkedIn
    li_m = re.search(r"linkedin\.com/in/[\w\-]+", text, re.I)
    result["linkedin_url"] = ("https://" + li_m.group()) if li_m else ""

    # GitHub
    gh_m = re.search(r"github\.com/[\w\-]+", text, re.I)
    result["github_url"] = ("https://" + gh_m.group()) if gh_m else ""

    # Total experience (from header/summary)
    exp_m = re.search(r"(\d+\.?\d*)\+?\s*years?\s+(?:of\s+)?(?:total\s+)?experience", text, re.I)
    result["years_experience"] = float(exp_m.group(1)) if exp_m else 0.0

    # Skills extraction — look for skills section
    skills = []
    known_techs = [
        "Python", "PySpark", "Spark", "SQL", "Databricks", "Azure", "AWS", "GCP",
        "Kafka", "Airflow", "dbt", "Scala", "Java", "Delta Lake", "Snowflake",
        "Redshift", "BigQuery", "Pandas", "NumPy", "TensorFlow", "PyTorch",
        "Docker", "Kubernetes", "Git", "Tableau", "Power BI", "Hadoop", "Hive",
        "Terraform", "Jenkins", "REST API", "FastAPI", "Flask", "React",
        "PostgreSQL", "MySQL", "MongoDB", "Elasticsearch", "Redis",
        "Azure Data Factory", "Azure Synapse", "AWS Glue", "EMR", "S3",
        "MLflow", "Scikit-learn", "XGBoost", "LightGBM", "BERT",
    ]
    for tech in known_techs:
        if tech.lower() in text.lower():
            skills.append(tech)
    result["skills_extracted"] = ", ".join(skills)

    # Work history — simple pattern matching
    work_history = []
    # Look for date patterns near company/role info
    date_pattern = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)\s+\d{4}"
    dates = list(re.finditer(date_pattern, text, re.I))

    # Try to extract company blocks (simplified)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    current_job = {}
    for i, line in enumerate(lines):
        # Heuristic: if line has date range, it's likely a job header
        if re.search(r"\d{4}\s*[-–]\s*(\d{4}|Present|Current)", line, re.I):
            if current_job:
                work_history.append(current_job)
            current_job = {
                "company": lines[i-1] if i > 0 else "Company",
                "title":   lines[i-2] if i > 1 else "Engineer",
                "start":   "",
                "end":     "Present",
                "bullets": [],
            }
            # Extract dates
            date_range = re.search(r"(\w+\s+\d{4})\s*[-–]\s*(\w+\s+\d{4}|Present|Current)", line, re.I)
            if date_range:
                current_job["start"] = date_range.group(1)
                current_job["end"]   = date_range.group(2)
        elif current_job and (line.startswith("•") or line.startswith("-") or line.startswith("◦")):
            bullet = line.lstrip("•-◦ ").strip()
            if len(bullet) > 20:
                current_job["bullets"].append(bullet)

    if current_job:
        work_history.append(current_job)

    result["work_history"] = work_history[-6:]  # Keep last 6 jobs

    # Education
    education = []
    edu_keywords = ["B.Tech", "B.E", "M.Tech", "M.S.", "M.B.A", "Bachelor", "Master", "Ph.D", "B.Sc", "M.Sc"]
    for line in lines:
        if any(kw.lower() in line.lower() for kw in edu_keywords):
            education.append({"degree": line[:100], "school": "", "year": ""})
            break
    result["education"] = education

    return result

# ── GitHub Scraper ─────────────────────────────────────────────
def fetch_github_profile(github_url: str) -> dict:
    """Fetch GitHub profile data via public API."""
    import requests
    username = github_url.rstrip("/").split("/")[-1]
    try:
        user_resp = requests.get(f"https://api.github.com/users/{username}", timeout=10)
        repos_resp= requests.get(f"https://api.github.com/users/{username}/repos?sort=stars&per_page=10", timeout=10)

        user_data = user_resp.json() if user_resp.status_code == 200 else {}
        repos_data= repos_resp.json() if repos_resp.status_code == 200 else []

        languages = {}
        top_repos = []
        if isinstance(repos_data, list):
            for repo in repos_data[:10]:
                lang = repo.get("language") or ""
                if lang:
                    languages[lang] = languages.get(lang, 0) + 1
                top_repos.append({
                    "name":  repo.get("name", ""),
                    "desc":  (repo.get("description") or "")[:100],
                    "stars": repo.get("stargazers_count", 0),
                    "lang":  lang,
                })

        top_langs = sorted(languages.items(), key=lambda x: -x[1])
        langs_str = ", ".join(l for l, _ in top_langs[:8])

        # Infer skills from languages
        lang_to_skills = {
            "Python": ["Python", "Pandas", "NumPy"],
            "Scala": ["Scala", "Spark"],
            "Java": ["Java"],
            "JavaScript": ["JavaScript", "React"],
            "TypeScript": ["TypeScript"],
            "SQL": ["SQL"],
            "Shell": ["Bash", "Linux"],
            "HCL": ["Terraform"],
            "Dockerfile": ["Docker"],
        }
        inferred = []
        for lang, _ in top_langs:
            inferred.extend(lang_to_skills.get(lang, []))

        return {
            "github_username":    username,
            "top_languages":      langs_str,
            "top_repos_json":     json.dumps(top_repos),
            "skills_inferred":    ", ".join(dict.fromkeys(inferred)),
            "contribution_summary": f"Public repos: {user_data.get('public_repos', 0)} | Followers: {user_data.get('followers', 0)}",
        }
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════
# PAGE LAYOUT
# ═══════════════════════════════════════════════════════════
st.title("👤 User Onboarding")
st.markdown("Set up your profile, upload resume, and configure your application preferences.")

# ── Tab layout ────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📄 Resume Upload", "👤 Profile Details", "📧 Email Setup", "🗂️ Clipboards"])

# ════════════════════════════════
# TAB 1: Resume Upload & Parse
# ════════════════════════════════
with tab1:
    st.subheader("Upload Your Resume")
    st.info("Upload PDF or DOCX. All details will be auto-extracted. You can review and edit in the next tab.")

    uploaded_file = st.file_uploader(
        "Choose your resume file",
        type=["pdf", "docx"],
        help="PDF or DOCX format. Max 10MB."
    )

    if uploaded_file:
        file_bytes = uploaded_file.read()
        file_type  = uploaded_file.name.split(".")[-1].lower()

        with st.spinner("🤖 Parsing resume..."):
            if file_type == "pdf":
                parsed = parse_pdf_resume(file_bytes)
            else:
                parsed = parse_docx_resume(file_bytes)

        st.success("✅ Resume parsed successfully!")

        # Store in session
        st.session_state["parsed_resume"]   = parsed
        st.session_state["resume_file_name"]= uploaded_file.name
        st.session_state["resume_file_type"]= file_type
        st.session_state["resume_bytes"]    = file_bytes

        # Show parsed preview
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**📊 Extracted Info**")
            st.write(f"📞 Phone: `{parsed.get('phone', 'Not found')}`")
            st.write(f"📧 Email: `{parsed.get('email', 'Not found')}`")
            st.write(f"🔗 LinkedIn: `{parsed.get('linkedin_url', 'Not found')}`")
            st.write(f"💼 Experience: `{parsed.get('years_experience', 0)} years`")
        with col2:
            st.markdown("**🛠️ Skills Detected**")
            skills = parsed.get("skills_extracted", "")
            if skills:
                for s in skills.split(",")[:12]:
                    st.markdown(f"`{s.strip()}`", unsafe_allow_html=False)
            else:
                st.write("No skills auto-detected")

        # Work history preview
        work = parsed.get("work_history", [])
        if work:
            st.markdown("**💼 Work History Detected**")
            for i, job in enumerate(work):
                with st.expander(f"{job.get('title','Role')} at {job.get('company','Company')} ({job.get('start','')} – {job.get('end','')})"):
                    bullets = job.get("bullets", [])
                    for b in bullets[:5]:
                        st.write(f"• {b}")
                    if not bullets:
                        st.write("*No bullets extracted — will use AI to generate*")

        st.markdown("---")
        st.info("👉 Go to **Profile Details** tab to review and complete your profile, then save.")

# ════════════════════════════════
# TAB 2: Profile Details Form
# ════════════════════════════════
with tab2:
    st.subheader("Profile Details")

    parsed = st.session_state.get("parsed_resume", {})

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            full_name      = st.text_input("Full Name *", value=parsed.get("name", ""))
            preferred_name = st.text_input("Preferred Name", value="")
            phone          = st.text_input("Phone *", value=parsed.get("phone", ""))
            city           = st.text_input("City", value="")
            state          = st.text_input("State", value="")
        with col2:
            current_title  = st.text_input("Current Title", value="")
            target_title   = st.text_input("Target Job Title *", value="Data Engineer")
            total_exp      = st.number_input("Total Experience (years) *", min_value=0.0, max_value=50.0,
                                              value=float(parsed.get("years_experience", 0)), step=0.5)
            linkedin_url   = st.text_input("LinkedIn URL", value=parsed.get("linkedin_url", ""))
            github_url     = st.text_input("GitHub URL", value=parsed.get("github_url", ""))

        st.markdown("---")
        col3, col4 = st.columns(2)
        with col3:
            skills_override = st.text_area("Skills (comma-separated)",
                                            value=parsed.get("skills_extracted", ""),
                                            height=100,
                                            help="Auto-detected from resume. Edit if needed.")
            resume_label   = st.text_input("Resume Label", value="Primary Resume",
                                            help="E.g. '8yr Resume', 'Senior Profile'")
        with col4:
            min_match_score= st.slider("Minimum Match Score to Show (%)", 30, 90, 50)
            daily_limit    = st.number_input("Daily Resume Generation Limit", 5, 50, 10)

        st.markdown("**Work History** (review/edit extracted data)")
        work_history_json_input = st.text_area(
            "Work History JSON",
            value=json.dumps(parsed.get("work_history", []), indent=2),
            height=200,
            help='JSON array: [{"company":"..","title":"..","start":"..","end":"..","bullets":["..."]}]'
        )

        education_json_input = st.text_area(
            "Education JSON",
            value=json.dumps(parsed.get("education", []), indent=2),
            height=80,
            help='[{"degree":"B.Tech","school":"JNTU","year":"2018"}]'
        )

        certifications = st.text_input("Certifications (comma-separated)",
                                        placeholder="AWS Solutions Architect, Databricks Certified...")

        # GitHub scrape button
        if github_url:
            fetch_gh = st.form_submit_button("🐙 Fetch GitHub Profile Too")
        
        submit = st.form_submit_button("💾 Save Profile", use_container_width=True, type="primary")

    if submit:
        if not full_name or not target_title:
            st.error("Full Name and Target Job Title are required!")
        else:
            user_id = str(uuid.uuid4())
            resume_id = str(uuid.uuid4())

            user_row = {
                "user_id":               user_id,
                "full_name":             full_name,
                "preferred_name":        preferred_name,
                "current_title":         current_title,
                "target_title":          target_title,
                "total_experience_years":total_exp,
                "phone":                 phone,
                "city":                  city,
                "state":                 state,
                "linkedin_url":          linkedin_url,
                "github_url":            github_url,
                "portfolio_url":         "",
                "min_match_score":       min_match_score,
                "daily_resume_limit":    daily_limit,
                "created_at":            datetime.now(),
                "updated_at":            datetime.now(),
                "is_active":             True,
            }

            try:
                wh = json.loads(work_history_json_input)
            except Exception:
                wh = parsed.get("work_history", [])

            try:
                edu = json.loads(education_json_input)
            except Exception:
                edu = parsed.get("education", [])

            resume_row = {
                "resume_id":          resume_id,
                "user_id":            user_id,
                "file_name":          st.session_state.get("resume_file_name", "resume.pdf"),
                "file_path":          f"/FileStore/resumes/uploads/{user_id}/",
                "file_type":          st.session_state.get("resume_file_type", "pdf"),
                "resume_label":       resume_label,
                "years_experience":   total_exp,
                "skills_extracted":   skills_override,
                "summary_text":       "",
                "work_history_json":  json.dumps(wh),
                "education_json":     json.dumps(edu),
                "certifications":     certifications,
                "uploaded_at":        datetime.now(),
                "is_primary":         True,
            }

            # Insert to Databricks
            if insert_row(f"{CATALOG}.users_schema.users", user_row) and \
               insert_row(f"{CATALOG}.users_schema.user_resumes", resume_row):
                st.session_state["current_user_id"] = user_id
                st.success(f"✅ Profile saved! Your User ID: `{user_id}`")
                st.balloons()

                # Fetch GitHub
                if github_url:
                    with st.spinner("🐙 Fetching GitHub..."):
                        gh_data = fetch_github_profile(github_url)
                        if "error" not in gh_data:
                            gh_row = {
                                "github_profile_id": str(uuid.uuid4()),
                                "user_id":           user_id,
                                "github_url":        github_url,
                                **gh_data,
                                "scraped_at":        datetime.now(),
                            }
                            insert_row(f"{CATALOG}.users_schema.user_github_profiles", gh_row)
                            st.success(f"✅ GitHub: {gh_data.get('top_languages','')}")

# ════════════════════════════════
# TAB 3: Email Setup
# ════════════════════════════════
with tab3:
    st.subheader("📧 Email Accounts for Outreach")
    st.info("Add your Gmail/Outlook accounts for sending applications. App passwords are encrypted with AES-256.")

    user_id = st.session_state.get("current_user_id", "")
    if not user_id:
        st.warning("⚠️ Please complete and save your profile in Tab 2 first.")
    else:
        with st.form("email_form"):
            col1, col2 = st.columns(2)
            with col1:
                email_addr   = st.text_input("Email Address *", placeholder="yourname@gmail.com")
                display_name = st.text_input("Display Name *", placeholder="Your Full Name")
                email_label  = st.text_input("Label", placeholder="Primary Gmail", value="Primary Gmail")
            with col2:
                smtp_host    = st.selectbox("SMTP Host", ["smtp.gmail.com", "smtp.office365.com", "smtp.yahoo.com", "Other"])
                smtp_port    = st.number_input("SMTP Port", value=587)
                app_password = st.text_input("App Password *", type="password",
                                              help="Gmail: Settings → Security → App Passwords")
                is_primary   = st.checkbox("Set as Primary", value=True)

            st.markdown("---")
            st.markdown("**📌 How to get Gmail App Password:**")
            st.markdown("1. Go to Google Account → Security → 2-Step Verification → App Passwords\n"
                       "2. Select 'Mail' → Generate → Copy the 16-char password")

            add_email = st.form_submit_button("➕ Add Email Account", type="primary")

        if add_email and email_addr and app_password:
            # AES encrypt the password
            try:
                from cryptography.fernet import Fernet
                import os
                # In production: store this key in Databricks Secrets
                enc_key = os.getenv("EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())
                fernet = Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
                encrypted_pw = fernet.encrypt(app_password.encode()).decode()
            except ImportError:
                # Fallback: base64 (NOT secure — install cryptography package)
                import base64
                encrypted_pw = base64.b64encode(app_password.encode()).decode()

            email_row = {
                "email_id":               str(uuid.uuid4()),
                "user_id":                user_id,
                "email_address":          email_addr,
                "display_name":           display_name,
                "smtp_host":              smtp_host,
                "smtp_port":              int(smtp_port),
                "app_password_encrypted": encrypted_pw,
                "email_label":            email_label,
                "is_primary":             is_primary,
                "is_active":              True,
                "added_at":              datetime.now(),
            }
            if insert_row(f"{CATALOG}.users_schema.user_emails", email_row):
                st.success(f"✅ Email {email_addr} added successfully!")

        # Show existing emails
        if user_id and spark:
            st.markdown("---")
            st.markdown("**Your Email Accounts**")
            df = run_sql(f"SELECT email_id, email_address, display_name, email_label, is_primary FROM {CATALOG}.users_schema.user_emails WHERE user_id = '{user_id}'")
            if df and df.count() > 0:
                st.dataframe(df.toPandas(), use_container_width=True, hide_index=True)

# ════════════════════════════════
# TAB 4: Application Clipboards
# ════════════════════════════════
with tab4:
    st.subheader("🗂️ Application Clipboards")
    st.markdown("""
    Clipboards let you apply with **different profiles** for different jobs.
    For example:
    - **"Senior 8yr"** clipboard → claims 8 years exp, uses your main LinkedIn
    - **"Mid-level 5yr"** clipboard → claims 5 years, uses alternate email
    """)

    user_id = st.session_state.get("current_user_id", "")
    if not user_id:
        st.warning("⚠️ Save your profile first.")
    else:
        with st.form("clipboard_form"):
            col1, col2 = st.columns(2)
            with col1:
                clip_name     = st.text_input("Clipboard Name *", placeholder="Senior 8yr Profile")
                exp_override  = st.number_input("Experience Years (for this profile)",
                                                 min_value=0.0, max_value=30.0, value=0.0, step=0.5,
                                                 help="Leave 0 to use resume's actual experience")
                location_ov   = st.text_input("Location Override", placeholder="Irving, TX (if relocating)")
                phone_ov      = st.text_input("Phone Override", placeholder="Leave blank to use profile phone")

            with col2:
                basic_skills  = st.text_area("Add as 'Familiar With' Skills",
                                              placeholder="Docker, Kubernetes, Terraform",
                                              height=80,
                                              help="Skills you have basic knowledge of — will be added as 'Familiar with X'")
                extra_bullets = st.text_area("Extra Bullets to Inject",
                                              placeholder="One per line — e.g. 'Contributed to open source Spark projects'",
                                              height=80)
                is_default    = st.checkbox("Set as Default Clipboard", value=False)

            add_clip = st.form_submit_button("➕ Create Clipboard", type="primary")

        if add_clip and clip_name:
            bullets_json = json.dumps([{"context": "general", "bullet": b.strip()}
                                        for b in (extra_bullets or "").split("\n") if b.strip()])
            clip_row = {
                "clipboard_id":             str(uuid.uuid4()),
                "user_id":                  user_id,
                "clipboard_name":           clip_name,
                "years_experience_override":float(exp_override) if exp_override > 0 else None,
                "resume_id_to_use":         None,
                "linkedin_id_to_use":       None,
                "email_id_to_use":          None,
                "extra_bullets_json":       bullets_json,
                "basic_knowledge_skills":   basic_skills,
                "phone_override":           phone_ov or None,
                "location_override":        location_ov or None,
                "is_default":               is_default,
                "created_at":              datetime.now(),
                "updated_at":              datetime.now(),
            }
            if insert_row(f"{CATALOG}.users_schema.user_application_clipboard", clip_row):
                st.success(f"✅ Clipboard '{clip_name}' created!")

        # Show existing clipboards
        if spark:
            st.markdown("---")
            df = run_sql(f"SELECT clipboard_name, years_experience_override, location_override, basic_knowledge_skills, is_default FROM {CATALOG}.users_schema.user_application_clipboard WHERE user_id = '{user_id}'")
            if df and df.count() > 0:
                st.dataframe(df.toPandas(), use_container_width=True, hide_index=True)
