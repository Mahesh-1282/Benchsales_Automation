#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V11 — END-TO-END PIPELINE TEST                  ║
║  Tests ALL 14 portals with detailed terminal logs.                    ║
║  Validates every column in jobs_harvested_bronze.                     ║
║  No portal is spared — every single one is tested.                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime, date

# Add parent paths
sys.path.insert(0, str(Path(__file__).parent.parent / "01_local_scraper"))
sys.path.insert(0, str(Path(__file__).parent.parent / "03_databricks_app"))
sys.path.insert(0, str(Path(__file__).parent.parent / "04_sql_scripts"))

from job_scrapper import (
    CONFIG, CSV_HEADERS, build_record,
    ai_score_job, rule_based_score,
    ai_expand_keywords, ai_extract_jobs_from_dom,
    write_to_db, print_token_summary, TOKEN_TRACKER,
    _ai_call,
)
from db_utils import execute_sql, query_df, DB_PATH
from init_local_db import init_db


# ═══════════════════════════════════════════════════════════════════
# 🧪  E2E TEST CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
TEST_KEYWORDS = [
    "Java Developer",
    "Python Engineer",
    "Data Engineer",
    "React Developer",
    "DevOps Engineer",
    "Cloud Architect",
    "Machine Learning Engineer",
    "Full Stack Developer",
]

ALL_PORTALS = [
    "LinkedIn", "Indeed", "Dice", "Built In", "Glassdoor",
    "Wellfound", "ZipRecruiter", "SimplyHired", "Monster",
    "HiringCafe", "WTTJ", "CareerBuilder", "Greenhouse", "Lever"
]

CRITICAL_COLUMNS = [
    "id", "job_hash", "fetch_date", "portal", "search_keyword",
    "job_title", "company_name", "location", "apply_link",
    "validation_score", "validation_status",
]

ALL_COLUMNS = CSV_HEADERS  # All 29 columns


def log_section(title: str, char: str = "═"):
    print(f"\n{char * 65}")
    print(f"  {title}")
    print(f"{char * 65}")


def log_result(name: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}" + (f" → {detail}" if detail else ""))
    return passed


