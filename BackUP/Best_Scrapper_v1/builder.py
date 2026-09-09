import re

def build_final():
    with open('final_version.py', 'r') as f:
        content = f.read()
    
    # 1. Add stealth_sync import
    content = content.replace(
        "from urllib.parse import urlparse, urljoin, quote_plus",
        "from urllib.parse import urlparse, urljoin, quote_plus\nfrom playwright_stealth import stealth_sync"
    )

    # 2. Update CSV headers
    content = content.replace(
        '"posted_date", "job_description", "description_length",',
        '"posted_date", "job_description", "description_length",\n    "roles_responsibilities", "requirements_section", "roles_summary",'
    )

    # 3. Add Regex extractors & ai_rescore just before fetch_job_detail
    extractors = """
# ── Text extractors ───────────────────────────────────────────
def extract_roles(text: str) -> str:
    patterns = [
        r"(?:key\s+)?responsibilities[:\s]*\\n(.*?)(?=\\n(?:requirements|qualifications|skills|benefits|about|who you|experience|education)|$)",
        r"(?:what you(?:'ll)? do|your role|day.to.day|in this role)[:\s]*\\n(.*?)(?=\\n(?:requirements|qualifications|skills|benefits|about)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 100: return s[:2000]
    return ""

def extract_requirements(text: str) -> str:
    patterns = [
        r"(?:requirements|qualifications|must have|required skills|what you(?:'ll)? need)[:\s]*\\n(.*?)(?=\\n(?:benefits|about|what we|nice to have|preferred|compensation)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 100: return s[:2000]
    return ""

def extract_salary(text: str) -> str:
    patterns = [
        r"\\$[\d,]+(?:\s*[-–]\s*\\$[\d,]+)?\s*(?:per\s+(?:year|annum|yr|month|hour)|\/(?:yr|year|hr|hour))",
        r"(?:salary|compensation)[:\s]+\\$[\d,]+(?:\s*[-–]\s*\\$[\d,]+)?",
        r"\\$[\d]+[Kk](?:\s*[-–]\s*\\$[\d]+[Kk])?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m: return m.group().strip()[:80]
    return ""

def extract_experience(text: str) -> str:
    patterns = [
        r"(\d+\+?\s*(?:to|-)\s*\d+\+?)\s+years?\s+(?:of\s+)?experience",
        r"(\d+\+?)\s+years?\s+(?:of\s+)?experience",
        r"minimum\s+(\d+\+?)\s+years?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m: return m.group().strip()[:60]
    return ""

def ai_rescore(job: dict) -> dict:
    desc = (job.get("job_description") or "")[:3000]
    title = job.get("job_title", "")
    company = job.get("company_name", "")
    location = job.get("location", "")

    if len(desc) < 50:
        return {
            "validation_score": 60, "validation_status": "Partial",
            "ai_summary": "No description available", "roles_summary": "",
            "tech_stack": job.get("tech_stack",""), "experience_years": "Not specified",
            "remote_type": "Remote" if "remote" in (title+location).lower() else "Not specified",
            "visa_sponsorship": False,
        }

    prompt = f\"\"\"Analyze this US IT job posting. Respond ONLY with valid JSON.

Title: {title}
Company: {company}
Location: {location}
Description:
{desc}

JSON format:
{{
  "score": <0-100 integer, relevance for US IT job seeker>,
  "is_real_job": <true/false>,
  "summary": "<2 sentence summary>",
  "roles_summary": "<3-5 bullet key responsibilities>",
  "tech_stack": "<top 8 skills comma-separated>",
  "experience_years": "<e.g. '5+ years' or 'Not specified'>",
  "remote_type": "<Remote|Hybrid|Onsite|Not specified>",
  "salary_mentioned": "<salary string or empty>",
  "visa_sponsorship": <true/false>
}}\"\"\"
    api_key = CONFIG["nvidia_api_key"]
    model = CONFIG["nvidia_model"]

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1, "max_tokens": 500},
                timeout=20,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                m = re.search(r'\{.*\}', content, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    score = int(data.get("score", 60))
                    return {
                        "validation_score": score,
                        "validation_status": "Valid" if score >= 70 else "Partial" if score >= 40 else "Junk",
                        "ai_summary": data.get("summary", ""),
                        "roles_summary": data.get("roles_summary", ""),
                        "tech_stack": data.get("tech_stack", ""),
                        "experience_years": data.get("experience_years", "Not specified"),
                        "remote_type": data.get("remote_type", "Not specified"),
                        "salary_mentioned": data.get("salary_mentioned", ""),
                        "visa_sponsorship": bool(data.get("visa_sponsorship", False)),
                    }
            elif resp.status_code == 429:
                time.sleep(5)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.debug(f"AI error: {e}")
            if attempt < 2: time.sleep(random.uniform(2, 4))

    return {
        "validation_score": 60, "validation_status": "Partial",
        "ai_summary": "AI unavailable", "roles_summary": "",
        "tech_stack": job.get("tech_stack",""), "experience_years": "Not specified",
        "remote_type": "Not specified", "visa_sponsorship": False,
    }

# ============================================================
# 🔍  JOB DETAIL FETCHER — The Big New Feature
# ============================================================"""
    content = content.replace(
        "# ============================================================\n# 🔍  JOB DETAIL FETCHER — The Big New Feature\n# ============================================================",
        extractors
    )

    # 4. Update fetch_details_parallel to use stealth and be thread safe
    new_parallel = """def fetch_details_parallel(records: list, _browser=None) -> list:
    to_fetch = [r for r in records if r.get("validation_score", 0) >= CONFIG["detail_fetch_min_score"]]
    log.info(f"🔍 Fetching details for {len(to_fetch)}/{len(records)} jobs (score >= {CONFIG['detail_fetch_min_score']})...")

    hash_to_record = {r["job_hash"]: r for r in records}
    completed = 0

    def fetch_one(rec):
        from playwright.sync_api import sync_playwright
        detail = {
            "job_description": "",
            "roles_responsibilities": "",
            "requirements_section": "",
            "salary_range": "",
            "experience_years": "",
            "detail_fetched": False,
            "hr_email": "",
            "company_website": "",
            "company_career_url": "",
            "easy_apply_link": ""
        }
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=CONFIG["headless"],
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-infobars", "--disable-dev-shm-usage"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                
                page = context.new_page()
                stealth_sync(page)
                
                # Apply human-like delays before fetching
                time.sleep(random.uniform(1.5, 3.5))
                
                page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())
                page.goto(rec["apply_link"], wait_until="domcontentloaded", timeout=CONFIG["detail_fetch_timeout_ms"])
                time.sleep(random.uniform(2.0, 4.0))

                html = page.content()
                desc = ""
                
                # Copying basic extraction logic from fetch_job_detail
                if "linkedin.com" in rec["apply_link"]:
                    desc_el = page.query_selector("div.description__text, div[class*='show-more-less-html']")
                    if desc_el: desc = desc_el.inner_text().strip()
                elif "indeed.com" in rec["apply_link"]:
                    desc_el = page.query_selector("div#jobDescriptionText, div[class*='jobsearch-JobComponent-description']")
                    if desc_el: desc = desc_el.inner_text().strip()
                    co_link = page.query_selector("a[data-testid='employer-website'], a[class*='companyLink']")
                    if co_link: detail["company_website"] = co_link.get_attribute("href") or ""
                elif "dice.com" in rec["apply_link"]:
                    desc_el = page.query_selector("div[data-testid='jobDescriptionHtml'], div[class*='job-description']")
                    if desc_el: desc = desc_el.inner_text().strip()
                
                if not desc or len(desc) < 100:
                    for sel in ["div[class*='description']", "div[class*='job-desc']", "section[class*='description']", "article", "main"]:
                        el = page.query_selector(sel)
                        if el:
                            candidate = el.inner_text().strip()
                            if len(candidate) > len(desc): desc = candidate
                            if len(desc) > 200: break
                            
                detail["job_description"] = desc[:4000] if desc else ""
                detail["roles_responsibilities"] = extract_roles(desc) if desc else ""
                detail["requirements_section"] = extract_requirements(desc) if desc else ""
                detail["salary_range"] = extract_salary(desc) if desc else ""
                detail["experience_years"] = extract_experience(desc) if desc else ""
                detail["detail_fetched"] = bool(detail["job_description"])
                
                emails = extract_emails(html)
                if emails: detail["hr_email"] = best_hr_email(emails)
                
                career_el = page.query_selector("a[href*='career'], a[href*='job']")
                if career_el:
                    career_url = career_el.get_attribute("href") or ""
                    if career_url and "http" in career_url:
                        detail["company_career_url"] = career_url
                
                context.close()
                browser.close()
        except Exception as e:
            log.debug(f"Parallel fetch error: {e}")
            
        return rec["job_hash"], detail

    for i in range(0, len(to_fetch), CONFIG["detail_fetch_workers"]):
        batch = to_fetch[i:i + CONFIG["detail_fetch_workers"]]
        with ThreadPoolExecutor(max_workers=CONFIG["detail_fetch_workers"]) as executor:
            futures = {executor.submit(fetch_one, rec): rec for rec in batch}
            for future in as_completed(futures):
                try:
                    job_hash, detail = future.result(timeout=60)
                    if job_hash in hash_to_record:
                        hash_to_record[job_hash].update(detail)
                        desc = detail.get("job_description", "")
                        hash_to_record[job_hash]["description_length"] = len(desc.split())
                        completed += 1
                except Exception as e:
                    log.debug(f"Future error: {e}")

        if (i // CONFIG["detail_fetch_workers"]) % 5 == 0:
            log.info(f"   Detail fetch: {completed}/{len(to_fetch)} done...")

    log.info(f"  ✅ Detail fetch complete: {completed}/{len(to_fetch)} pages fetched")
    return list(hash_to_record.values())"""

    # Using regex to replace the old fetch_details_parallel
    content = re.sub(r'def fetch_details_parallel\(records: list, browser\) -> list:.*?return list\(hash_to_record\.values\(\)\)', new_parallel, content, flags=re.DOTALL)

    # 5. Update Phase 4 Re-Scoring
    new_phase4 = """        # ── PHASE 4: Re-score with full description ──────────
        log.info("\\n═══ PHASE 4: RE-SCORE WITH FULL DESCRIPTIONS ═══")
        fetched_with_desc = [r for r in quality if r.get("detail_fetched")]
        log.info(f"🔄 Re-scoring {len(fetched_with_desc)} jobs with full descriptions...")
        for i, rec in enumerate(fetched_with_desc):
            if rec.get("description_length", 0) > 100:
                ai = ai_rescore(rec)
                rec["validation_score"] = ai["validation_score"]
                rec["validation_status"] = ai["validation_status"]
                rec["ai_summary"] = ai.get("ai_summary", "")
                rec["roles_summary"] = ai.get("roles_summary", "")
                rec["remote_type"] = ai.get("remote_type", "")
                rec["visa_sponsorship"] = str(ai.get("visa_sponsorship", False))
                
                if ai.get("tech_stack"): 
                    rec["tech_stack"] = ai["tech_stack"]
                if ai.get("experience_years") and ai["experience_years"] != "Not specified":
                    rec["experience_years"] = ai["experience_years"]
                if ai.get("salary_mentioned") and not rec.get("salary_range", "").strip():
                    rec["salary_range"] = ai["salary_mentioned"]

            if (i + 1) % 10 == 0:
                log.info(f"   Re-scored {i+1}/{len(fetched_with_desc)}...")"""

    content = re.sub(r'        # ── PHASE 4: Re-score with full description ──────────.*?log\.info\(f"   Re-scored {i\+1}/{len\(fetched_with_desc\)}\.\.\."\)', new_phase4, content, flags=re.DOTALL)

    with open('final_version.py', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    build_final()
