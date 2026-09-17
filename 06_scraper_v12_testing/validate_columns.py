#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  COLUMN VALIDATOR — jobs_harvested_bronze                            ║
║                                                                      ║
║  Validates ALL 29 columns against the Databricks DDL schema.         ║
║  Reports fill rate, data types, distributions.                       ║
║  Flags columns with < 50% fill rate.                                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from standalone_db import query_df, execute_sql, init_bronze_table, DB_PATH

# ═══════════════════════════════════════════════════════════════════
# 📋  EXPECTED SCHEMA (from Databricks DDL)
# ═══════════════════════════════════════════════════════════════════
EXPECTED_SCHEMA = {
    "id":                    {"type": "TEXT",    "nullable": False, "critical": True},
    "job_hash":              {"type": "TEXT",    "nullable": False, "critical": True},
    "fetch_date":            {"type": "DATE",    "nullable": False, "critical": True},
    "portal":                {"type": "TEXT",    "nullable": False, "critical": True},
    "search_keyword":        {"type": "TEXT",    "nullable": False, "critical": True},
    "job_title":             {"type": "TEXT",    "nullable": False, "critical": True},
    "company_name":          {"type": "TEXT",    "nullable": False, "critical": True},
    "location":              {"type": "TEXT",    "nullable": False, "critical": True},
    "remote_type":           {"type": "TEXT",    "nullable": True,  "critical": False},
    "salary_range":          {"type": "TEXT",    "nullable": True,  "critical": False},
    "experience_years":      {"type": "TEXT",    "nullable": True,  "critical": False},
    "tech_stack":            {"type": "TEXT",    "nullable": True,  "critical": False},
    "posted_date":           {"type": "TEXT",    "nullable": True,  "critical": False},
    "job_description":       {"type": "TEXT",    "nullable": True,  "critical": False},
    "description_length":    {"type": "INTEGER", "nullable": True,  "critical": False},
    "roles_responsibilities":{"type": "TEXT",    "nullable": True,  "critical": False},
    "requirements_section":  {"type": "TEXT",    "nullable": True,  "critical": False},
    "roles_summary":         {"type": "TEXT",    "nullable": True,  "critical": False},
    "apply_link":            {"type": "TEXT",    "nullable": False, "critical": True},
    "easy_apply_link":       {"type": "TEXT",    "nullable": True,  "critical": False},
    "company_career_url":    {"type": "TEXT",    "nullable": True,  "critical": False},
    "company_website":       {"type": "TEXT",    "nullable": True,  "critical": False},
    "hr_email":              {"type": "TEXT",    "nullable": True,  "critical": False},
    "job_id":                {"type": "TEXT",    "nullable": True,  "critical": False},
    "visa_sponsorship":      {"type": "BOOLEAN", "nullable": True,  "critical": False},
    "validation_score":      {"type": "INTEGER", "nullable": False, "critical": True},
    "validation_status":     {"type": "TEXT",    "nullable": False, "critical": True},
    "ai_summary":            {"type": "TEXT",    "nullable": True,  "critical": False},
    "detail_fetched":        {"type": "BOOLEAN", "nullable": True,  "critical": False},
}


def validate():
    print("═" * 70)
    print("  📊 COLUMN VALIDATOR — jobs_harvested_bronze")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📁 DB: {DB_PATH}")
    print("═" * 70)

    init_bronze_table()

    # Get row count
    df_count = query_df("SELECT COUNT(*) as cnt FROM jobs_harvested_bronze")
    total_rows = df_count.iloc[0]["cnt"] if not df_count.empty else 0
    print(f"\n  📊 Total rows: {total_rows}")

    if total_rows == 0:
        print("  ⚠️  No data! Run the scraper first.")
        return

    # Get all data
    df = query_df("SELECT * FROM jobs_harvested_bronze")

    # Check table columns match schema
    print(f"\n  📋 SCHEMA VALIDATION:")
    actual_cols = set(df.columns)
    expected_cols = set(EXPECTED_SCHEMA.keys())
    missing = expected_cols - actual_cols
    extra = actual_cols - expected_cols

    if missing:
        print(f"  ❌ Missing columns: {missing}")
    if extra:
        print(f"  ⚠️  Extra columns: {extra}")
    if not missing and not extra:
        print(f"  ✅ All 29 columns present!")

    # Detailed column analysis
    print(f"\n  📊 COLUMN FILL RATE ANALYSIS:")
    print(f"  {'Column':<28} {'Type':<10} {'Critical':>8} {'Filled':>8} {'Rate':>6} {'Status':>8}")
    print(f"  {'─' * 75}")

    issues = []
    for col, spec in EXPECTED_SCHEMA.items():
        if col not in df.columns:
            print(f"  ❌ {col:<28} {'MISSING':<10}")
            issues.append(f"MISSING: {col}")
            continue

        # Count non-null, non-empty values
        filled = 0
        for val in df[col]:
            if val is not None:
                s = str(val).strip()
                if s and s not in ("", "0", "False", "Not Specified", "Not specified", "N/A", "Unknown", "Pending"):
                    filled += 1

        rate = filled * 100 // total_rows
        is_critical = spec["critical"]
        expected_type = spec["type"]

        if rate >= 80:
            status = "✅ GOOD"
        elif rate >= 50:
            status = "⚠️ FAIR"
        elif rate > 0:
            status = "🟡 LOW"
        else:
            status = "❌ EMPTY"

        crit_str = "YES" if is_critical else "no"
        print(f"  {status[:2]} {col:<28} {expected_type:<10} {crit_str:>8} {filled:>7}/{total_rows} {rate:>5}%")

        if is_critical and rate < 80:
            issues.append(f"CRITICAL column '{col}' only {rate}% filled")
        elif rate < 50:
            issues.append(f"Column '{col}' only {rate}% filled")

    # Portal distribution
    print(f"\n  🌐 PORTAL DISTRIBUTION:")
    portal_df = query_df("SELECT portal, COUNT(*) as cnt FROM jobs_harvested_bronze GROUP BY portal ORDER BY cnt DESC")
    if not portal_df.empty:
        for _, row in portal_df.iterrows():
            print(f"     {row['portal']:<20} → {row['cnt']} jobs")

    # Validation status distribution
    print(f"\n  🎯 VALIDATION STATUS:")
    status_df = query_df("SELECT validation_status, COUNT(*) as cnt FROM jobs_harvested_bronze GROUP BY validation_status ORDER BY cnt DESC")
    if not status_df.empty:
        for _, row in status_df.iterrows():
            print(f"     {row['validation_status']:<20} → {row['cnt']}")

    # Score distribution
    print(f"\n  📊 SCORE DISTRIBUTION:")
    score_df = query_df("""
        SELECT 
            CASE 
                WHEN validation_score >= 80 THEN '80-100 (Excellent)'
                WHEN validation_score >= 60 THEN '60-79 (Good)'
                WHEN validation_score >= 40 THEN '40-59 (Partial)'
                ELSE '0-39 (Low)'
            END as score_range,
            COUNT(*) as cnt
        FROM jobs_harvested_bronze 
        GROUP BY score_range
        ORDER BY score_range DESC
    """)
    if not score_df.empty:
        for _, row in score_df.iterrows():
            print(f"     {row['score_range']:<25} → {row['cnt']}")

    # Issues summary
    if issues:
        print(f"\n  ❌ ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"     • {issue}")
    else:
        print(f"\n  ✅ ALL COLUMNS VALIDATED SUCCESSFULLY!")

    print("═" * 70)


if __name__ == "__main__":
    validate()
