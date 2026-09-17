import os
import requests
from dotenv import load_dotenv

load_dotenv("01_local_scraper/.env")
api_key = os.getenv("NVIDIA_NIM_API_KEY")
print("NVIDIA KEY:", api_key[:10] if api_key else None)

resp = requests.post(
    "https://integrate.api.nvidia.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": "meta/llama-3.1-8b-instruct",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10,
    }
)
print("NVIDIA STATUS:", resp.status_code)
print("NVIDIA TEXT:", resp.text)

gemini_key = os.getenv("GEMINI_API_KEY")
print("GEMINI KEY:", gemini_key[:10] if gemini_key else None)
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-8b:generateContent?key={gemini_key}"
resp2 = requests.post(
    url,
    headers={"Content-Type": "application/json"},
    json={
        "contents": [{"parts": [{"text": "Hello"}]}],
        "generationConfig": {"maxOutputTokens": 10}
    }
)
print("GEMINI STATUS:", resp2.status_code)
print("GEMINI TEXT:", resp2.text)
