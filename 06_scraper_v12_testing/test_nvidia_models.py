import requests, os
import sys
sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import CONFIG
api_key = CONFIG["nvidia_api_key"]

resp = requests.get(
    "https://integrate.api.nvidia.com/v1/models",
    headers={"Authorization": f"Bearer {api_key}"}
)
if resp.status_code == 200:
    for m in resp.json()["data"]:
        print(m["id"])
