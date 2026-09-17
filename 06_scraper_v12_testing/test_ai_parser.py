import sys, os
sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import _ai_call
from dotenv import load_dotenv

load_dotenv("/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper/.env")
prompt = "Output exactly this JSON: {\"a\": 1, \"b\": 2}"
res = _ai_call(prompt, max_tokens=1000)
print("RAW_CONTENT:", repr(res))
