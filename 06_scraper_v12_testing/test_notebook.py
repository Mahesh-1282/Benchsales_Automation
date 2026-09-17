#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V12 — TEST NOTEBOOK                            ║
║                                                                      ║
║  Interactive test with default parameters.                           ║
║  Pass raw keywords → AI expands → Scrape → Score → Insert DB        ║
║  Validates every column and prints results.                          ║
║                                                                      ║
║  Usage:                                                              ║
║    python test_notebook.py                                           ║
║    python test_notebook.py "Java" "Python" "React"                   ║
║    python test_notebook.py --quick                                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime, date

# ── Setup paths ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "01_local_scraper"))
sys.path.insert(0, str(Path(__file__).parent))

# Load .env
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / "01_local_scraper" / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    pass

from job_scrapper import (
    CONFIG, CSV_HEADERS, ai_expand_keywords,
    run_harvester_v10, print_token_summary, TOKEN_TRACKER,
    _ai_call,
)
from standalone_db import (
    execute_sql, query_df, init_bronze_table, DB_PATH,
)

# ═══════════════════════════════════════════════════════════════════
# 📋  DEFAULT PARAMETERS
# ═══════════════════════════════════════════════════════════════════
DEFAULT_KEYWORDS = ["Java", "Python", "Data Engineer"]
QUICK_KEYWORDS = ["Python Developer"]  # For --quick mode

# ═══════════════════════════════════════════════════════════════════
# 🎯  STEP 1: DETERMINE KEYWORDS
# ═══════════════════════════════════════════════════════════════════
def step1_determine_keywords(user_args):
    print("\n" + "═" * 65)
    print("  STEP 1: KEYWORD DETERMINATION")
    print("═" * 65)
    
    if user_args and user_args[0] != "--quick":
        raw_keywords = user_args
        print(f"  📥 User provided keywords: {raw_keywords}")
    elif user_args and user_args[0] == "--quick":
        raw_keywords = QUICK_KEYWORDS
        print(f"  ⚡ Quick mode: {raw_keywords}")
    else:
        raw_keywords = DEFAULT_KEYWORDS
        print(f"  📥 Using default keywords: {raw_keywords}")
    
    # Ask AI to generate the best search terms
    print(f"\n  🤖 Asking AI to expand '{raw_keywords}' into US IT job search terms...")
    
    # Custom prompt for best results
    prompt = f"""You are an expert US IT job recruiter and web scraper. 
Given these technology/skill keywords: {', '.join(raw_keywords)}

Generate the most popular and effective job search terms that companies in the US actually use when posting jobs.
Think like a human searching for jobs on LinkedIn, Indeed, and Dice.

For each technology, create 2-3 specific job titles. Include:
- Standard titles (e.g., "Java Developer", "Python Engineer")  
- Senior/Lead variants (e.g., "Senior Java Developer")
- Specialized titles (e.g., "PySpark Engineer", "React Native Developer")

Return ONLY a JSON list of strings. No explanation.
Example: ["Java Developer", "Senior Java Engineer", "Spring Boot Developer"]"""

    expanded = _ai_call(prompt, max_tokens=400)
    if expanded:
        try:
            import re
            m = re.search(r'\[.*\]', expanded, re.DOTALL)
            if m:
                keywords = json.loads(m.group())
                print(f"  ✅ AI expanded {len(raw_keywords)} inputs → {len(keywords)} search keywords:")
                for i, kw in enumerate(keywords, 1):
                    print(f"     {i:2d}. {kw}")
                return keywords
        except Exception as e:
            print(f"  ⚠️  AI expansion parse error: {e}")
    
    # Fallback
    fallback = ai_expand_keywords(raw_keywords)
    print(f"  ⚠️  Using fallback expansion: {fallback}")
    return fallback


# ═══════════════════════════════════════════════════════════════════
# 🚀  STEP 2: RUN SCRAPER PIPELINE
# ═══════════════════════════════════════════════════════════════════
def step2_run_pipeline(keywords):
    print("\n" + "═" * 65)
    print("  STEP 2: RUNNING SCRAPER PIPELINE")
    print("═" * 65)
    print(f"  🔍 Keywords: {keywords}")
    print(f"  🌐 Portals: ALL 14 (LinkedIn, Indeed, Dice, Built In, Glassdoor,")
    print(f"              Wellfound, ZipRecruiter, SimplyHired, Monster,")
    print(f"              HiringCafe, WTTJ, CareerBuilder, Greenhouse, Lever)")
    print(f"  🤖 AI: NVIDIA NIM + Gemini Fallback")
    print(f"  ⏱️  Starting pipeline...\n")
    
    start_time = time.time()
    
    # Override CONFIG roles with our keywords
    CONFIG["roles"] = keywords
    CONFIG["enable_all_sites"] = True
    CONFIG["headless"] = True
    
    # Run the full harvester pipeline
    jobs = run_harvester_v10(keywords)
    
    elapsed = time.time() - start_time
    print(f"\n  ⏱️  Pipeline completed in {elapsed:.1f}s ({elapsed/60:.1f}m)")
    return jobs


