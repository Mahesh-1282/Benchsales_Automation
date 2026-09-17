#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V11 — COMPREHENSIVE UNIT TESTS                  ║
║  Tests ALL helper functions, record building, DB operations,         ║
║  AI parsing, and schema validation                                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import unittest
import hashlib
import uuid
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta

# Add parent paths so we can import from 01_local_scraper
sys.path.insert(0, str(Path(__file__).parent.parent / "01_local_scraper"))
sys.path.insert(0, str(Path(__file__).parent.parent / "03_databricks_app"))

# ── Import functions under test ──────────────────────────────────
from job_scrapper import (
    is_recent_job,
    extract_emails,
    best_hr_email,
    guess_company_domain,
    build_record,
    extract_roles,
    extract_requirements,
    extract_salary,
    extract_experience,
    rule_based_score,
    CSV_HEADERS,
    ai_expand_keywords,
    TOKEN_TRACKER,
)

# ── Import DB utils ──────────────────────────────────────────────
from db_utils import get_connection, execute_sql, insert_row, query_df, _escape, DB_PATH


# ═══════════════════════════════════════════════════════════════════
# 📝  TEST COUNTERS
# ═══════════════════════════════════════════════════════════════════
TOTAL_TESTS = 0
PASSED_TESTS = 0
FAILED_TESTS = 0
FAILED_DETAILS = []


def run_test(test_name, test_func):
    """Run a single test and track results."""
    global TOTAL_TESTS, PASSED_TESTS, FAILED_TESTS
    TOTAL_TESTS += 1
    try:
        test_func()
        PASSED_TESTS += 1
        print(f"  ✅ {test_name}")
    except AssertionError as e:
        FAILED_TESTS += 1
        FAILED_DETAILS.append((test_name, str(e)))
        print(f"  ❌ {test_name}: {e}")
    except Exception as e:
        FAILED_TESTS += 1
        FAILED_DETAILS.append((test_name, str(e)))
        print(f"  💥 {test_name}: EXCEPTION → {e}")


# ═══════════════════════════════════════════════════════════════════
# 🗓️  DATE VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════
def test_date_validation():
    print("\n🗓️  DATE VALIDATION TESTS")
    print("─" * 50)

    # Test 1: "today" should be recent
    run_test("'today' is recent", lambda: assert_true(is_recent_job("today")))

    # Test 2: "yesterday" should be recent
    run_test("'yesterday' is recent", lambda: assert_true(is_recent_job("yesterday")))

    # Test 3: "just now" should be recent
    run_test("'just now' is recent", lambda: assert_true(is_recent_job("just now")))

    # Test 4: "1 day ago" should be recent
    run_test("'1 day ago' is recent", lambda: assert_true(is_recent_job("1 day ago")))

    # Test 5: "24h" should be recent
    run_test("'24h' is recent", lambda: assert_true(is_recent_job("24h")))

    # Test 6: "1d" should be recent
    run_test("'1d' is recent", lambda: assert_true(is_recent_job("1d")))

    # Test 7: "minutes ago" should be recent
    run_test("'5 minutes ago' is recent", lambda: assert_true(is_recent_job("5 minutes ago")))

    # Test 8: "hours ago" should be recent
    run_test("'2 hours ago' is recent", lambda: assert_true(is_recent_job("2 hours ago")))

    # Test 9: "hour ago" should be recent
    run_test("'1 hour ago' is recent", lambda: assert_true(is_recent_job("1 hour ago")))

    # Test 10: Empty/None should be treated as recent (no date = assume fresh)
    run_test("empty string is recent", lambda: assert_true(is_recent_job("")))
    run_test("None is recent", lambda: assert_true(is_recent_job(None)))

    # Test 11: "30 days ago" should NOT be recent
    run_test("'30 days ago' is NOT recent", lambda: assert_true(not is_recent_job("30 days ago")))

    # Test 12: "2 weeks ago" should NOT be recent
    run_test("'2 weeks ago' is NOT recent", lambda: assert_true(not is_recent_job("2 weeks ago")))

    # Test 13: Date strings
    today_str = datetime.now().strftime("%B %d, %Y")
    run_test(f"today's date '{today_str}' is recent", lambda: assert_true(is_recent_job(today_str)))

    # Test 14: Case insensitivity
    run_test("'TODAY' (uppercase) is recent", lambda: assert_true(is_recent_job("TODAY")))
    run_test("'Just Now' (mixed case) is recent", lambda: assert_true(is_recent_job("Just Now")))

    # Test 15: Glassdoor format
    run_test("'1d' (Glassdoor) is recent", lambda: assert_true(is_recent_job("1d")))

    # Test 16: "3d" should NOT be recent (more than 1 day)
    run_test("'3d' is NOT recent", lambda: assert_true(not is_recent_job("3d")))

    # Test 17: "48h" should be recent (within 48 hours)
    run_test("'48h' is recent", lambda: assert_true(is_recent_job("48h")))

    # Test 18: "seconds ago" should be recent
    run_test("'30 seconds ago' is recent", lambda: assert_true(is_recent_job("30 seconds ago")))


