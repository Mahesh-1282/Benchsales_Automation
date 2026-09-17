import sys, os
sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import run_harvester_v10, CONFIG
from standalone_db import get_connection

# Clean DB to show fresh test
conn = get_connection()
conn.execute("DELETE FROM jobs_harvested_bronze WHERE portal = 'Built In'")
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

jobs = run_harvester_v10(["Python Developer"])

print("\n--- DB VALIDATION ---")
import pandas as pd
df = pd.read_sql_query("SELECT job_title, job_description, description_length, tech_stack, roles_responsibilities, hr_email FROM jobs_harvested_bronze WHERE portal = 'Built In'", conn)
print(df.head())
