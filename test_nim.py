import requests
import json
api_key = "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"
model = "meta/llama-3.2-11b-vision-instruct"
prompt = "Return exactly this JSON: {\"hello\": \"world\"}"
resp = requests.post(
    "https://integrate.api.nvidia.com/v1/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 100,
    }
)
print(resp.status_code, resp.text[:200])