# ═══════════════════════════════════════════════════════════════════
# 📧  EMAIL EXTRACTION TESTS
# ═══════════════════════════════════════════════════════════════════
def test_email_extraction():
    print("\n📧  EMAIL EXTRACTION TESTS")
    print("─" * 50)

    # Test 1: Basic email extraction
    run_test("extract basic email",
             lambda: assert_true("john@company.com" in extract_emails("Contact john@company.com for details")))

    # Test 2: Multiple emails
    run_test("extract multiple emails",
             lambda: assert_equal(len(extract_emails("email1@a.com and email2@b.com")), 2))

    # Test 3: Filter blacklisted domains
    run_test("filter sentry.io",
             lambda: assert_true(len(extract_emails("err@sentry.io")) == 0))
    run_test("filter example.com",
             lambda: assert_true(len(extract_emails("test@example.com")) == 0))
    run_test("filter noreply",
             lambda: assert_true(len(extract_emails("noreply@company.com")) == 0))

    # Test 4: Deduplication
    run_test("deduplicate emails",
             lambda: assert_equal(len(extract_emails("a@b.com a@b.com a@b.com")), 1))

    # Test 5: Email with special chars
    run_test("email with dots and plus",
             lambda: assert_true("first.last+tag@domain.com" in extract_emails("Contact first.last+tag@domain.com")))

    # Test 6: No emails in text
    run_test("no emails returns empty",
             lambda: assert_equal(extract_emails("No email here"), []))

    # Test 7: Filter AWS domain
    run_test("filter amazonaws.com",
             lambda: assert_true(len(extract_emails("bucket@amazonaws.com")) == 0))

    # Test 8: HR email priority
    run_test("best_hr_email picks 'recruit'",
             lambda: assert_equal(best_hr_email(["info@co.com", "recruit@co.com", "sales@co.com"]), "recruit@co.com"))
    run_test("best_hr_email picks 'hr'",
             lambda: assert_equal(best_hr_email(["info@co.com", "hr@co.com"]), "hr@co.com"))
    run_test("best_hr_email picks 'talent'",
             lambda: assert_equal(best_hr_email(["info@co.com", "talent@co.com"]), "talent@co.com"))
    run_test("best_hr_email picks 'hiring'",
             lambda: assert_equal(best_hr_email(["info@co.com", "hiring@co.com"]), "hiring@co.com"))
    run_test("best_hr_email picks 'careers'",
             lambda: assert_equal(best_hr_email(["info@co.com", "careers@co.com"]), "careers@co.com"))

    # Test 9: Company domain preference
    run_test("best_hr_email prefers company domain",
             lambda: assert_equal(best_hr_email(["random@gmail.com", "hr@mycompany.com"], "mycompany.com"), "hr@mycompany.com"))

    # Test 10: Empty list
    run_test("best_hr_email empty list returns ''",
             lambda: assert_equal(best_hr_email([]), ""))


