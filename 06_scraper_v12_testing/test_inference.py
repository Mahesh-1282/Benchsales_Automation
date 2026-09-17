import requests, os
import sys
sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import CONFIG
api_key = CONFIG["nvidia_api_key"]

models_to_test = [
    "meta/llama2-70b", 
    "google/gemma-4-31b-it", 
    "mistralai/mixtral-8x22b-v0.1", 
    "nvidia/llama-3.1-nemotron-70b-instruct"
]

for model in models_to_test:
    print(f"\nTesting {model}...")
    resp = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Hello!"}],
            "max_tokens": 10,
        }
    )
    if resp.status_code == 200:
        print("✅ SUCCESS")
        # We only need one good model.
    else:
        print(f"❌ FAIL: {resp.status_code} - {resp.text[:100]}")