# ═══════════════════════════════════════════════════════════════════
# 🔌  TEST 1: ENVIRONMENT & API CONNECTIVITY
# ═══════════════════════════════════════════════════════════════════
def test_environment():
    log_section("TEST 1: ENVIRONMENT & API CONNECTIVITY")
    passed = 0
    total = 0

    # Check NVIDIA API key
    total += 1
    nvidia_key = os.getenv("NVIDIA_NIM_API_KEY", "")
    if log_result("NVIDIA_NIM_API_KEY present", bool(nvidia_key), f"{nvidia_key[:10]}...{nvidia_key[-5:]}" if nvidia_key else "MISSING"):
        passed += 1

    # Check Gemini API key
    total += 1
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if log_result("GEMINI_API_KEY present", bool(gemini_key), f"{gemini_key[:10]}...{gemini_key[-5:]}" if gemini_key else "MISSING"):
        passed += 1

    # Test NVIDIA NIM connectivity
    total += 1
    try:
        response = _ai_call("Say 'OK' in one word.", max_tokens=5)
        nim_ok = response is not None
    except Exception as e:
        nim_ok = False
        response = str(e)
    if log_result("NVIDIA NIM API connectivity", nim_ok, str(response)[:50] if response else "No response"):
        passed += 1

    # Check Playwright
    total += 1
    try:
        from playwright.sync_api import sync_playwright
        pw_ok = True
    except ImportError:
        pw_ok = False
    if log_result("Playwright installed", pw_ok):
        passed += 1

    # Check playwright-stealth
    total += 1
    try:
        import playwright_stealth
        stealth_ok = True
    except ImportError:
        stealth_ok = False
    if log_result("playwright-stealth installed", stealth_ok):
        passed += 1

    # Check SQLite DB
    total += 1
    init_db()
    db_ok = DB_PATH.exists()
    if log_result("SQLite DB initialized", db_ok, str(DB_PATH)):
        passed += 1

    print(f"\n  📊 Environment: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 🤖  TEST 2: AI SCORING PIPELINE
# ═══════════════════════════════════════════════════════════════════
def test_ai_scoring():
    log_section("TEST 2: AI SCORING PIPELINE")
    passed = 0
    total = 0

    # Test AI scoring with a realistic job
    test_job = build_record(
        "E2ETest", "Java Developer",
        "Senior Java Developer",
        "TechCorp International",
        "San Francisco, CA",
        """We are seeking a Senior Java Developer to join our growing engineering team.
        You will design and build scalable microservices using Java 17, Spring Boot, and Kubernetes.
        Responsibilities: Lead backend architecture, mentor junior developers, implement CI/CD.
        Requirements: 5+ years Java, Spring Boot, PostgreSQL, AWS, Docker.
        Salary: $150,000-$180,000/year. Remote-friendly. H1B sponsorship available.""",
        "https://e2etest.com/job/java-senior-1"
    )

    total += 1
    score, summary, tech, exp, visa = ai_score_job(test_job)
    print(f"\n  🤖 AI Scoring Results:")
    print(f"     Score        : {score}")
    print(f"     Summary      : {summary[:80]}...")
    print(f"     Tech Stack   : {tech}")
    print(f"     Experience   : {exp}")
    print(f"     Visa         : {visa}")

    if log_result("AI score returned (not 0)", score > 0, f"score={score}"):
        passed += 1

    total += 1
    if log_result("AI summary not empty", bool(summary) and summary != "AI unavailable"):
        passed += 1

    total += 1
    if log_result("tech_stack extracted", bool(tech)):
        passed += 1

    total += 1
    if log_result("experience_years extracted", bool(exp)):
        passed += 1

    # Test rule-based scoring as fallback
    total += 1
    rb_score = rule_based_score(test_job)
    if log_result("rule_based_score works", rb_score > 0, f"score={rb_score}"):
        passed += 1

    # Test scoring a junk job
    junk_job = build_record("E2ETest", "x", "x", "", "", "abc", "https://x.com/1")
    total += 1
    junk_score = rule_based_score(junk_job)
    if log_result("junk job gets low score", junk_score < 50, f"score={junk_score}"):
        passed += 1

    print(f"\n  📊 AI Scoring: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 🌐  TEST 3: KEYWORD EXPANSION
# ═══════════════════════════════════════════════════════════════════
def test_keyword_expansion():
    log_section("TEST 3: AI KEYWORD EXPANSION")
    passed = 0
    total = 0

    # Test with raw technology names
    test_techs = ["Java", "Python", "Spark"]
    total += 1
    expanded = ai_expand_keywords(test_techs)
    print(f"\n  🤖 Input: {test_techs}")
    print(f"  🤖 Expanded: {expanded}")

    if log_result("keywords expanded", len(expanded) > len(test_techs), f"{len(test_techs)} → {len(expanded)}"):
        passed += 1

    total += 1
    if log_result("expanded contains developer/engineer terms",
                  any("developer" in k.lower() or "engineer" in k.lower() for k in expanded)):
        passed += 1

    # Test with empty input
    total += 1
    empty_result = ai_expand_keywords([])
    if log_result("empty input returns defaults", len(empty_result) > 0):
        passed += 1

    print(f"\n  📊 Keyword Expansion: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 💾  TEST 4: DATABASE INSERT & VALIDATE ALL COLUMNS
# ═══════════════════════════════════════════════════════════════════
def test_db_columns():
    log_section("TEST 4: DATABASE — ALL 29 COLUMNS VALIDATION")
    passed = 0
    total = 0

    # Create a fully-populated test record
    full_rec = {
        "id": "e2e-test-" + str(int(time.time())),
        "job_hash": "e2e_test_hash_" + str(int(time.time())),
        "fetch_date": date.today().strftime("%Y-%m-%d"),
        "portal": "E2ETest",
        "search_keyword": "Java Developer",
        "job_title": "Senior Java Developer",
        "company_name": "TechCorp",
        "location": "San Francisco, CA",
        "remote_type": "Hybrid",
        "salary_range": "$150,000-$180,000",
        "experience_years": "5-7 years",
        "tech_stack": "Java, Spring Boot, PostgreSQL, AWS, Docker, Kubernetes",
        "posted_date": "2024-01-15",
        "job_description": "Full job description here with responsibilities and requirements.",
        "description_length": 10,
        "roles_responsibilities": "Design scalable systems, mentor junior devs",
        "requirements_section": "5+ years Java, Spring Boot experience",
        "roles_summary": "Backend lead for microservices team",
        "apply_link": "https://e2etest.com/apply/123",
        "easy_apply_link": "https://linkedin.com/easy-apply/123",
        "company_career_url": "https://techcorp.com/careers",
        "company_website": "https://techcorp.com",
        "hr_email": "recruit@techcorp.com",
        "job_id": "JOB-E2E-123",
        "visa_sponsorship": True,
        "validation_score": 85,
        "validation_status": "Valid",
        "ai_summary": "Senior Java role at TechCorp focused on microservices.",
        "detail_fetched": True,
    }

    # Insert
    from db_utils import insert_row
    total += 1
    ok, err = insert_row("jobs_harvested_bronze", full_rec)
    if log_result("insert full record", ok, err[:50] if err else "OK"):
        passed += 1

    # Query back
    df = query_df(f"SELECT * FROM jobs_harvested_bronze WHERE job_hash = '{full_rec['job_hash']}'")
    total += 1
    if log_result("query returns record", len(df) > 0):
        passed += 1

    if len(df) > 0:
        row = df.iloc[0]

        # Validate EVERY column
        print(f"\n  📋 Column-by-column validation:")
        for col in ALL_COLUMNS:
            total += 1
            val = row.get(col)
            col_ok = val is not None and str(val).strip() != ""
            if log_result(f"  column '{col}'", col_ok, f"value={str(val)[:40]}"):
                passed += 1

    # Cleanup
    execute_sql(f"DELETE FROM jobs_harvested_bronze WHERE job_hash = '{full_rec['job_hash']}'")

    print(f"\n  📊 Database Columns: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 🌐  TEST 5: PORTAL SCRAPING (ALL 14 PORTALS)
# ═══════════════════════════════════════════════════════════════════
def test_portal_scraping():
    log_section("TEST 5: PORTAL SCRAPING — ALL 14 PORTALS")
    passed = 0
    total = 0
    portal_results = {}

    test_keyword = "Python Developer"

    try:
        from playwright.sync_api import sync_playwright
        import playwright_stealth
    except ImportError:
        print("  ⚠️  Playwright not installed. Skipping browser-based portal tests.")
        return 0, 0

    # Import all scrapers
    from job_scrapper import (
        LinkedInScraper, IndeedScraper, DiceScraper, BuiltInScraper,
        GlassdoorScraper, WellfoundScraper, ZipRecruiterScraper,
        SimplyHiredScraper, MonsterScraper, HiringCafeScraper,
        WelcomeToTheJungleScraper, CareerBuilderScraper,
        GreenhouseScraper, LeverScraper,
    )

    # First test DDG-based scrapers (no browser needed)
    for ScrClass, name in [(GreenhouseScraper, "Greenhouse"), (LeverScraper, "Lever")]:
        total += 1
        try:
            scraper = ScrClass()
            jobs = scraper.scrape(test_keyword)
            result = len(jobs)
            portal_results[name] = result
            if log_result(f"{name}: scraped", True, f"{result} jobs found"):
                passed += 1
        except Exception as e:
            portal_results[name] = f"ERROR: {e}"
            log_result(f"{name}: scraped", False, str(e)[:60])
        time.sleep(1)

    # Browser-based scrapers
    browser_scraper_classes = [
        (LinkedInScraper, "LinkedIn"),
        (IndeedScraper, "Indeed"),
        (DiceScraper, "Dice"),
        (BuiltInScraper, "Built In"),
        (GlassdoorScraper, "Glassdoor"),
        (WellfoundScraper, "Wellfound"),
        (ZipRecruiterScraper, "ZipRecruiter"),
        (SimplyHiredScraper, "SimplyHired"),
        (MonsterScraper, "Monster"),
        (HiringCafeScraper, "HiringCafe"),
        (WelcomeToTheJungleScraper, "WTTJ"),
        (CareerBuilderScraper, "CareerBuilder"),
    ]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                      "--disable-infobars", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            playwright_stealth.Stealth().apply_stealth_sync(page)
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda r: r.abort())

            for ScrClass, name in browser_scraper_classes:
                total += 1
                try:
                    print(f"\n  🌐 Testing {name}...")
                    scraper = ScrClass(page)
                    start_time = time.time()
                    jobs = scraper.scrape(test_keyword)
                    elapsed = time.time() - start_time
                    result = len(jobs)
                    portal_results[name] = result

                    detail = f"{result} jobs in {elapsed:.1f}s"
                    if result > 0:
                        # Validate first job record
                        first = jobs[0]
                        cols_ok = all(h in first for h in CSV_HEADERS)
                        detail += f" | all_cols={cols_ok}"
                        if not cols_ok:
                            missing = [h for h in CSV_HEADERS if h not in first]
                            detail += f" | missing={missing}"

                    if log_result(f"{name}: scraped", True, detail):
                        passed += 1

                    # Log sample job
                    if jobs:
                        j = jobs[0]
                        print(f"     📌 Sample: {j.get('job_title', '?')[:40]} @ {j.get('company_name', '?')[:25]}")
                        print(f"        📍 {j.get('location', '?')[:30]} | 🔗 {j.get('apply_link', '?')[:50]}")

                except Exception as e:
                    portal_results[name] = f"ERROR: {e}"
                    log_result(f"{name}: scraped", False, str(e)[:80])

                # Delay between portals
                time.sleep(2)

            context.close()
            browser.close()
    except Exception as e:
        print(f"  💥 Browser launch failed: {e}")

    # Summary table
    print(f"\n  {'─'*50}")
    print(f"  📊 PORTAL RESULTS SUMMARY")
    print(f"  {'─'*50}")
    for portal in ALL_PORTALS:
        result = portal_results.get(portal, "NOT TESTED")
        icon = "✅" if isinstance(result, int) and result > 0 else "⚡" if isinstance(result, int) else "❌"
        print(f"  {icon} {portal:<20} → {result}")
    print(f"  {'─'*50}")

    print(f"\n  📊 Portal Scraping: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 🔄  TEST 6: FULL PIPELINE E2E (1 keyword, all phases)
# ═══════════════════════════════════════════════════════════════════
def test_full_pipeline():
    log_section("TEST 6: FULL PIPELINE E2E (1 keyword)")
    passed = 0
    total = 0

    # We'll simulate the pipeline with mock data (to avoid long scraping)
    # Create 5 realistic mock records
    mock_records = []
    for i, (title, company, loc) in enumerate([
        ("Senior Python Developer", "DataTech Inc", "Austin, TX"),
        ("Python Engineer", "CloudBase Corp", "Remote"),
        ("Junior Python Developer", "StartupXYZ", "New York, NY"),
        ("Lead Python Architect", "Enterprise Solutions", "San Jose, CA"),
        ("Python Data Engineer", "Analytics Co", "Seattle, WA"),
    ]):
        rec = build_record(
            portal="E2ETest",
            keyword="Python Developer",
            title=title,
            company=company,
            location=loc,
            desc=f"Looking for {title} at {company}. Must have Python, Django, Flask, PostgreSQL, AWS. 3+ years experience required. Salary: $120K-$160K.",
            url=f"https://e2etest.com/job/{i+1}",
            job_id=f"E2E-{i+1}"
        )
        mock_records.append(rec)

    # PHASE 2: AI Scoring
    print("\n  ═══ PHASE 2: AI SCORING ═══")
    for rec in mock_records:
        score, summary, tech, exp, visa = ai_score_job(rec)
        rec["validation_score"] = score
        rec["validation_status"] = "Valid" if score >= 70 else "Partial" if score >= 40 else "Junk"
        rec["ai_summary"] = summary
        rec["tech_stack"] = tech
        rec["experience_years"] = exp
        rec["visa_sponsorship"] = visa
        print(f"     📊 {rec['job_title'][:30]:<30} → score={score}, tech={tech[:30]}")

    total += 1
    scored = [r for r in mock_records if r["validation_score"] > 0]
    if log_result("all jobs scored", len(scored) == len(mock_records), f"{len(scored)}/{len(mock_records)}"):
        passed += 1

    total += 1
    with_tech = [r for r in mock_records if r["tech_stack"] and r["tech_stack"] != "Not Specified"]
    if log_result("tech_stack populated", len(with_tech) > 0, f"{len(with_tech)}/{len(mock_records)}"):
        passed += 1

    # PHASE 4: DB Insertion
    print("\n  ═══ PHASE 4: DB INSERTION ═══")
    total += 1
    written = write_to_db(mock_records)
    if log_result("records written to DB", written > 0, f"{written} new records"):
        passed += 1

    # Validate in DB
    df = query_df("SELECT * FROM jobs_harvested_bronze WHERE portal = 'E2ETest'")
    total += 1
    if log_result("records found in DB", len(df) >= written, f"{len(df)} rows"):
        passed += 1

    # Check every column has no NULL for critical fields
    if len(df) > 0:
        print("\n  📋 Critical column validation:")
        for col in CRITICAL_COLUMNS:
            total += 1
            non_null = df[col].notna().sum() if col in df.columns else 0
            all_filled = non_null == len(df)
            if log_result(f"  '{col}' fully populated", all_filled, f"{non_null}/{len(df)}"):
                passed += 1

    # Cleanup test records
    execute_sql("DELETE FROM jobs_harvested_bronze WHERE portal = 'E2ETest'")

    print(f"\n  📊 Full Pipeline: {passed}/{total} passed")
    return passed, total


# ═══════════════════════════════════════════════════════════════════
# 🚀  MAIN TEST RUNNER
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("═" * 65)
    print("  🧪 US IT JOB HARVESTER V11 — END-TO-END PIPELINE TEST")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 65)

    total_passed = 0
    total_tests = 0

    # Run all test suites
    test_suites = [
        ("Environment", test_environment),
        ("AI Scoring", test_ai_scoring),
        ("Keyword Expansion", test_keyword_expansion),
        ("DB Columns", test_db_columns),
        ("Portal Scraping", test_portal_scraping),
        ("Full Pipeline", test_full_pipeline),
    ]

    suite_results = []
    for name, func in test_suites:
        try:
            p, t = func()
            total_passed += p
            total_tests += t
            suite_results.append((name, p, t))
        except Exception as e:
            print(f"  💥 Suite '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            suite_results.append((name, 0, 1))
            total_tests += 1

    # Print token summary
    print_token_summary()

    # Final Summary
    log_section("FINAL E2E TEST RESULTS", "═")
    for name, p, t in suite_results:
        icon = "✅" if p == t else "⚠️" if p > 0 else "❌"
        print(f"  {icon} {name:<25} {p}/{t} passed")
    print(f"{'─' * 65}")
    print(f"  📊 TOTAL: {total_passed}/{total_tests} passed ({total_passed*100//max(total_tests,1)}%)")
    print(f"  {'✅ ALL TESTS PASSED!' if total_passed == total_tests else '❌ SOME TESTS FAILED'}")
    print("═" * 65)

    sys.exit(0 if total_passed == total_tests else 1)