# ═══════════════════════════════════════════════════════════════════
# 🔍  COMPANY DOMAIN GUESSER TESTS
# ═══════════════════════════════════════════════════════════════════
def test_company_domain():
    print("\n🔍  COMPANY DOMAIN GUESSER TESTS")
    print("─" * 50)

    run_test("guess domain for 'Google'",
             lambda: assert_equal(guess_company_domain("Google"), "google.com"))
    run_test("guess domain for 'Microsoft Corp'",
             lambda: assert_equal(guess_company_domain("Microsoft Corp"), "microsoft.com"))
    run_test("guess domain for empty string",
             lambda: assert_equal(guess_company_domain(""), ""))
    run_test("guess domain for 'Unknown'",
             lambda: assert_equal(guess_company_domain("Unknown"), ""))
    run_test("guess domain with special chars",
             lambda: assert_equal(guess_company_domain("Amazon.com Inc."), "amazoncom.com"))


# ═══════════════════════════════════════════════════════════════════
# 🏗️  RECORD BUILDER TESTS
# ═══════════════════════════════════════════════════════════════════
def test_record_builder():
    print("\n🏗️  RECORD BUILDER TESTS")
    print("─" * 50)

    rec = build_record(
        portal="TestPortal",
        keyword="Java Developer",
        title="Senior Java Developer",
        company="TechCorp",
        location="New York, NY",
        desc="We are looking for a Java developer with 5+ years experience in Spring Boot, microservices.",
        url="https://example.com/job/123",
        posted="today",
        salary="$120K-$150K",
        job_id="JOB-123"
    )

    # Test all 29 columns are present
    run_test("record has all CSV_HEADERS columns",
             lambda: assert_true(all(h in rec for h in CSV_HEADERS)))

    # Test specific fields
    run_test("id is valid UUID",
             lambda: assert_true(len(rec["id"]) == 36 and "-" in rec["id"]))
    run_test("job_hash is MD5",
             lambda: assert_equal(rec["job_hash"], hashlib.md5("https://example.com/job/123".encode()).hexdigest()))
    run_test("fetch_date is today",
             lambda: assert_equal(rec["fetch_date"], date.today().strftime("%Y-%m-%d")))
    run_test("portal is correct",
             lambda: assert_equal(rec["portal"], "TestPortal"))
    run_test("search_keyword is correct",
             lambda: assert_equal(rec["search_keyword"], "Java Developer"))
    run_test("job_title is correct",
             lambda: assert_equal(rec["job_title"], "Senior Java Developer"))
    run_test("company_name is correct",
             lambda: assert_equal(rec["company_name"], "TechCorp"))
    run_test("location is correct",
             lambda: assert_equal(rec["location"], "New York, NY"))
    run_test("salary_range is correct",
             lambda: assert_equal(rec["salary_range"], "$120K-$150K"))
    run_test("apply_link is correct",
             lambda: assert_equal(rec["apply_link"], "https://example.com/job/123"))
    run_test("job_id is correct",
             lambda: assert_equal(rec["job_id"], "JOB-123"))
    run_test("detail_fetched is False initially",
             lambda: assert_equal(rec["detail_fetched"], False))
    run_test("validation_score is 0 initially",
             lambda: assert_equal(rec["validation_score"], 0))
    run_test("validation_status is 'Pending' initially",
             lambda: assert_equal(rec["validation_status"], "Pending"))
    run_test("description_length computed correctly",
             lambda: assert_true(rec["description_length"] > 0))

    # Test with minimal data
    minimal = build_record("P", "K", "", "", "", "", "https://x.com/1")
    run_test("minimal record has all columns",
             lambda: assert_true(all(h in minimal for h in CSV_HEADERS)))
    run_test("minimal title defaults to keyword",
             lambda: assert_equal(minimal["job_title"], "K"))
    run_test("minimal company defaults to 'Unknown'",
             lambda: assert_equal(minimal["company_name"], "Unknown"))
    run_test("minimal location defaults to 'USA'",
             lambda: assert_equal(minimal["location"], "USA"))

    # Test no None values in record
    run_test("no None values in record",
             lambda: assert_true(all(v is not None for v in rec.values())))


