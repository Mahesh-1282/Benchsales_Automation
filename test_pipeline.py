"""
test_pipeline.py — End-to-End Pipeline Validator
Tests: resume parsing → data storage → resume generation → DOCX output
Run locally: python test_pipeline.py
"""

import os, sys, json, uuid, re, io
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / "03_databricks_app"))

print("=" * 60)
print("SYNTRA — Pipeline Validation Test")
print("=" * 60)

# ── 1. Test Resume Parser ─────────────────────────────────────
print("\n🧪 TEST 1: Resume Parser")

# Sindhu's resume text (subset)
SINDHU_RESUME = """
SINDHU SINGAMANENI
Data Engineer | Advanced SQL, dbt & Snowflake | ETL/ELT & Data Conversion | IBM DataStage
gspriya0321@gmail.com | www.linkedin.com/in/sindhu-s-b74b43367 | Dallas, TX | Open to Relocation — Cincinnati, OH | W2

PROFESSIONAL SUMMARY
Data Engineer with 5+ years of experience building and maintaining ETL/ELT pipelines, data transformations, and data migration solutions across Azure, AWS, and GCP. Hands-on expertise in Advanced SQL, T-SQL, dbt, Snowflake, and IBM DataStage.

RELEVANT SKILLS
SQL & Data Warehousing: Advanced SQL · T-SQL · ANSI SQL · dbt (data build tool) · Snowflake · Azure Synapse Analytics · Google BigQuery · Amazon Redshift
ETL/ELT & Data Integration: IBM DataStage · Azure Data Factory (ADF) · AWS Glue · Informatica PowerCenter · Apache Airflow
Programming: Python · PySpark · Scala · PL/SQL
Databases: PostgreSQL · MySQL · Oracle · SQL Server · MongoDB

PROFESSIONAL EXPERIENCE
Data Engineer · Interstate Batteries Oct 2023 – Jul 2026
Enterprise data platform engineering and financial data migration on Azure, Microsoft Fabric, and AWS.
• Supported data migration and data conversion initiatives involving sales invoices, billing records, customer transactions, and revenue-related financial datasets — ensuring accurate, validated, and consistent movement of data.
• Developed and maintained ETL/ELT pipelines to extract, transform, validate, and load transactional and financial data — building dbt models and Snowflake transformations.
• Authored complex Advanced SQL and T-SQL transformations, CTEs, and window functions — improving query performance by 45%.
• Built automated data quality validation and anomaly detection frameworks — reducing downstream data errors by 30%.

ETL Developer · Wipro Jun 2021 – Jul 2023
Enterprise data warehousing, IBM DataStage ETL development.
• Developed and supported ETL workflows using IBM DataStage — creating parallel jobs, transformations, lookups, joins, and data cleansing workflows.
• Translated source-to-target mappings and business rules into scalable IBM DataStage ETL processes.
• Performed data validation, error handling, and reconciliation across source and target systems.

EDUCATION
M.S. in Data Science · University of North Texas, Denton, TX · 2025 · GPA: 3.66 / 4.0
B.E. in Engineering · Gudlavalleru Engineering College · 2022 · GPA: 8.67 / 10
"""

# Test regex parser
from pages._1_Onboarding import regex_parse_resume

try:
    parsed = regex_parse_resume(SINDHU_RESUME)
    print(f"  ✅ Name:          {parsed.get('full_name', '⚠️ MISSING')}")
    print(f"  ✅ Email:         {parsed.get('email', '⚠️ MISSING')}")
    print(f"  ✅ Phone:         {parsed.get('phone', '⚠️ Not found')}")
    print(f"  ✅ LinkedIn:      {parsed.get('linkedin_url', '⚠️ MISSING')}")
    print(f"  ✅ City:          {parsed.get('city', '⚠️ MISSING')}")
    print(f"  ✅ Experience:    {parsed.get('total_experience_years', 0)} years")
    print(f"  ✅ Skills count:  {len(parsed.get('skills', '').split(','))}")
    print(f"  ✅ Work history:  {len(parsed.get('work_history', []))} positions")
    print(f"  ✅ Education:     {len(parsed.get('education', []))} records")

    wh = parsed.get("work_history", [])
    for i, job in enumerate(wh):
        print(f"     Job {i+1}: {job.get('title')} @ {job.get('company')} | {job.get('start')} – {job.get('end')}")
        print(f"            Bullets: {len(job.get('bullets', []))}")
