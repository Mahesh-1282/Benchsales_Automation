"""
╔══════════════════════════════════════════════════════════════════════╗
║  JOB DETAIL ENRICHER — V10 RE-PROCESSOR                             ║
║  Reads existing CSV → visits every job URL → fetches FULL desc      ║
║  3 retries with human-like random delays (2-6 sec)                  ║
║  Re-scores ALL jobs with NVIDIA NIM using full description           ║
║  Extracts: description, roles, requirements, salary, email           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, csv, re, time, random, logging, json, requests, sys
from datetime import datetime, date
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import urlparse

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

# ── Config ────────────────────────────────────────────────────
INPUT_CSV  = sys.argv[1] if len(sys.argv) > 1 else "jobs_v10_output.csv"
OUTPUT_CSV = sys.argv[2] if len(sys.argv) > 2 else "jobs_enriched_output.csv"

NVIDIA_API_KEY = os.getenv("NVIDIA_NIM_API_KEY",
    "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")
NVIDIA_MODEL = "meta/llama-3.1-8b-instruct"

MAX_RETRIES       = 3
RETRY_MIN         = 2.0
RETRY_MAX         = 6.0
BETWEEN_MIN       = 1.5
BETWEEN_MAX       = 3.5

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("Enricher")

# ── Portal wait times (seconds for JS to render) ─────────────
PORTAL_WAIT = {
    "dice.com": 5, "linkedin.com": 4, "indeed.com": 3,
    "glassdoor.com": 4, "wellfound.com": 5, "builtin.com": 3,
    "simplyhired.com": 3, "ziprecruiter.com": 3,
    "monster.com": 3, "greenhouse.io": 2, "lever.co": 2,
}

# ── Verified selectors per portal ────────────────────────────
PORTAL_SELECTORS = {
    "dice.com": [
        "div[data-testid='jobDescriptionHtml']",
        "div[class*='description']",        # VERIFIED: 5193 chars
        "div[class*='job-description']",
        "section[class*='description']",
    ],
    "linkedin.com": [
        "div.description__text",
        "div[class*='show-more-less-html']",
        "div[class*='description__text']",
        "section[class*='description']",
    ],
    "indeed.com": [
        "div#jobDescriptionText",
        "div[class*='jobsearch-JobComponent-description']",
        "div[id*='jobDescription']",
        "div[class*='jobDescription']",
    ],
    "glassdoor.com": [
        "div[class*='JobDetails_jobDescription']",
        "div.jobDescriptionContent",
        "div[class*='job-description']",
        "div[class*='description']",
    ],
    "wellfound.com": [
        "div[class*='description']",
        "section[class*='job-description']",
        "div[class*='posting-body']",
    ],
    "builtin.com": [
        "div.job-description",
        "div[class*='job-description']",
        "div[class*='description']",
    ],
    "simplyhired.com": [
        "div[data-testid='VJ-section-description']",
        "div.viewjob-description",
        "div[class*='description']",
    ],
    "greenhouse.io": ["div#content", "div.job-post", "div[class*='description']"],
    "lever.co": ["div.content", "div[class*='posting-description']", "div[class*='description']"],
}

UNIVERSAL_FALLBACKS = [
    "div#jobDescription", "div.description",
    "div[class*='description']", "section[class*='description']",
    "div[class*='job-body']", "article", "main",
]

# ── Email extractor ───────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
EMAIL_BLACKLIST = {"example.com", "test.com", "noreply", "sentry.io",
                   "amazonaws.com", "cloudfront.net", "w3.org", "schema.org",
                   "intercom.io", "hubspot.com", "wixpress.com"}

def extract_best_email(html: str) -> str:
    emails = EMAIL_RE.findall(html)
    clean, seen = [], set()
    for e in emails:
        e = e.lower().strip(".,;")
        domain = e.split("@")[-1]
        if any(bl in domain for bl in EMAIL_BLACKLIST): continue
        if e not in seen:
            seen.add(e); clean.append(e)
    if not clean: return ""
    for prefix in ["recruit", "talent", "hr", "hiring", "jobs", "careers", "apply", "people"]:
        for e in clean:
            if prefix in e.split("@")[0]: return e
    return clean[0]

# ── Text extractors ───────────────────────────────────────────
def extract_roles(text: str) -> str:
    patterns = [
        r"(?:key\s+)?responsibilities[:\s]*\n(.*?)(?=\n(?:requirements|qualifications|skills|benefits|about|who you|experience|education)|$)",
        r"(?:what you(?:'ll)? do|your role|day.to.day|in this role)[:\s]*\n(.*?)(?=\n(?:requirements|qualifications|skills|benefits|about)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 100: return s[:2000]
    return ""

def extract_requirements(text: str) -> str:
    patterns = [
        r"(?:requirements|qualifications|must have|required skills|what you(?:'ll)? need)[:\s]*\n(.*?)(?=\n(?:benefits|about|what we|nice to have|preferred|compensation)|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 100: return s[:2000]
    return ""

def extract_salary(text: str) -> str:
    patterns = [
        r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?\s*(?:per\s+(?:year|annum|yr|month|hour)|\/(?:yr|year|hr|hour))",
        r"(?:salary|compensation)[:\s]+\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?",
        r"\$[\d]+[Kk](?:\s*[-–]\s*\$[\d]+[Kk])?",
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

# ── NVIDIA NIM re-scorer ──────────────────────────────────────
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

    prompt = f"""Analyze this US IT job posting. Respond ONLY with valid JSON.

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
}}"""

    for attempt in range(3):
        try:
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
                json={"model": NVIDIA_MODEL,
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

# ── Core detail fetcher with retries ─────────────────────────
def fetch_detail(page, url: str) -> dict:
    portal_key = next((k for k in PORTAL_SELECTORS if k in url), "default")
    wait_secs  = next((v for k, v in PORTAL_WAIT.items() if k in url), 4)
    selectors  = PORTAL_SELECTORS.get(portal_key, []) + UNIVERSAL_FALLBACKS

    empty = {"job_description": "", "hr_email": "", "salary_range": "",
             "experience_years": "", "roles_responsibilities": "",
             "requirements_section": "", "detail_fetched": False, "company_website": ""}

    for attempt in range(MAX_RETRIES):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(wait_secs)

            # Wait for meaningful content
            try:
                page.wait_for_selector(
                    "h1, div[class*='description'], article, div#jobDescriptionText",
                    timeout=8000)
            except:
                pass

            html = page.content()

            # Try portal selectors
            desc = ""
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        candidate = el.inner_text().strip()
                        if len(candidate) > len(desc) and len(candidate) > 80:
                            desc = candidate
                        if len(desc) > 500:
                            break
                except:
                    continue

            # Smart JS fallback — find longest job-like div
            if len(desc) < 100:
                try:
                    desc = page.evaluate("""() => {
                        let best = '';
                        for (let el of document.querySelectorAll('div,section,article')) {
                            const t = el.innerText || '';
                            if (t.length > best.length && t.length < 15000) {
                                const l = t.toLowerCase();
                                if (l.includes('responsib') || l.includes('qualif') ||
                                    l.includes('experience') || l.includes('skills') ||
                                    l.includes('requirement')) {
                                    best = t;
                                }
                            }
                        }
                        return best;
                    }""")
                except:
                    pass

            if len(desc) > 80:
                roles = extract_roles(desc)
                reqs  = extract_requirements(desc)
                sal   = extract_salary(desc)
                exp   = extract_experience(desc)
                email = extract_best_email(html)

                co_url = ""
                try:
                    co_el = page.query_selector(
                        "a[href*='careers'], a[data-testid='employer-website']")
                    if co_el:
                        co_url = co_el.get_attribute("href") or ""
                except:
                    pass

                return {
                    "job_description": desc[:5000],
                    "hr_email": email,
                    "salary_range": sal,
                    "experience_years": exp,
                    "roles_responsibilities": roles[:2000],
                    "requirements_section": reqs[:2000],
                    "detail_fetched": True,
                    "company_website": co_url,
                }

        except PlaywrightTimeout:
            log.debug(f"  Timeout attempt {attempt+1}")
        except Exception as e:
            log.debug(f"  Error attempt {attempt+1}: {e}")

        if attempt < MAX_RETRIES - 1:
            sleep_t = random.uniform(RETRY_MIN, RETRY_MAX)
            log.debug(f"  Retry sleep {sleep_t:.1f}s...")
            time.sleep(sleep_t)

    return empty

# ── Main ──────────────────────────────────────────────────────
def run():
    log.info("=" * 65)
    log.info("🔍 JOB DETAIL ENRICHER")
    log.info(f"📂 Input: {INPUT_CSV}  |  📁 Output: {OUTPUT_CSV}")
    log.info("=" * 65)

    if not os.path.exists(INPUT_CSV):
        log.error(f"Input not found: {INPUT_CSV}")
        sys.exit(1)

    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    log.info(f"📋 Loaded {len(rows)} jobs")

    # Ensure extra columns exist
    extra = ["roles_responsibilities", "requirements_section", "remote_type",
             "roles_summary", "company_website", "detail_fetched"]
    for col in extra:
        if col not in headers:
            headers.append(col)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,ico}", lambda r: r.abort())
        page = ctx.new_page()

        success, failed, emails = 0, 0, 0

        for i, row in enumerate(rows):
            url    = row.get("apply_link", "")
            title  = row.get("job_title", "?")[:45]
            portal = row.get("portal", "?")
            company= row.get("company_name", "?")[:25]

            if not url:
                continue

            # Skip if already done well
            already = str(row.get("detail_fetched","")).lower() == "true"
            dlen    = int(row.get("description_length", 0) or 0)
            if already and dlen > 100:
                log.info(f"[{i+1:3}/{len(rows)}] ⏭️  {portal:12} | {title}")
                success += 1
                continue

            log.info(f"[{i+1:3}/{len(rows)}] 🌐 {portal:12} | {title} | {company}")

            detail = fetch_detail(page, url)

            if detail["detail_fetched"]:
                desc = detail["job_description"]
                row["job_description"]       = desc
                row["description_length"]    = len(desc.split())
                row["detail_fetched"]        = "True"
                row["roles_responsibilities"]= detail.get("roles_responsibilities","")
                row["requirements_section"]  = detail.get("requirements_section","")
                row["company_website"]       = detail.get("company_website","")
                if detail.get("hr_email"):
                    row["hr_email"] = detail["hr_email"]
                    emails += 1
                if detail.get("salary_range") and not row.get("salary_range","").strip():
                    row["salary_range"] = detail["salary_range"]
                if detail.get("experience_years") and not row.get("experience_years","").strip():
                    row["experience_years"] = detail["experience_years"]

                # Re-score with full description
                log.info(f"         📝 {row['description_length']} words → AI scoring...")
                ai = ai_rescore(row)
                row["validation_score"]  = str(ai["validation_score"])
                row["validation_status"] = ai["validation_status"]
                row["ai_summary"]        = ai.get("ai_summary","") or ai.get("summary","")
                row["roles_summary"]     = ai.get("roles_summary","")
                row["remote_type"]       = ai.get("remote_type","")
                row["visa_sponsorship"]  = str(ai.get("visa_sponsorship",False))
                if ai.get("tech_stack"): row["tech_stack"] = ai["tech_stack"]
                if ai.get("experience_years","") not in ("Not specified",""):
                    row["experience_years"] = ai["experience_years"]
                if ai.get("salary_mentioned") and not row.get("salary_range","").strip():
                    row["salary_range"] = ai["salary_mentioned"]

                icon = {"Valid":"✅","Partial":"⚠️","Junk":"❌"}.get(row["validation_status"],"?")
                log.info(f"         {icon} {row['validation_score']}% {row['validation_status']} | {row.get('tech_stack','')[:55]}")
                if row.get("hr_email"):
                    log.info(f"         📧 {row['hr_email']}")
                success += 1
            else:
                row["detail_fetched"] = "False"
                cur = int(row.get("validation_score", 50) or 50)
                if cur < 50:
                    row["validation_score"] = "50"
                    row["validation_status"] = "Partial"
                log.warning(f"         ⚠️  Fetch failed (score kept at {row['validation_score']}%)")
                failed += 1

            time.sleep(random.uniform(BETWEEN_MIN, BETWEEN_MAX))

            # Save every 20 jobs
            if (i + 1) % 20 == 0:
                with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                    w.writeheader(); w.writerows(rows)
                log.info(f"  💾 Progress saved ({i+1}/{len(rows)})")

        page.close(); ctx.close(); browser.close()

    # Final write
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    # Summary
    valid   = sum(1 for r in rows if r.get("validation_status")=="Valid")
    partial = sum(1 for r in rows if r.get("validation_status")=="Partial")
    junk    = sum(1 for r in rows if r.get("validation_status")=="Junk")
    w_desc  = sum(1 for r in rows if int(r.get("description_length",0) or 0)>100)

    print("\n" + "="*65)
    print("  🎯 ENRICHMENT COMPLETE")
    print("="*65)
    print(f"  📋 Total:          {len(rows)}")
    print(f"  📝 With desc:      {w_desc} ({w_desc*100//max(len(rows),1)}%)")
    print(f"  📧 With email:     {emails}")
    print(f"  ✅ Valid (70%+):   {valid}")
    print(f"  ⚠️  Partial:       {partial}")
    print(f"  ❌ Junk:           {junk}")
    print(f"  🔴 Failed:         {failed}")
    print(f"  📁 CSV: {os.path.abspath(OUTPUT_CSV)}")
    print("="*65)

    # Show samples
    print("\n📋 SAMPLE ENRICHED JOBS:")
    shown = 0
    for r in rows:
        if shown >= 5: break
        if int(r.get("description_length",0) or 0) > 100:
            print(f"\n  🏢 {r.get('company_name','?')[:30]} | {r.get('portal','?')}")
            print(f"  💼 {r.get('job_title','?')[:55]}")
            print(f"  📍 {r.get('location','?')[:35]} | 🏠 {r.get('remote_type','?')}")
            print(f"  💰 {r.get('salary_range','N/A')[:40]}")
            print(f"  🛠️  {r.get('tech_stack','N/A')[:60]}")
            print(f"  📅 Exp: {r.get('experience_years','N/A')[:40]}")
            print(f"  🤖 Score: {r.get('validation_score','?')}% | {r.get('validation_status','?')}")
            if r.get('hr_email'): print(f"  📧 {r['hr_email']}")
            print(f"  🔗 {r.get('apply_link','')[:70]}")
            preview = " ".join(str(r.get("job_description","")).split()[:25])
            print(f"  📄 {preview}...")
            shown += 1

if __name__ == "__main__":
    run()
