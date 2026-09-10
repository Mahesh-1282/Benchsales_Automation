-- ============================================================
-- BENCHSALES AUTOMATION — COMPLETE TABLE CREATION SCRIPT
-- Run this ENTIRE file top-to-bottom in Databricks SQL Editor
-- All tables live in: jobs_automation_db catalog
-- Two schemas: default (jobs) and users_schema (user data)
-- ============================================================

-- Step 1: Create the users schema (separate from jobs schema)
CREATE SCHEMA IF NOT EXISTS jobs_automation_db.users_schema;

-- ============================================================
-- LAYER 0: BRONZE — Raw Jobs Landing Zone
-- (Already exists, recreating with IF NOT EXISTS for safety)
-- Populated by: 02_databricks_notebooks/01_bronze_loader.ipynb
-- ============================================================
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.jobs_harvested_bronze (
  id                    STRING COLLATE UTF8_BINARY,
  job_hash              STRING COLLATE UTF8_BINARY,
  fetch_date            DATE,
  portal                STRING COLLATE UTF8_BINARY,
  search_keyword        STRING COLLATE UTF8_BINARY,
  job_title             STRING COLLATE UTF8_BINARY,
  company_name          STRING COLLATE UTF8_BINARY,
  location              STRING COLLATE UTF8_BINARY,
  remote_type           STRING COLLATE UTF8_BINARY,
  salary_range          STRING COLLATE UTF8_BINARY,
  experience_years      STRING COLLATE UTF8_BINARY,
  tech_stack            STRING COLLATE UTF8_BINARY,
  posted_date           STRING COLLATE UTF8_BINARY,
  job_description       STRING COLLATE UTF8_BINARY,
  description_length    INT,
  roles_responsibilities STRING COLLATE UTF8_BINARY,
  requirements_section  STRING COLLATE UTF8_BINARY,
  roles_summary         STRING COLLATE UTF8_BINARY,
  apply_link            STRING COLLATE UTF8_BINARY,
  easy_apply_link       STRING COLLATE UTF8_BINARY,
  company_career_url    STRING COLLATE UTF8_BINARY,
  company_website       STRING COLLATE UTF8_BINARY,
  hr_email              STRING COLLATE UTF8_BINARY,
  job_id                STRING COLLATE UTF8_BINARY,
  visa_sponsorship      BOOLEAN,
  validation_score      INT,
  validation_status     STRING COLLATE UTF8_BINARY,
  ai_summary            STRING COLLATE UTF8_BINARY,
  detail_fetched        BOOLEAN
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.feature.appendOnly'   = 'supported',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ============================================================
-- LAYER 1: SILVER — Clean, Unique, AI-Enriched Jobs
-- One row per unique job (deduplicated by job_hash)
-- Populated by: 02_databricks_notebooks/02_silver_pipeline.ipynb
-- ============================================================
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.jobs_clean_silver (
  job_hash              STRING COLLATE UTF8_BINARY,    -- PK: MD5(lower(company+title))
  job_title             STRING COLLATE UTF8_BINARY,
  company_name          STRING COLLATE UTF8_BINARY,
  location              STRING COLLATE UTF8_BINARY,
  remote_type           STRING COLLATE UTF8_BINARY,    -- Remote / Hybrid / Onsite / Not specified
  salary_range          STRING COLLATE UTF8_BINARY,
  experience_min        INT,                            -- Parsed: "5-8 years" → 5
  experience_max        INT,                            -- Parsed: "5-8 years" → 8
  tech_stack            STRING COLLATE UTF8_BINARY,    -- comma-separated skills string
  job_description       STRING COLLATE UTF8_BINARY,
  roles_responsibilities STRING COLLATE UTF8_BINARY,
  requirements_section  STRING COLLATE UTF8_BINARY,
  roles_summary         STRING COLLATE UTF8_BINARY,
  ai_summary            STRING COLLATE UTF8_BINARY,
  apply_link            STRING COLLATE UTF8_BINARY,
  easy_apply_link       STRING COLLATE UTF8_BINARY,
  company_career_url    STRING COLLATE UTF8_BINARY,
  company_website       STRING COLLATE UTF8_BINARY,
  hr_email              STRING COLLATE UTF8_BINARY,
  portal                STRING COLLATE UTF8_BINARY,    -- First portal that found it
  posted_date           STRING COLLATE UTF8_BINARY,
  fetch_date            DATE,
  visa_sponsorship      BOOLEAN,
  validation_score      INT,
  first_seen_date       DATE,                          -- First time inserted to silver
  last_seen_date        DATE,                          -- Most recent bronze fetch_date
  active                BOOLEAN                        -- FALSE if not seen in 7+ days
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ============================================================
-- USERS SCHEMA — All user-related tables
-- ============================================================

-- ── TABLE: users (Master User Registry) ──────────────────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.users (
  user_id               STRING COLLATE UTF8_BINARY,    -- UUID, PK
  full_name             STRING COLLATE UTF8_BINARY,
  preferred_name        STRING COLLATE UTF8_BINARY,    -- Display name
  current_title         STRING COLLATE UTF8_BINARY,    -- e.g. "Senior Data Engineer"
  target_title          STRING COLLATE UTF8_BINARY,    -- Job title they're applying for
  total_experience_years DOUBLE,                        -- e.g. 6.5 (user's declared)
  phone                 STRING COLLATE UTF8_BINARY,
  city                  STRING COLLATE UTF8_BINARY,
  state                 STRING COLLATE UTF8_BINARY,
  linkedin_url          STRING COLLATE UTF8_BINARY,
  github_url            STRING COLLATE UTF8_BINARY,
  portfolio_url         STRING COLLATE UTF8_BINARY,
  min_match_score       INT,                            -- Min job match % to show (default 50)
  daily_resume_limit    INT,                            -- Resumes to auto-generate/day (default 10)
  created_at            TIMESTAMP,
  updated_at            TIMESTAMP,
  is_active             BOOLEAN
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: user_resumes (Uploaded + Parsed Resumes) ──────────
-- One user can have multiple resumes (different versions/experience levels)
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.user_resumes (
  resume_id             STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users.user_id
  file_name             STRING COLLATE UTF8_BINARY,    -- Original filename
  file_path             STRING COLLATE UTF8_BINARY,    -- DBFS path: /FileStore/resumes/uploads/{user_id}/
  file_type             STRING COLLATE UTF8_BINARY,    -- 'pdf' or 'docx'
  resume_label          STRING COLLATE UTF8_BINARY,    -- User-given name: "5yr Resume", "8yr Resume"
  years_experience      DOUBLE,                        -- Parsed from resume
  skills_extracted      STRING COLLATE UTF8_BINARY,    -- Comma-separated skills list
  summary_text          STRING COLLATE UTF8_BINARY,    -- Professional summary from resume
  -- Work history stored as JSON string: 
  -- [{"company":"ABC Corp","title":"DE","start":"2020-01","end":"2022-06",
  --   "bullets":["Built X pipeline...","Optimized Y by 40%..."]}]
  work_history_json     STRING COLLATE UTF8_BINARY,
  -- Education as JSON: [{"degree":"B.Tech","school":"JNTU","year":"2018"}]
  education_json        STRING COLLATE UTF8_BINARY,
  certifications        STRING COLLATE UTF8_BINARY,    -- Comma-separated certs
  uploaded_at           TIMESTAMP,
  is_primary            BOOLEAN                        -- Which resume to use by default
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: user_linkedin_accounts ────────────────────────────
-- One user can have multiple LinkedIn profiles (different experience levels)
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.user_linkedin_accounts (
  linkedin_id           STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users.user_id
  linkedin_url          STRING COLLATE UTF8_BINARY,
  display_name          STRING COLLATE UTF8_BINARY,    -- Name on that profile
  headline              STRING COLLATE UTF8_BINARY,    -- LinkedIn headline
  years_experience      DOUBLE,                        -- Experience level on that profile
  profile_label         STRING COLLATE UTF8_BINARY,    -- User label: "3yr profile", "7yr profile"
  scraped_data_json     STRING COLLATE UTF8_BINARY,    -- Full scraped profile JSON
  skills_on_profile     STRING COLLATE UTF8_BINARY,    -- Skills listed on that LinkedIn
  is_primary            BOOLEAN,                       -- Default profile to use
  scraped_at            TIMESTAMP,
  added_at              TIMESTAMP
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: user_github_profiles ──────────────────────────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.user_github_profiles (
  github_profile_id     STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users.user_id
  github_url            STRING COLLATE UTF8_BINARY,
  github_username       STRING COLLATE UTF8_BINARY,
  top_languages         STRING COLLATE UTF8_BINARY,    -- Comma-separated: Python, Scala, SQL...
  top_repos_json        STRING COLLATE UTF8_BINARY,    -- [{"name":"..","desc":"..","stars":5,"lang":"Python"}]
  skills_inferred       STRING COLLATE UTF8_BINARY,    -- Skills inferred from repos
  contribution_summary  STRING COLLATE UTF8_BINARY,    -- "Active contributor, 200+ commits/year"
  scraped_at            TIMESTAMP
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: user_emails (SMTP Credentials — AES Encrypted) ────
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.user_emails (
  email_id              STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users.user_id
  email_address         STRING COLLATE UTF8_BINARY,
  display_name          STRING COLLATE UTF8_BINARY,    -- "Sumanth Kumar" — shown in From:
  smtp_host             STRING COLLATE UTF8_BINARY,    -- smtp.gmail.com
  smtp_port             INT,                            -- 587
  -- app_password stored AES-256 encrypted, key in Databricks Secrets
  app_password_encrypted STRING COLLATE UTF8_BINARY,
  email_label           STRING COLLATE UTF8_BINARY,    -- "Primary Gmail", "Secondary"
  is_primary            BOOLEAN,
  is_active             BOOLEAN,
  added_at              TIMESTAMP
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: user_application_clipboard ────────────────────────
-- Per-application overrides: user can set custom experience/details
-- before generating resume for a specific job
CREATE TABLE IF NOT EXISTS jobs_automation_db.users_schema.user_application_clipboard (
  clipboard_id          STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users.user_id
  clipboard_name        STRING COLLATE UTF8_BINARY,    -- User-given name: "Senior Profile 8yr"
  -- Override experience for this clipboard
  years_experience_override DOUBLE,                    -- e.g. 8.0 (overrides resume)
  resume_id_to_use      STRING COLLATE UTF8_BINARY,    -- Which resume to base on
  linkedin_id_to_use    STRING COLLATE UTF8_BINARY,    -- Which LinkedIn profile to reference
  email_id_to_use       STRING COLLATE UTF8_BINARY,    -- Which email to send from
  -- Additional bullet points user wants injected
  extra_bullets_json    STRING COLLATE UTF8_BINARY,    -- [{"context":"..","bullet":".."}]
  -- Technologies to claim "basic knowledge" of (even if not in resume)
  basic_knowledge_skills STRING COLLATE UTF8_BINARY,   -- comma-separated
  phone_override        STRING COLLATE UTF8_BINARY,    -- Different phone for this profile
  location_override     STRING COLLATE UTF8_BINARY,    -- e.g. "Irving, TX" (relocatable)
  is_default            BOOLEAN,                       -- Default clipboard for new matches
  created_at            TIMESTAMP,
  updated_at            TIMESTAMP
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ============================================================
-- MATCHING + OUTPUT TABLES
-- ============================================================

-- ── TABLE: user_job_matches (Gold Layer — User × Job) ────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.user_job_matches (
  match_id              STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users_schema.users
  job_hash              STRING COLLATE UTF8_BINARY,    -- FK → jobs_clean_silver
  clipboard_id          STRING COLLATE UTF8_BINARY,    -- Which clipboard used (NULL = default)
  match_score           INT,                            -- 0-100 overall match
  skill_match_pct       INT,                            -- % of required skills matched
  experience_fit        STRING COLLATE UTF8_BINARY,    -- 'under' | 'exact' | 'over'
  skill_overlap         STRING COLLATE UTF8_BINARY,    -- Skills that matched (comma-sep)
  skill_gap             STRING COLLATE UTF8_BINARY,    -- Missing skills (comma-sep)
  match_reasons_json    STRING COLLATE UTF8_BINARY,    -- JSON: detailed match breakdown
  matched_at            TIMESTAMP,
  -- Resume generation tracking
  resume_generated      BOOLEAN,
  resume_id             STRING COLLATE UTF8_BINARY,    -- FK → generated_resumes once created
  resume_generated_at   TIMESTAMP,
  -- Application tracking
  status                STRING COLLATE UTF8_BINARY     -- 'matched'|'resume_pending'|'resume_ready'
                                                       -- |'applied'|'skipped'|'recruiter_replied'
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: generated_resumes ─────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.generated_resumes (
  resume_id             STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,    -- FK → users_schema.users
  job_hash              STRING COLLATE UTF8_BINARY,    -- FK → jobs_clean_silver
  match_id              STRING COLLATE UTF8_BINARY,    -- FK → user_job_matches
  clipboard_id          STRING COLLATE UTF8_BINARY,    -- Clipboard used
  -- File paths
  docx_path             STRING COLLATE UTF8_BINARY,    -- DBFS path to DOCX (editable)
  pdf_path              STRING COLLATE UTF8_BINARY,    -- DBFS path to PDF (for download)
  -- What was tailored in this resume
  experience_years_used DOUBLE,                        -- From clipboard override or resume
  skills_highlighted    STRING COLLATE UTF8_BINARY,    -- Skills emphasised (comma-sep)
  basic_knowledge_added STRING COLLATE UTF8_BINARY,    -- "having knowledge of X, Y" skills added
  -- JSON: [{company_name, tailored_bullets:[]}]
  tailored_bullets_json STRING COLLATE UTF8_BINARY,
  -- LinkedIn profile used (URL of the one selected)
  linkedin_used         STRING COLLATE UTF8_BINARY,
  -- Generation metadata
  resume_version        INT,                            -- 1,2,3... (if regenerated)
  is_latest             BOOLEAN,                       -- Only latest = TRUE
  generation_model      STRING COLLATE UTF8_BINARY,    -- e.g. nvidia/llama-3.1-8b
  generated_at          TIMESTAMP,
  -- Edit tracking
  last_edited_at        TIMESTAMP,                     -- When user edited in UI
  is_user_edited        BOOLEAN                        -- TRUE if user manually edited
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: email_drafts ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.email_drafts (
  draft_id              STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,
  job_hash              STRING COLLATE UTF8_BINARY,
  match_id              STRING COLLATE UTF8_BINARY,
  resume_id             STRING COLLATE UTF8_BINARY,    -- FK → generated_resumes
  from_email            STRING COLLATE UTF8_BINARY,
  to_email              STRING COLLATE UTF8_BINARY,    -- hr_email (NULL if not found)
  subject               STRING COLLATE UTF8_BINARY,
  body_html             STRING COLLATE UTF8_BINARY,
  body_text             STRING COLLATE UTF8_BINARY,
  draft_type            STRING COLLATE UTF8_BINARY,    -- 'initial_apply' | 'recruiter_reply'
  parent_draft_id       STRING COLLATE UTF8_BINARY,    -- For reply threads (NULL if initial)
  recruiter_email_raw   STRING COLLATE UTF8_BINARY,    -- Inbound recruiter email text (for analysis)
  status                STRING COLLATE UTF8_BINARY,    -- 'draft'|'approved'|'sent'|'failed'
  created_at            TIMESTAMP,
  sent_at               TIMESTAMP,
  smtp_response         STRING COLLATE UTF8_BINARY,
  is_user_edited        BOOLEAN
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: job_submissions (No-Duplicate Application Tracker) ─
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.job_submissions (
  submission_id         STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,
  job_hash              STRING COLLATE UTF8_BINARY,
  match_id              STRING COLLATE UTF8_BINARY,
  resume_id             STRING COLLATE UTF8_BINARY,
  submitted_at          TIMESTAMP,
  submission_method     STRING COLLATE UTF8_BINARY,    -- 'email_smtp'|'link_opened'|'easy_apply'|'manual'
  status                STRING COLLATE UTF8_BINARY     -- 'submitted'|'pending'|'failed'
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: recruiter_emails (Inbound Replies Tracking) ────────
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.recruiter_emails (
  recruiter_email_id    STRING COLLATE UTF8_BINARY,    -- UUID, PK
  user_id               STRING COLLATE UTF8_BINARY,
  job_hash              STRING COLLATE UTF8_BINARY,    -- If matched to a job
  submission_id         STRING COLLATE UTF8_BINARY,    -- If matched to a submission
  from_email            STRING COLLATE UTF8_BINARY,    -- Recruiter's email
  from_name             STRING COLLATE UTF8_BINARY,
  subject               STRING COLLATE UTF8_BINARY,
  body_raw              STRING COLLATE UTF8_BINARY,    -- Full email text
  received_at           TIMESTAMP,
  -- AI analysis results
  sentiment             STRING COLLATE UTF8_BINARY,    -- 'positive'|'neutral'|'negative'|'request_info'
  ai_suggested_response STRING COLLATE UTF8_BINARY,    -- AI-drafted reply
  analysis_json         STRING COLLATE UTF8_BINARY,    -- Full AI analysis breakdown
  reply_draft_id        STRING COLLATE UTF8_BINARY,    -- FK → email_drafts once draft created
  status                STRING COLLATE UTF8_BINARY     -- 'new'|'draft_created'|'replied'|'ignored'
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ── TABLE: bronze_load_audit ──────────────────────────────────
-- Track which CSV files have been loaded to bronze (avoid re-loading)
CREATE TABLE IF NOT EXISTS jobs_automation_db.default.bronze_load_audit (
  audit_id              STRING COLLATE UTF8_BINARY,
  file_name             STRING COLLATE UTF8_BINARY,
  file_path             STRING COLLATE UTF8_BINARY,
  loaded_at             TIMESTAMP,
  rows_loaded           INT,
  rows_merged           INT,
  status                STRING COLLATE UTF8_BINARY     -- 'success'|'failed'
)
USING delta
DEFAULT COLLATION UTF8_BINARY
TBLPROPERTIES (
  'delta.enableDeletionVectors' = 'true',
  'delta.parquet.compression.codec' = 'zstd'
);

-- ============================================================
-- VERIFY: Check all tables created
-- ============================================================
SHOW TABLES IN jobs_automation_db.default;
SHOW TABLES IN jobs_automation_db.users_schema;