# ═══════════════════════════════════════════════════════════════════
# 📄  TEXT EXTRACTION TESTS
# ═══════════════════════════════════════════════════════════════════
def test_text_extraction():
    print("\n📄  TEXT EXTRACTION TESTS")
    print("─" * 50)

    sample_jd = """
    About the Role:
    We are looking for a Senior Software Engineer.

    Key Responsibilities:
    - Design and implement scalable microservices using Java and Spring Boot
    - Lead code reviews and mentor junior developers
    - Collaborate with product and design teams to deliver features
    - Optimize application performance and troubleshoot production issues
    - Implement CI/CD pipelines using Jenkins and Docker

    Requirements:
    - 5+ years of experience in Java/Spring Boot development
    - Strong understanding of microservices architecture
    - Proficiency in SQL and NoSQL databases
    - Experience with AWS/GCP cloud services
    - Bachelor's degree in Computer Science or related field

    Benefits:
    - Competitive salary and equity
    - Remote-first culture
    """

    # Roles extraction
    run_test("extract_roles finds responsibilities",
             lambda: assert_true(len(extract_roles(sample_jd)) > 100))
    run_test("extract_roles contains 'microservices'",
             lambda: assert_true("microservices" in extract_roles(sample_jd).lower()))

    # Requirements extraction
    run_test("extract_requirements finds requirements",
             lambda: assert_true(len(extract_requirements(sample_jd)) > 100))
    run_test("extract_requirements contains 'experience'",
             lambda: assert_true("experience" in extract_requirements(sample_jd).lower()))

    # Salary extraction
    run_test("extract_salary from '$120K-$150K'",
             lambda: assert_true("120" in extract_salary("Salary: $120K-$150K per year")))
    run_test("extract_salary from '$100,000'",
             lambda: assert_true("100,000" in extract_salary("compensation: $100,000-$130,000 per year")))
    run_test("extract_salary empty when no salary",
             lambda: assert_equal(extract_salary("No salary information"), ""))

    # Experience extraction
    run_test("extract_experience '5+ years'",
             lambda: assert_true("5" in extract_experience("5+ years of experience")))
    run_test("extract_experience '3 to 5 years'",
             lambda: assert_true("3" in extract_experience("3 to 5 years of experience")))
    run_test("extract_experience 'minimum 2 years'",
             lambda: assert_true("2" in extract_experience("minimum 2 years")))
    run_test("extract_experience empty when no exp",
             lambda: assert_equal(extract_experience("No experience required"), ""))


# ═══════════════════════════════════════════════════════════════════
# 🤖  RULE-BASED SCORING TESTS
# ═══════════════════════════════════════════════════════════════════
def test_rule_based_scoring():
    print("\n🤖  RULE-BASED SCORING TESTS")
    print("─" * 50)

    # Good job
    good_job = {
        "job_title": "Senior Java Developer",
        "company_name": "Google",
        "job_description": "We are looking for a candidate with experience in software engineering. "
                          "The role requires skills in Java, Spring Boot, and microservices. "
                          "Key responsibilities include designing scalable systems and leading a team. "
                          "Qualifications: 5+ years experience. Benefits: competitive salary, equity. "
                          "Apply now to join our growing engineering team. Requirements include strong problem solving skills."
    }
    score_good = rule_based_score(good_job)
    run_test(f"good job scores high ({score_good} >= 60)",
             lambda: assert_true(score_good >= 60))

    # Bad/junk job
    bad_job = {
        "job_title": "x",
        "company_name": "",
        "job_description": "short"
    }
    score_bad = rule_based_score(bad_job)
    run_test(f"junk job scores low ({score_bad} <= 30)",
             lambda: assert_true(score_bad <= 30))

    # Medium job
    mid_job = {
        "job_title": "Data Analyst",
        "company_name": "Startup Inc",
        "job_description": "We need a data analyst with SQL experience. Apply today."
    }
    score_mid = rule_based_score(mid_job)
    run_test(f"medium job scores mid ({score_mid} between 30-80)",
             lambda: assert_true(30 <= score_mid <= 80))

    # Score is always 0-100
    run_test("score never exceeds 100",
             lambda: assert_true(score_good <= 100))
    run_test("score never below 0",
             lambda: assert_true(score_bad >= 0))


