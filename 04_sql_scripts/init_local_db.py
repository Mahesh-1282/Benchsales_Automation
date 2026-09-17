import sqlite3
import os
from pathlib import Path

# DB file will be at the root of the project
DB_PATH = Path(__file__).parent.parent / "local_db.sqlite"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # ── LAYER 0: BRONZE ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs_harvested_bronze (
      id TEXT,
      job_hash TEXT,
      fetch_date DATE,
      portal TEXT,
      search_keyword TEXT,
      job_title TEXT,
      company_name TEXT,
      location TEXT,
      remote_type TEXT,
      salary_range TEXT,
      experience_years TEXT,
      tech_stack TEXT,
      posted_date TEXT,
      job_description TEXT,
      description_length INTEGER,
      roles_responsibilities TEXT,
      requirements_section TEXT,
      roles_summary TEXT,
      apply_link TEXT,
      easy_apply_link TEXT,
      company_career_url TEXT,
      company_website TEXT,
      hr_email TEXT,
      job_id TEXT,
      visa_sponsorship TEXT,
      validation_score INTEGER,
      validation_status TEXT,
      ai_summary TEXT,
      detail_fetched BOOLEAN
    )
    """)

    # ── LAYER 1: SILVER ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs_clean_silver (
      job_hash TEXT PRIMARY KEY,
      job_title TEXT,
      company_name TEXT,
      location TEXT,
      remote_type TEXT,
      salary_range TEXT,
      experience_min INTEGER,
      experience_max INTEGER,
      tech_stack TEXT,
      job_description TEXT,
      roles_responsibilities TEXT,
      requirements_section TEXT,
      roles_summary TEXT,
      ai_summary TEXT,
      apply_link TEXT,
      easy_apply_link TEXT,
      company_career_url TEXT,
      company_website TEXT,
      hr_email TEXT,
      portal TEXT,
      posted_date TEXT,
      fetch_date DATE,
      visa_sponsorship BOOLEAN,
      validation_score INTEGER,
      first_seen_date DATE,
      last_seen_date DATE,
      active BOOLEAN
    )
    """)

    # ── USERS ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY,
      full_name TEXT,
      preferred_name TEXT,
      current_title TEXT,
      target_title TEXT,
      total_experience_years REAL,
      phone TEXT,
      city TEXT,
      state TEXT,
      linkedin_url TEXT,
      github_url TEXT,
      portfolio_url TEXT,
      min_match_score INTEGER,
      daily_resume_limit INTEGER,
      created_at DATETIME,
      updated_at DATETIME,
      is_active BOOLEAN,
      target_domains TEXT,
      ai_scraping_keywords TEXT
    )
    """)

    # ── RESUMES ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_resumes (
      resume_id TEXT PRIMARY KEY,
      user_id TEXT,
      file_name TEXT,
      file_path TEXT,
      file_type TEXT,
      resume_label TEXT,
      years_experience REAL,
      skills_extracted TEXT,
      summary_text TEXT,
      work_history_json TEXT,
      education_json TEXT,
      certifications TEXT,
      uploaded_at DATETIME,
      is_primary BOOLEAN,
      FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    # ── CLIPBOARD ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_application_clipboard (
      clipboard_id TEXT PRIMARY KEY,
      user_id TEXT,
      clipboard_name TEXT,
      years_experience_override REAL,
      resume_id_to_use TEXT,
      linkedin_id_to_use TEXT,
      email_id_to_use TEXT,
      extra_bullets_json TEXT,
      basic_knowledge_skills TEXT,
      phone_override TEXT,
      location_override TEXT,
      is_default BOOLEAN,
      created_at DATETIME,
      updated_at DATETIME,
      FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    # ── JOB MATCHES ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_job_matches (
      match_id TEXT PRIMARY KEY,
      user_id TEXT,
      job_hash TEXT,
      clipboard_id TEXT,
      match_score INTEGER,
      skill_match_pct INTEGER,
      experience_fit TEXT,
      skill_overlap TEXT,
      skill_gap TEXT,
      match_reasons_json TEXT,
      matched_at DATETIME,
      resume_generated BOOLEAN,
      resume_id TEXT,
      resume_generated_at DATETIME,
      status TEXT,
      FOREIGN KEY(user_id) REFERENCES users(user_id),
      FOREIGN KEY(job_hash) REFERENCES jobs_clean_silver(job_hash)
    )
    """)

    # ── GENERATED RESUMES ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generated_resumes (
      resume_id TEXT PRIMARY KEY,
      user_id TEXT,
      job_hash TEXT,
      match_id TEXT,
      clipboard_id TEXT,
      docx_path TEXT,
      pdf_path TEXT,
      experience_years_used REAL,
      skills_highlighted TEXT,
      basic_knowledge_added TEXT,
      tailored_bullets_json TEXT,
      linkedin_used TEXT,
      resume_version INTEGER,
      is_latest BOOLEAN,
      generation_model TEXT,
      generated_at DATETIME,
      last_edited_at DATETIME,
      is_user_edited BOOLEAN,
      FOREIGN KEY(user_id) REFERENCES users(user_id),
      FOREIGN KEY(match_id) REFERENCES user_job_matches(match_id)
    )
    """)
    
    # ── JOB SUBMISSIONS ──
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS job_submissions (
      submission_id TEXT PRIMARY KEY,
      user_id TEXT,
      job_hash TEXT,
      match_id TEXT,
      resume_id TEXT,
      submitted_at DATETIME,
      submission_method TEXT,
      status TEXT
    )
    """)

    conn.commit()
    conn.close()
    print(f"✅ Local SQLite DB initialized at {DB_PATH}")

if __name__ == "__main__":
    init_db()