# ═══════════════════════════════════════════════════════════════════
# 📊  STEP 3: VALIDATE & REPORT
# ═══════════════════════════════════════════════════════════════════
def step3_validate_and_report(jobs):
    print("\n" + "═" * 65)
    print("  STEP 3: VALIDATION & REPORTING")
    print("═" * 65)
    
    if not jobs:
        print("  ⚠️  No jobs returned from pipeline!")
        return
    
    print(f"\n  📊 Total jobs harvested: {len(jobs)}")
    
    # Column fill rate
    print(f"\n  📋 COLUMN FILL RATES ({len(jobs)} jobs):")
    print(f"  {'Column':<30} {'Filled':>8} {'Rate':>8}")
    print(f"  {'─' * 50}")
    
    for col in CSV_HEADERS:
        filled = sum(1 for j in jobs 
                     if j.get(col) is not None 
                     and str(j.get(col, "")).strip() 
                     and str(j.get(col, "")) not in ("0", "False", "Not Specified", ""))
        rate = filled * 100 // len(jobs)
        icon = "✅" if rate >= 50 else "⚠️" if rate > 0 else "❌"
        print(f"  {icon} {col:<28} {filled:>7}/{len(jobs)} {rate:>6}%")
    
    # Portal breakdown
    from collections import defaultdict
    by_portal = defaultdict(int)
    by_status = defaultdict(int)
    for j in jobs:
        by_portal[j.get("portal", "?")] += 1
        by_status[j.get("validation_status", "?")] += 1
    
    print(f"\n  🌐 JOBS BY PORTAL:")
    for p, c in sorted(by_portal.items(), key=lambda x: -x[1]):
        print(f"     {p:<20} → {c}")
    
    print(f"\n  🎯 VALIDATION STATUS:")
    for s, c in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"     {s:<20} → {c}")
    
    # Sample jobs
    print(f"\n  📋 SAMPLE JOBS (first 5 with descriptions):")
    shown = 0
    for j in jobs:
        if shown >= 5:
            break
        if j.get("description_length", 0) > 20:
            print(f"  {'─' * 60}")
            print(f"  🏢 {j['company_name'][:30]} | {j['portal']}")
            print(f"  📌 {j['job_title'][:50]}")
            print(f"  📍 {j.get('location', '')[:40]} | {j.get('remote_type', '')}")
            print(f"  💰 {j.get('salary_range', 'N/A')[:30]}")
            print(f"  🔧 {j.get('tech_stack', 'N/A')[:60]}")
            print(f"  📝 {j.get('ai_summary', '')[:100]}")
            print(f"  🔗 {j['apply_link'][:70]}")
            if j.get("hr_email"):
                print(f"  📧 {j['hr_email']}")
            shown += 1
    
    # DB validation
    print(f"\n  💾 DATABASE VALIDATION:")
    df = query_df("SELECT COUNT(*) as cnt FROM jobs_harvested_bronze")
    if not df.empty:
        print(f"     Total rows in jobs_harvested_bronze: {df.iloc[0]['cnt']}")
    
    df_today = query_df(f"SELECT COUNT(*) as cnt FROM jobs_harvested_bronze WHERE fetch_date = '{date.today().isoformat()}'")
    if not df_today.empty:
        print(f"     Today's rows: {df_today.iloc[0]['cnt']}")


# ═══════════════════════════════════════════════════════════════════
# 🔢  STEP 4: TOKEN REPORT
# ═══════════════════════════════════════════════════════════════════
def step4_token_report():
    print("\n" + "═" * 65)
    print("  STEP 4: AI TOKEN CONSUMPTION REPORT")
    print("═" * 65)
    
    t = TOKEN_TRACKER
    total_tokens = t["total_input_tokens"] + t["total_output_tokens"]
    
    print(f"  Total API Calls     : {t['total_api_calls']}")
    print(f"  Total Input Tokens  : {t['total_input_tokens']:,}")
    print(f"  Total Output Tokens : {t['total_output_tokens']:,}")
    print(f"  Total Tokens        : {total_tokens:,}")
    
    if t['tokens_per_job']:
        unique_jobs = len(set(j['job_hash'] for j in t['tokens_per_job']))
        avg = total_tokens / max(unique_jobs, 1)
        print(f"  Unique Jobs Scored  : {unique_jobs}")
        print(f"  Avg Tokens/Job      : {avg:,.0f}")
    
    print(f"\n  Model Breakdown:")
    for model, count in t['calls_by_model'].items():
        print(f"     {model}: {count} calls")


# ═══════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("═" * 65)
    print("  🧪 US IT JOB HARVESTER V12 — TEST NOTEBOOK")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🖥️  Standalone Desktop Mode")
    print("═" * 65)
    
    # Initialize DB
    init_bronze_table()
    
    # Get user keywords from CLI args
    user_args = sys.argv[1:]
    
    # Step 1: Determine keywords
    keywords = step1_determine_keywords(user_args)
    
    # Step 2: Run pipeline
    jobs = step2_run_pipeline(keywords)
    
    # Step 3: Validate & report
    step3_validate_and_report(jobs)
    
    # Step 4: Token report
    step4_token_report()
    
    print("\n" + "═" * 65)
    print(f"  🎉 NOTEBOOK COMPLETE!")
    print(f"  📁 Data in: {DB_PATH}")
    total = len(jobs) if jobs else 0
    desc_count = sum(1 for j in (jobs or []) if j.get("description_length", 0) > 50)
    email_count = sum(1 for j in (jobs or []) if j.get("hr_email"))
    print(f"  📊 {total} jobs | {desc_count} with descriptions | {email_count} with emails")
    print("═" * 65)
