#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V11 — SCRAPER TEST NOTEBOOK                     ║
║                                                                      ║
║  Put random technologies below → AI generates keywords →             ║
║  Scraper runs automatically → Results inserted into                  ║
║  jobs_harvested_bronze table                                         ║
║                                                                      ║
║  Usage: python run_scraper_test.py                                   ║
║  Or:    python run_scraper_test.py Java Python Spark                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# 🎯  PUT YOUR TECHNOLOGIES HERE
# ═══════════════════════════════════════════════════════════════════
# These are raw technology/skill names.
# AI will automatically expand them into proper job search keywords.
# Example: "Java" → ["Java Developer", "Senior Java Engineer", "J2EE Developer"]

DEFAULT_TECHNOLOGIES = [
    "Java",
    "Python",
    "Data Engineer",
    "React",
    "DevOps",
    "Salesforce",
    "Azure",
    "Snowflake",
    "Databricks",
    ".NET",
    "Kubernetes",
    "Machine Learning",
]

# ═══════════════════════════════════════════════════════════════════
# 🔧  SETUP
# ═══════════════════════════════════════════════════════════════════
# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "01_local_scraper"))
sys.path.insert(0, str(Path(__file__).parent.parent / "03_databricks_app"))
sys.path.insert(0, str(Path(__file__).parent.parent / "04_sql_scripts"))

# Load .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / "01_local_scraper" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        print(f"  ✅ Loaded .env from {env_path}")
except ImportError:
    print("  ⚠️  python-dotenv not installed, using existing env vars")

# Initialize local DB
from init_local_db import init_db
init_db()
print("  ✅ SQLite DB initialized")


def main():
    print("═" * 70)
    print("  🚀 US IT JOB HARVESTER V11 — SCRAPER TEST NOTEBOOK")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 70)

    # Determine technologies from CLI args or defaults
    if len(sys.argv) > 1:
        technologies = sys.argv[1:]
        print(f"\n  📋 Using CLI technologies: {technologies}")
    else:
        technologies = DEFAULT_TECHNOLOGIES
        print(f"\n  📋 Using default technologies: {technologies}")

    # Import and run
    from job_scrapper import run_harvester_v10, print_token_summary, TOKEN_TRACKER
    from db_utils import query_df

    print(f"\n  🤖 Step 1: AI will expand {len(technologies)} technologies into search keywords...")
    print(f"  🌐 Step 2: Scraper will search ALL 14 portals per keyword...")
    print(f"  📊 Step 3: AI will score and validate all jobs...")
    print(f"  💾 Step 4: Results inserted into jobs_harvested_bronze...")
    print(f"\n  ⏱️  Starting pipeline...\n")

    start_time = time.time()

    # Run the full pipeline
    jobs = run_harvester_v10(keywords=technologies)

    elapsed = time.time() - start_time

    # Post-run validation
    print("\n" + "═" * 70)
    print("  📊 POST-RUN VALIDATION")
    print("═" * 70)

    # Query DB for all records
    df = query_df("SELECT * FROM jobs_harvested_bronze ORDER BY fetch_date DESC LIMIT 500")

    # Column-level validation
    print("\n  📋 Column Coverage Analysis:")
    print(f"  {'─'*55}")
    for col in [
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
    ]:
        if col in df.columns:
            non_empty = df[col].apply(lambda x: bool(x) and str(x).strip() not in ('', 'None', '0', 'False', 'Not Specified')).sum()
            pct = non_empty * 100 // max(len(df), 1)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            icon = "✅" if pct >= 80 else "⚡" if pct >= 30 else "❌"
            print(f"  {icon} {col:<25} {bar} {pct:>3}% ({non_empty}/{len(df)})")
        else:
            print(f"  ❌ {col:<25} {'░'*20} MISSING COLUMN!")

    # Portal distribution
    if "portal" in df.columns and len(df) > 0:
        print(f"\n  🌐 Jobs by Portal:")
        print(f"  {'─'*40}")
        portal_counts = df["portal"].value_counts()
        for portal, count in portal_counts.items():
            print(f"     {portal:<20} → {count}")

    # Keyword distribution
    if "search_keyword" in df.columns and len(df) > 0:
        print(f"\n  🔍 Jobs by Keyword:")
        print(f"  {'─'*40}")
        kw_counts = df["search_keyword"].value_counts().head(10)
        for kw, count in kw_counts.items():
            print(f"     {kw:<25} → {count}")

    # Score distribution
    if "validation_status" in df.columns and len(df) > 0:
        print(f"\n  📊 Validation Status:")
        print(f"  {'─'*40}")
        status_counts = df["validation_status"].value_counts()
        for status, count in status_counts.items():
            icon = "✅" if status == "Valid" else "⚠️" if status == "Partial" else "❌"
            print(f"     {icon} {status:<15} → {count}")

    # Final stats
    print(f"\n  {'═'*55}")
    print(f"  🎯 FINAL STATS")
    print(f"  {'═'*55}")
    print(f"  Total jobs harvested    : {len(jobs)}")
    print(f"  Total in DB             : {len(df)}")
    print(f"  With descriptions       : {sum(1 for j in jobs if j.get('description_length', 0) > 50)}")
    print(f"  With tech_stack         : {sum(1 for j in jobs if j.get('tech_stack') and j['tech_stack'] != 'Not Specified')}")
    print(f"  With HR email           : {sum(1 for j in jobs if j.get('hr_email'))}")
    print(f"  With salary             : {sum(1 for j in jobs if j.get('salary_range') and j['salary_range'] != 'Not Specified')}")
    print(f"  Pipeline elapsed        : {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Token summary
    print_token_summary()

    print(f"\n  {'═'*55}")
    print(f"  ✅ SCRAPER TEST COMPLETE!")
    print(f"  {'═'*55}")


if __name__ == "__main__":
    main()
