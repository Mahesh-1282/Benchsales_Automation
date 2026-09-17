import os, requests
from dotenv import load_dotenv

load_dotenv("01_local_scraper/.env")
gemini_key = os.getenv("GEMINI_API_KEY")

# List Gemini Models
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
resp = requests.get(url)
if resp.status_code == 200:
    for m in resp.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print("GEMINI MODEL:", m["name"])
else:
    print("GEMINI ERROR:", resp.status_code, resp.text)

# List NVIDIA Models
api_key = os.getenv("NVIDIA_NIM_API_KEY")
resp = requests.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
if resp.status_code == 200:
    for m in resp.json().get("data", []):
        if "llama" in m["id"].lower():
            print("NVIDIA MODEL:", m["id"])
else:
    print("NVIDIA ERROR:", resp.status_code, resp.text)
