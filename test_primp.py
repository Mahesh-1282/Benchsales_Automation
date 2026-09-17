import primp
client = primp.Client(impersonate="chrome_120")
response = client.get("https://www.dice.com/jobs?q=Python+Developer")
print("Status:", response.status_code)
print(response.text[:200])
