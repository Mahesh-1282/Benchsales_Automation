import sys
from pathlib import Path

# Add app to path
app_dir = Path("/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/03_databricks_app")
sys.path.insert(0, str(app_dir))

import dotenv
# Load .env explicitly to ensure NVIDIA_NIM_API_KEY is available
dotenv.load_dotenv(app_dir / ".env")

from pages.1_Onboarding import extract_text_from_pdf, ai_parse_resume
import json

resume_path = Path("/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/Sindhu Singamaneni Resume.pdf")
print("Reading file...")
file_bytes = resume_path.read_bytes()

print("Extracting text...")
raw_text = extract_text_from_pdf(file_bytes)
print(f"Extracted {len(raw_text)} chars.")

print("Parsing with AI...")
parsed = ai_parse_resume(raw_text)

print("Result:")
print(json.dumps(parsed, indent=2))

import os
import requests

url = "https://integrate.api.nvidia.com/v1/chat/completions"
headers = {"Authorization": f"Bearer {os.environ.get('NVIDIA_NIM_API_KEY')}", "Content-Type": "application/json"}
data = {
    "model": "meta/llama-3.1-70b-instruct",
    "messages": [{"role": "user", "content": "Just testing the API."}],
    "max_tokens": 10
}
resp = requests.post(url, headers=headers, json=data)
print(f"Test API call status: {resp.status_code}")
if resp.status_code != 200:
    print(resp.text)

