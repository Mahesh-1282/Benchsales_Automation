import sys, os, time
import pandas as pd
from tabulate import tabulate

sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import run_harvester_v10, CONFIG
from standalone_db import get_connection

print("\n🗑️  DELETING ALL DATA IN jobs_harvested_bronze...")
conn = get_connection()
conn.execute("DELETE FROM jobs_harvested_bronze")
conn.commit()

# Run fast pipeline: only Built In, only 1 keyword
CONFIG["enable_all_sites"] = False
# Mock AI expand to avoid 6 keyword iterations
import job_scrapper
job_scrapper.ai_expand_keywords = lambda k: ["Python Developer"]

# Disable other portals
def mock_scrape(*args, **kwargs): return []
job_scrapper.LinkedInScraper.scrape = mock_scrape
job_scrapper.IndeedScraper.scrape = mock_scrape
job_scrapper.DiceScraper.scrape = mock_scrape

print("\n🚀 STARTING THROTTLED HARVESTER PIPELINE (Target: 40 RPM)...")
start_time = time.time()
jobs = run_harvester_v10(["Python Developer"])
elapsed = time.time() - start_time
print(f"\n✅ Pipeline finished in {elapsed/60:.1f} minutes.")

print("\n📊 VALIDATING DB RECORDS IN jobs_harvested_bronze...")
df = pd.read_sql_query("SELECT * FROM jobs_harvested_bronze", conn)
total_records = len(df)
print(f"Total Records in DB: {total_records}")

if total_records == 0:
    print("❌ FAILED: No records found in the database!")
    sys.exit(1)

critical_columns = [
    "job_title", "company_name", "job_description", 
    "description_length", "tech_stack", "roles_responsibilities",
    "ai_summary", "validation_score"
]

validation_results = []
for col in critical_columns:
    if col not in df.columns:
        validation_results.append([col, "MISSING COLUMN", "0%"])
        continue
    
    valid_count = 0
    for val in df[col]:
        if pd.isna(val): continue
        val_str = str(val).strip()
        if not val_str or val_str.lower() in ["not specified", "none", "0"]: continue
        valid_count += 1
        
    pct = (valid_count / total_records) * 100
    status = "✅" if pct > 80 else "⚠️" if pct > 40 else "❌"
    validation_results.append([col, f"{valid_count}/{total_records}", f"{pct:.1f}%", status])

print("\n" + tabulate(validation_results, headers=["Column", "Populated", "Percent", "Status"], tablefmt="rounded_outline"))

print("\n📋 SAMPLE RECORDS:")
sample_df = df[["job_title", "description_length", "tech_stack", "ai_summary"]].head(2)
pd.set_option('display.max_columns', None)
print(sample_df)

print("\n✅ VALIDATION COMPLETE.")