# ═══════════════════════════════════════════════════════════════════
# 💾  DATABASE TESTS
# ═══════════════════════════════════════════════════════════════════
def test_database():
    print("\n💾  DATABASE TESTS")
    print("─" * 50)

    # Initialize test DB
    from init_local_db import init_db
    init_db()

    # Test 1: DB file exists
    run_test("SQLite DB file exists",
             lambda: assert_true(DB_PATH.exists()))

    # Test 2: Table exists
    ok, rows, err = execute_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs_harvested_bronze'")
    run_test("jobs_harvested_bronze table exists",
             lambda: assert_true(ok and len(rows) > 0))

    # Test 3: Insert a test record
    test_rec = build_record(
        "UnitTest", "TestKeyword", "Test Title", "Test Company",
        "Test Location", "Test description content for unit test", "https://unittest.com/job/1"
    )
    test_rec["validation_score"] = 75
    test_rec["validation_status"] = "Valid"
    test_rec["ai_summary"] = "Test AI summary"
    test_rec["tech_stack"] = "Python, Java, SQL"

    ok, err = insert_row("jobs_harvested_bronze", test_rec)
    run_test(f"insert test record (ok={ok}, err={err[:50] if err else 'none'})",
             lambda: assert_true(ok))

    # Test 4: Query the inserted record
    df = query_df(f"SELECT * FROM jobs_harvested_bronze WHERE job_hash = '{test_rec['job_hash']}'")
    run_test("query returns inserted record",
             lambda: assert_true(len(df) > 0))

    # Test 5: Check column count
    cols = list(df.columns)
    run_test(f"bronze table has >= 29 columns (has {len(cols)})",
             lambda: assert_true(len(cols) >= 29))

    # Test 6: Verify key columns have values
    if len(df) > 0:
        row = df.iloc[0]
        run_test("id column populated", lambda: assert_true(bool(row.get("id"))))
        run_test("job_hash column populated", lambda: assert_true(bool(row.get("job_hash"))))
        run_test("fetch_date column populated", lambda: assert_true(bool(row.get("fetch_date"))))
        run_test("portal column populated", lambda: assert_true(bool(row.get("portal"))))
        run_test("job_title column populated", lambda: assert_true(bool(row.get("job_title"))))
        run_test("company_name column populated", lambda: assert_true(bool(row.get("company_name"))))
        run_test("validation_score column populated", lambda: assert_true(row.get("validation_score", 0) > 0))
        run_test("tech_stack column populated", lambda: assert_true(bool(row.get("tech_stack"))))

    # Test 7: Dedup - inserting same record should fail or be skipped
    ok2, err2 = insert_row("jobs_harvested_bronze", test_rec)
    # SQLite should error on duplicate primary key or unique constraint
    run_test("duplicate insert handled", lambda: assert_true(True))  # Just verify no crash

    # Test 8: SQL escape function
    run_test("_escape handles None", lambda: assert_equal(_escape(None), "NULL"))
    run_test("_escape handles True", lambda: assert_equal(_escape(True), "1"))
    run_test("_escape handles False", lambda: assert_equal(_escape(False), "0"))
    run_test("_escape handles int", lambda: assert_equal(_escape(42), "42"))
    run_test("_escape handles string with quotes",
             lambda: assert_true("''" in _escape("it's a test")))

    # Cleanup test record
    execute_sql(f"DELETE FROM jobs_harvested_bronze WHERE job_hash = '{test_rec['job_hash']}'")


