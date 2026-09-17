import sys, os
sys.path.insert(0, "/Users/mahesh/Desktop/untitled folder/Benchsales_Automation/01_local_scraper")
from job_scrapper import _call_nvidia_nim

print("Testing NVIDIA NIM...")
prompt = "Analyze this job. Title: Python Developer. Is it a real job? Return JSON: {'score': 100, 'tech_stack': 'Python'}"
res = _call_nvidia_nim(prompt, model="nvidia/llama-3.1-nemotron-70b-instruct", max_tokens=100)
print(f"Result: {res}")