except Exception as e:
    print(f"  ❌ Parser test failed: {e}")
    import traceback; traceback.print_exc()

print()

# ── 2. Mock User Data ─────────────────────────────────────────
print("🧪 TEST 2: Mock User Data Build")

user_id   = str(uuid.uuid4())
resume_id = str(uuid.uuid4())

user_data = {
    "user_id":               user_id,
    "full_name":             parsed.get("full_name", "Sindhu Singamaneni"),
    "preferred_name":        parsed.get("preferred_name", "Sindhu"),
    "current_title":         parsed.get("current_title", "Data Engineer"),
    "target_title":          "Data Engineer",
    "total_experience_years":parsed.get("total_experience_years", 5.0),
    "phone":                 parsed.get("phone", "+1 (945) 527-2599"),
    "city":                  parsed.get("city", "Dallas"),
    "state":                 parsed.get("state", "TX"),
    "linkedin_url":          parsed.get("linkedin_url", ""),
    "skills_extracted":      parsed.get("skills", ""),
    "work_history_json":     json.dumps(parsed.get("work_history", [])),
    "education_json":        json.dumps(parsed.get("education", [])),
}
print(f"  ✅ User data built for {user_data['full_name']}")

# ── 3. Mock Job Data ──────────────────────────────────────────
print("\n🧪 TEST 3: Mock Job Data")

job_data = {
    "job_hash":       "test_job_001",
    "job_title":      "Senior Data Engineer",
    "company_name":   "Acme Analytics Corp",
    "location":       "Irving, TX",
    "remote_type":    "Hybrid",
    "tech_stack":     "Python, dbt, Snowflake, Airflow, AWS Glue, PySpark, SQL",
    "job_description":"We are looking for a Senior Data Engineer with expertise in dbt, Snowflake, and AWS Glue. Must have 5+ years experience building ETL pipelines.",
    "requirements_section": "5+ years Python, dbt, Snowflake, Airflow, AWS Glue, PySpark",
    "experience_min": 5,
    "experience_max": 8,
    "apply_link":     "https://example.com/apply",
    "hr_email":       "talent@acme.com",
}
print(f"  ✅ Job: {job_data['job_title']} @ {job_data['company_name']}")

# ── 4. Test AI Resume Generation ─────────────────────────────
print("\n🧪 TEST 4: Resume Generation (DOCX)")

NVIDIA_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
if not NVIDIA_API_KEY:
    print("  ⚠️  NVIDIA_NIM_API_KEY not set — testing DOCX builder only (no AI bullets)")

import requests

def generate_ai_bullets(user: dict, job: dict) -> list:
    """Generate 5 AI-tailored bullets per role."""
    if not NVIDIA_API_KEY:
        return [
            f"Designed and implemented {job['tech_stack'].split(',')[0].strip()} pipelines for enterprise-scale data processing",
            "Reduced pipeline execution time by 40% through query optimization and parallel processing",
            "Collaborated with cross-functional teams to deliver data solutions aligned with business objectives",
        ]

    work_history = json.loads(user.get("work_history_json", "[]"))
    all_bullets  = []

    for idx, role in enumerate(work_history[:4]):
        prompt = f"""Generate 5 ATS-friendly resume bullets for this role, tailored to the job.

Role: {role.get('title')} at {role.get('company')} ({role.get('start')} – {role.get('end')})
Original bullets: {'; '.join(role.get('bullets', [])[:3])}
Target Job: {job['job_title']} at {job['company_name']}
Required Skills: {job['tech_stack']}

Rules:
- Keep company name exactly as-is
- Replace bullet content with STAR format (Situation/Task/Action/Result)
- Include quantified results where possible
- Use keywords from job requirements naturally
- Start each with strong action verb
- Return ONLY a JSON array of 5 strings: ["bullet1", "bullet2", "bullet3", "bullet4", "bullet5"]"""

        try:
            import time
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
                json={"model": "meta/llama-3.1-8b-instruct",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.3, "max_tokens": 800},
                timeout=30,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                m = re.search(r'\[.*\]', content, re.DOTALL)
                if m:
                    bullets = json.loads(m.group())
                    all_bullets.append({"role_index": idx, "company": role.get("company"), "title": role.get("title"), "bullets": bullets})
            time.sleep(1)
        except Exception as e:
            print(f"  ⚠️  AI bullet gen failed for role {idx}: {e}")
            all_bullets.append({
                "role_index": idx,
                "company":    role.get("company", ""),
                "title":      role.get("title", ""),
                "bullets":    role.get("bullets", [])[:5],
            })

    return all_bullets

