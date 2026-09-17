import requests
import json
api_key = "AIzaSyAl9_gGM_Kf_hIIMM2u0tpdbvygKpDX-r0"
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
prompt = "Return exactly this JSON: {\"hello\": \"world\"}"
payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "temperature": 0.1,
        "maxOutputTokens": 400,
    }
}
try:
    resp = requests.post(url, json=payload, verify=False)
    print(resp.status_code)
    print(resp.text[:200])
except Exception as e:
    print("Error", e)
