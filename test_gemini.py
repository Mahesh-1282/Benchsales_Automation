import requests
api_key = "AIzaSyAl9_gGM_Kf_hIIMM2u0tpdbvygKpDX-r0"
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
resp = requests.post(url, json=payload, verify=False)
print(resp.status_code, resp.text[:200])