def build_docx(user: dict, job: dict, bullets_data: list) -> bytes:
    """Build DOCX resume file."""
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin    = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin   = Inches(0.7)
        section.right_margin  = Inches(0.7)

    # Header
    name_para = doc.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = name_para.add_run(user.get("full_name", "Candidate Name"))
    run.bold     = True
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

    contact_para = doc.add_paragraph()
    contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact_text = f"{user.get('phone','')} | {user.get('email_address', user.get('email', ''))} | {user.get('city','')}, {user.get('state','')}"
    if user.get("linkedin_url"):
        contact_text += f" | {user.get('linkedin_url')}"
    run2 = contact_para.add_run(contact_text)
    run2.font.size = Pt(9)

    def add_section_header(title: str):
        p = doc.add_paragraph()
        r = p.add_run(title.upper())
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
        p.paragraph_format.border_bottom = True
        doc.add_paragraph()  # spacing

    def add_bullet(text: str):
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(text)
        p.paragraph_format.space_after = Pt(2)

    # Skills
    add_section_header("Technical Skills")
    skills = user.get("skills_extracted", user.get("skills", ""))
    doc.add_paragraph(skills).runs[0].font.size = Pt(9.5) if doc.paragraphs[-1].runs else None

    # Work history with AI bullets
    add_section_header("Professional Experience")
    work_history = json.loads(user.get("work_history_json", "[]"))
    bullets_map  = {item["role_index"]: item["bullets"] for item in bullets_data}

    for idx, role in enumerate(work_history):
        role_para = doc.add_paragraph()
        r_title   = role_para.add_run(f"{role.get('title','')} · {role.get('company','')}")
        r_title.bold = True
        r_title.font.size = Pt(10)
        role_para.add_run(f"    {role.get('start','')} – {role.get('end','')}")

        bullets = bullets_map.get(idx, role.get("bullets", []))
        for b in bullets[:5]:
            add_bullet(b)

    # Education
    add_section_header("Education")
    education = json.loads(user.get("education_json", "[]"))
    for edu in education:
        edu_p = doc.add_paragraph()
        r_edu = edu_p.add_run(f"{edu.get('degree','')}  ·  {edu.get('school','')}  ·  {edu.get('year','')}")
        r_edu.font.size = Pt(9.5)
        if edu.get("gpa"):
            edu_p.add_run(f"  |  GPA: {edu.get('gpa')}")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

print("  Generating AI bullets...")
bullets = generate_ai_bullets(user_data, job_data)
print(f"  ✅ {len(bullets)} role bullet sets generated")

for b_set in bullets:
    print(f"     {b_set.get('title')} @ {b_set.get('company')}: {len(b_set.get('bullets', []))} bullets")
    for b in b_set.get("bullets", [])[:2]:
        print(f"        • {b[:100]}")

print("\n  Building DOCX...")
try:
    docx_bytes = build_docx(user_data, job_data, bullets)
    output_path = Path("test_resume_output.docx")
    output_path.write_bytes(docx_bytes)
    print(f"  ✅ DOCX saved: {output_path.absolute()} ({len(docx_bytes):,} bytes)")
except Exception as e:
    print(f"  ❌ DOCX build failed: {e}")
    import traceback; traceback.print_exc()

# ── 5. Save parsed data to CSV ────────────────────────────────
print("\n🧪 TEST 5: Save Parsed Data to CSV (manual DB reference)")

import csv
csv_path = Path("test_sindhu_parsed.csv")
flat = {
    "user_id":      user_id,
    "full_name":    user_data["full_name"],
    "email":        parsed.get("email", ""),
    "phone":        parsed.get("phone", ""),
    "city":         parsed.get("city", ""),
    "state":        parsed.get("state", ""),
    "linkedin_url": parsed.get("linkedin_url", ""),
    "experience":   parsed.get("total_experience_years", 0),
    "skills":       parsed.get("skills", ""),
    "work_jobs":    len(parsed.get("work_history", [])),
    "education":    len(parsed.get("education", [])),
}
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=flat.keys())
    w.writeheader()
    w.writerow(flat)

print(f"  ✅ CSV saved: {csv_path.absolute()}")

print("\n" + "=" * 60)
print("✅ All tests complete!")
print(f"   DOCX output:  test_resume_output.docx")
print(f"   CSV output:   test_sindhu_parsed.csv")
print("=" * 60)
