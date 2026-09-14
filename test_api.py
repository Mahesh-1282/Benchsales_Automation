import os
import requests
import dotenv
from pathlib import Path
import json

app_dir = Path("/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/03_databricks_app")
dotenv.load_dotenv(app_dir / ".env")

api_key = os.environ.get('GEMINI_API_KEY')
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"

payload = {
    "contents": [{"parts": [{"text": "Return a JSON object with keys 'foo' and 'bar'."}]}],
    "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}
}
resp = requests.post(url, json=payload)
print(f"Gemini API status: {resp.status_code}")
if resp.status_code == 200:
    print(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
else:
    print(resp.text)
