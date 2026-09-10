# 🚀 Benchsales Automation

> End-to-end automated bench-sales pipeline: Job Scraping → AI Resume Tailoring → Email Outreach → Application Tracking.

---

## 📁 Folder Structure

```
Benchsales_Automation/
├── 01_local_scraper/
│   ├── jsearch_local.py        # Run daily on your local machine
│   └── .env.example            # Copy to .env and add your API key
│
├── 02_databricks_notebooks/
│   ├── 01_bronze_loader.ipynb  # CSV → Bronze Delta table (MERGE, no duplicates)
│   ├── 02_silver_pipeline.ipynb# Bronze → Silver (dedup + AI enrichment)
│   ├── 03_user_job_matching.ipynb # Silver × User → Match scores
│   └── 04_resume_generator.ipynb  # AI-tailored DOCX resumes + email drafts
│
├── 03_databricks_app/
│   ├── app.py                  # Streamlit main entry
│   └── pages/
│       ├── 1_Onboarding.py     # Upload resume, profile, email, clipboards
│       ├── 2_Jobs_Dashboard.py # View matches, trigger generation, apply
│       ├── 3_Resume_Viewer.py  # Preview, edit, download DOCX/PDF
│       └── 4_Email_Outreach.py # Send emails, analyze recruiter replies
│
├── 04_sql_scripts/
│   └── create_all_tables.sql   # All 12 tables — run ONCE in Databricks SQL
│
└── requirements.txt
```

---

## 🚦 Setup Order (First Time)

### Step 1 — Run SQL once in Databricks
```sql
-- Open Databricks → SQL Editor → Open file → create_all_tables.sql → Run All
```

### Step 2 — Set up Databricks Secrets
```bash
databricks secrets create-scope jobs_automation
databricks secrets put --scope jobs_automation --key nvidia_nim
# Paste your NVIDIA NIM API key when prompted
```

### Step 3 — Local Scraper Setup
```bash
cd 01_local_scraper
cp .env.example .env
# Edit .env: add JSEARCH_API_KEY=your_key
pip install requests python-dotenv
python jsearch_local.py   # Runs daily, outputs daily_jobs_YYYYMMDD.csv
```

### Step 4 — Upload CSV to Databricks
- Databricks → Data → DBFS → `/FileStore/jobs_daily/`
- Upload the CSV file

### Step 5 — Run Databricks Notebooks (in order)
1. `01_bronze_loader` → loads CSV into bronze
2. `02_silver_pipeline` → deduplicates + AI enriches
3. `03_user_job_matching` → matches users to jobs
4. `04_resume_generator` → generates AI resumes

### Step 6 — Deploy Streamlit App
```bash
# In Databricks Apps:
# Create App → Select Streamlit → Point to 03_databricks_app/app.py
# OR run locally:
pip install -r requirements.txt
cd 03_databricks_app
streamlit run app.py
```

---

## 🔄 Daily Workflow

```
Morning (local machine):
  python 01_local_scraper/jsearch_local.py
  → Upload CSV to DBFS

Automated (Databricks scheduled jobs):
  → 01_bronze_loader  (runs after CSV upload)
  → 02_silver_pipeline (runs after bronze)
  → 03_user_job_matching (runs after silver)
  → 04_resume_generator (runs after matching)

Evening (Streamlit App):
  → Review new matches in Jobs Dashboard
  → Check generated resumes, edit if needed
  → Send emails or apply via link
  → Analyze any recruiter replies
```

---

## 📊 Database Schema

| Table | Schema | Purpose |
|-------|--------|---------|
| `jobs_harvested_bronze` | default | Raw scraped jobs (all portals) |
| `jobs_clean_silver` | default | Unique AI-enriched jobs |
| `user_job_matches` | default | User × Job match scores |
| `generated_resumes` | default | AI-tailored DOCX/PDF resumes |
| `email_drafts` | default | Application email drafts |
| `job_submissions` | default | Application tracking |
| `recruiter_emails` | default | Inbound recruiter replies |
| `bronze_load_audit` | default | CSV load tracking |
| `users` | users_schema | User profiles |
| `user_resumes` | users_schema | Uploaded resumes |
| `user_linkedin_accounts` | users_schema | LinkedIn profiles |
| `user_github_profiles` | users_schema | GitHub data |
| `user_emails` | users_schema | SMTP credentials |
| `user_application_clipboard` | users_schema | Profile overrides |

---

## 🔑 Environment Variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `JSEARCH_API_KEY` | `.env` (local) | RapidAPI JSearch key |
| `nvidia_nim` | Databricks Secrets | NVIDIA NIM API key |
| `EMAIL_ENCRYPTION_KEY` | Databricks Secrets | AES key for email passwords |

---

## 🤖 AI Models Used

- **NVIDIA NIM** (`meta/llama-3.1-8b-instruct`) — Resume tailoring, job scoring, email analysis
- **Free tier**: 1000 credits/month at [build.nvidia.com](https://build.nvidia.com)