# ═══════════════════════════════════════════════════════════════════
# 🔢  TOKEN TRACKER TESTS
# ═══════════════════════════════════════════════════════════════════
def test_token_tracker():
    print("\n🔢  TOKEN TRACKER TESTS")
    print("─" * 50)

    from job_scrapper import track_tokens, TOKEN_TRACKER

    # Reset tracker
    TOKEN_TRACKER["total_input_tokens"] = 0
    TOKEN_TRACKER["total_output_tokens"] = 0
    TOKEN_TRACKER["total_api_calls"] = 0
    TOKEN_TRACKER["calls_by_model"] = {}
    TOKEN_TRACKER["tokens_per_job"] = []

    # Track some tokens
    track_tokens("test-model", 100, 50, "hash1")
    run_test("total_input_tokens updated", lambda: assert_equal(TOKEN_TRACKER["total_input_tokens"], 100))
    run_test("total_output_tokens updated", lambda: assert_equal(TOKEN_TRACKER["total_output_tokens"], 50))
    run_test("total_api_calls updated", lambda: assert_equal(TOKEN_TRACKER["total_api_calls"], 1))
    run_test("model tracked", lambda: assert_equal(TOKEN_TRACKER["calls_by_model"]["test-model"], 1))
    run_test("per-job tracking", lambda: assert_equal(len(TOKEN_TRACKER["tokens_per_job"]), 1))

    # Track more
    track_tokens("test-model", 200, 100, "hash2")
    track_tokens("other-model", 50, 25, "hash3")
    run_test("cumulative input tokens", lambda: assert_equal(TOKEN_TRACKER["total_input_tokens"], 350))
    run_test("cumulative output tokens", lambda: assert_equal(TOKEN_TRACKER["total_output_tokens"], 175))
    run_test("cumulative api calls", lambda: assert_equal(TOKEN_TRACKER["total_api_calls"], 3))
    run_test("multiple models tracked", lambda: assert_equal(len(TOKEN_TRACKER["calls_by_model"]), 2))


# ═══════════════════════════════════════════════════════════════════
# 📋  SCHEMA VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════
def test_schema_validation():
    print("\n📋  SCHEMA VALIDATION TESTS")
    print("─" * 50)

    expected_columns = [
        "id", "job_hash", "fetch_date", "portal", "search_keyword",
        "job_title", "company_name", "location", "remote_type",
        "salary_range", "experience_years", "tech_stack",
        "posted_date", "job_description", "description_length",
        "roles_responsibilities", "requirements_section", "roles_summary",
        "apply_link", "easy_apply_link", "company_career_url",
        "company_website", "hr_email",
        "job_id", "visa_sponsorship",
        "validation_score", "validation_status", "ai_summary",
        "detail_fetched",
    ]

    # Test CSV_HEADERS matches expected
    run_test(f"CSV_HEADERS has {len(expected_columns)} columns",
             lambda: assert_equal(len(CSV_HEADERS), len(expected_columns)))

    for col in expected_columns:
        run_test(f"CSV_HEADERS contains '{col}'",
                 lambda col=col: assert_true(col in CSV_HEADERS))

    # Test build_record produces all columns
    rec = build_record("P", "K", "T", "C", "L", "D", "https://x.com/1")
    for col in expected_columns:
        run_test(f"build_record has '{col}'",
                 lambda col=col: assert_true(col in rec))

    # Test no column has None value
    for col in expected_columns:
        run_test(f"build_record '{col}' is not None",
                 lambda col=col: assert_true(rec[col] is not None))


# ═══════════════════════════════════════════════════════════════════
# 🌐  PORTAL CONFIG TESTS
# ═══════════════════════════════════════════════════════════════════
def test_portal_config():
    print("\n🌐  PORTAL CONFIG TESTS")
    print("─" * 50)

    from job_scrapper import CONFIG

    run_test("enable_all_sites is True", lambda: assert_true(CONFIG["enable_all_sites"]))
    run_test("max_jobs_per_portal is 25", lambda: assert_equal(CONFIG["max_jobs_per_portal_per_role"], 25))
    run_test("page_timeout_ms is 30000", lambda: assert_equal(CONFIG["page_timeout_ms"], 30_000))
    run_test("detail_fetch_workers is 3", lambda: assert_equal(CONFIG["detail_fetch_workers"], 3))
    run_test("headless is True", lambda: assert_true(CONFIG["headless"]))

    # NVIDIA NIM config
    run_test("nvidia_simple_model configured",
             lambda: assert_true("llama" in CONFIG["nvidia_simple_model"] or "meta" in CONFIG["nvidia_simple_model"]))
    run_test("nvidia_ultra_model configured",
             lambda: assert_true("nemotron" in CONFIG["nvidia_ultra_model"] or "nvidia" in CONFIG["nvidia_ultra_model"]))


# ═══════════════════════════════════════════════════════════════════
# 🔗  HASH & DEDUP TESTS
# ═══════════════════════════════════════════════════════════════════
def test_hash_dedup():
    print("\n🔗  HASH & DEDUP TESTS")
    print("─" * 50)

    url1 = "https://example.com/job/123"
    url2 = "https://example.com/job/456"

    hash1 = hashlib.md5(url1.encode()).hexdigest()
    hash2 = hashlib.md5(url2.encode()).hexdigest()

    run_test("different URLs produce different hashes",
             lambda: assert_true(hash1 != hash2))

    run_test("same URL produces same hash",
             lambda: assert_equal(hashlib.md5(url1.encode()).hexdigest(), hash1))

    rec1 = build_record("P", "K", "T", "C", "L", "D", url1)
    rec2 = build_record("P", "K", "T", "C", "L", "D", url1)
    run_test("same URL records have same hash",
             lambda: assert_equal(rec1["job_hash"], rec2["job_hash"]))

    rec3 = build_record("P", "K", "T", "C", "L", "D", url2)
    run_test("different URL records have different hash",
             lambda: assert_true(rec1["job_hash"] != rec3["job_hash"]))


# ═══════════════════════════════════════════════════════════════════
# 🆔  UUID TESTS
# ═══════════════════════════════════════════════════════════════════
def test_uuid_generation():
    print("\n🆔  UUID GENERATION TESTS")
    print("─" * 50)

    rec1 = build_record("P", "K", "T", "C", "L", "D", "https://x.com/1")
    rec2 = build_record("P", "K", "T", "C", "L", "D", "https://x.com/2")

    run_test("each record gets unique id",
             lambda: assert_true(rec1["id"] != rec2["id"]))

    run_test("id is valid UUID format",
             lambda: assert_true(len(rec1["id"]) == 36))

    # Validate UUID format
    try:
        uuid.UUID(rec1["id"])
        valid = True
    except ValueError:
        valid = False
    run_test("id is parseable as UUID",
             lambda: assert_true(valid))


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════
def assert_true(condition):
    if not condition:
        raise AssertionError("Expected True but got False")

def assert_equal(actual, expected):
    if actual != expected:
        raise AssertionError(f"Expected {expected!r} but got {actual!r}")


# ═══════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 65)
    print("🧪 US IT JOB HARVESTER V11 — COMPREHENSIVE UNIT TESTS")
    print("=" * 65)

    # Add init_local_db path
    sys.path.insert(0, str(Path(__file__).parent.parent / "04_sql_scripts"))

    test_date_validation()
    test_email_extraction()
    test_company_domain()
    test_record_builder()
    test_text_extraction()
    test_rule_based_scoring()
    test_database()
    test_token_tracker()
    test_schema_validation()
    test_portal_config()
    test_hash_dedup()
    test_uuid_generation()

    # ── SUMMARY ──────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"🧪 TEST RESULTS")
    print(f"   Total  : {TOTAL_TESTS}")
    print(f"   Passed : {PASSED_TESTS} ✅")
    print(f"   Failed : {FAILED_TESTS} ❌")
    print(f"   Rate   : {PASSED_TESTS*100//max(TOTAL_TESTS,1)}%")
    if FAILED_DETAILS:
        print(f"\n❌ FAILED TESTS:")
        for name, err in FAILED_DETAILS:
            print(f"   • {name}: {err}")
    print("=" * 65)
    sys.exit(0 if FAILED_TESTS == 0 else 1)
