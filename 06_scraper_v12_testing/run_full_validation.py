"""
╔══════════════════════════════════════════════════════════════════════╗
║  FULL END-TO-END VALIDATION — V12                                    ║
║                                                                      ║
║  1. Clear DB & run harvester with correct keywords                   ║
║  2. Re-scrape detail pages (enricher approach — saves AI tokens)     ║
║  3. AI rescore only jobs with full descriptions                      ║
║  4. Flag non-US jobs (India etc.)                                    ║
║  5. Validate all 29 columns + portal coverage                        ║
║                                                                      ║
║  KEY INSIGHT: Scrape first → AI later = less tokens, more data!      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, os, time, re, random, json, logging, requests, hashlib
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

# ── Path setup ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "01_local_scraper"))
sys.path.insert(0, str(Path(__file__).parent))

from standalone_db import get_connection, query_df, execute_sql, insert_row, update_row, init_bronze_table, DB_PATH

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("Validator")

# ============================================================
# ⚙️  CONFIG
# ============================================================
NVIDIA_API_KEY = os.getenv("NVIDIA_NIM_API_KEY",
    "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")
NVIDIA_MODEL = "meta/llama-3.2-11b-vision-instruct"

# ── All 14 expected portals ───────────────────────────────────
ALL_14_PORTALS = [
    "LinkedIn", "Indeed", "Dice", "Built In",
    "Glassdoor", "Wellfound", "ZipRecruiter", "SimplyHired",
    "Monster", "HiringCafe", "WTTJ", "CareerBuilder",
    "Greenhouse", "Lever",
]

# ── Non-US location patterns ─────────────────────────────────
INDIA_CITIES = [
    "noida", "bangalore", "bengaluru", "mumbai", "hyderabad", "chennai",
    "pune", "delhi", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "jaipur", "lucknow", "indore", "coimbatore", "kochi", "chandigarh",
    "mysore", "vizag", "visakhapatnam", "nagpur", "bhopal", "thiruvananthapuram",
]
NON_US_PATTERNS = INDIA_CITIES + [
    "uttar pradesh", "karnataka", "maharashtra", "tamil nadu", "telangana",
    "andhra pradesh", "west bengal", "rajasthan", "kerala", "gujarat",
    "india", "uk ", "united kingdom", "canada", "london", "toronto",
    "germany", "berlin", "singapore", "australia", "sydney", "melbourne",
]

# ── Portal-specific selectors (from enricher) ────────────────
PORTAL_SELECTORS = {
    "dice.com": [
        "div[data-testid='jobDescriptionHtml']",
        "div[class*='description']",
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
    "ziprecruiter.com": ["div[class*='job_description']", "div[class*='description']"],
    "monster.com": ["div[class*='job-description']", "div[class*='description']"],
    "careerbuilder.com": ["div[class*='job-description']", "div[class*='description']"],
    "hiring.cafe": ["div[class*='description']", "article", "main"],
    "welcometothejungle.com": ["div[class*='description']", "div[class*='content']"],
}

UNIVERSAL_FALLBACKS = [
    "div#jobDescription", "div.description",
    "div[class*='description']", "section[class*='description']",
    "div[class*='job-body']", "article", "main",
]

# ── Portal wait times ─────────────────────────────────────────
PORTAL_WAIT = {
    "dice.com": 5, "linkedin.com": 4, "indeed.com": 3,
    "glassdoor.com": 4, "wellfound.com": 5, "builtin.com": 3,
    "simplyhired.com": 3, "ziprecruiter.com": 3,
    "monster.com": 3, "greenhouse.io": 2, "lever.co": 2,
    "hiring.cafe": 4, "careerbuilder.com": 3, "welcometothejungle.com": 4,
}

# ============================================================
# 📧  EMAIL EXTRACTOR
# ============================================================
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
EMAIL_BLACKLIST = {"example.com", "test.com", "noreply", "sentry.io",
                   "amazonaws.com", "cloudfront.net", "w3.org", "schema.org",
                   "intercom.io", "hubspot.com", "wixpress.com", "openxmlformats.org"}

def extract_best_email(html: str) -> str:
    emails = EMAIL_RE.findall(html)
    clean, seen = [], set()
    for e in emails:
        e = e.lower().strip(".,;")
        domain = e.split("@")[-1]
        if any(bl in domain for bl in EMAIL_BLACKLIST):
            continue
        if e not in seen:
            seen.add(e)
            clean.append(e)
    if not clean:
        return ""
    for prefix in ["recruit", "talent", "hr", "hiring", "jobs", "careers", "apply", "people"]:
        for e in clean:
            if prefix in e.split("@")[0]:
                return e
    return clean[0]

# ============================================================
# 🔍  IMPROVED TEXT EXTRACTORS (fixed \n issue)
# ============================================================
def extract_roles(text: str) -> str:
    """Extract roles/responsibilities with RELAXED regex — handles both \\n and whitespace."""
    patterns = [
        # Relaxed: section header followed by content, separated by any whitespace
        r"(?:key\s+)?responsibilities[\s:]*[:\-–]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits|about\s+(?:us|the)|who\s+you|experience|education|preferred|nice\s+to\s+have|compensation|what\s+we\s+offer)|\Z)",
        r"(?:what\s+you(?:'ll)?\s+do|your\s+role|day[\s\-.]to[\s\-.]day|in\s+this\s+role)[\s:]*[:\-–]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits|about|what\s+you(?:'ll)?\s+need|who\s+you)|\Z)",
        r"(?:role\s+(?:overview|description|summary))[\s:]*[:\-–]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits)|\Z)",
        r"(?:duties\s+(?:and|&)\s+responsibilities|job\s+duties)[\s:]*[:\-–]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits)|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 50:
                return s[:2000]
    return ""

def extract_requirements(text: str) -> str:
    """Extract requirements with RELAXED regex."""
    patterns = [
        r"(?:requirements|qualifications|must\s+have|required\s+skills|what\s+you(?:'ll)?\s+need|minimum\s+qualifications)[\s:]*[:\-–]?\s*(.*?)(?=(?:benefits|about\s+(?:us|the)|what\s+we|nice\s+to\s+have|preferred|compensation|responsibilities|how\s+to\s+apply)|\Z)",
        r"(?:you(?:'ll)?\s+(?:need|bring)|we(?:'re)?\s+looking\s+for)[\s:]*[:\-–]?\s*(.*?)(?=(?:benefits|about|nice\s+to\s+have|preferred|compensation)|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 50:
                return s[:2000]
    return ""

def extract_salary(text: str) -> str:
    patterns = [
        r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?\s*(?:per\s+(?:year|annum|yr|month|hour)|\/(?:yr|year|hr|hour))",
        r"(?:salary|compensation)[\s:]+\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?",
        r"\$[\d]+[Kk](?:\s*[-–]\s*\$[\d]+[Kk])?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group().strip()[:80]
    return ""

def extract_experience(text: str) -> str:
    patterns = [
        r"(\d+\+?\s*(?:to|-)\s*\d+\+?)\s+years?\s+(?:of\s+)?experience",
        r"(\d+\+?)\s+years?\s+(?:of\s+)?experience",
        r"minimum\s+(\d+\+?)\s+years?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group().strip()[:60]
    return ""

# ============================================================
# 🌍  US LOCATION VALIDATOR
# ============================================================
def is_non_us_job(location: str, apply_link: str, job_description: str = "") -> bool:
    """Check if job is non-US based on location, URL, and description."""
    check_text = f"{location} {apply_link} {job_description[:500]}".lower()
    for pattern in NON_US_PATTERNS:
        if pattern in check_text:
            return True
    return False

# ============================================================
# 🔗  LINKEDIN POSTER PROFILE EXTRACTOR
# ============================================================
def extract_linkedin_poster_profile(page, url: str) -> str:
    """Try to extract LinkedIn profile URL of the job poster for messaging."""
    if "linkedin.com" not in url:
        return ""
    try:
        # Look for the poster's profile link on the job page
        poster_selectors = [
            "a[href*='/in/'][class*='poster']",
            "a[href*='/in/'][class*='hiring']",
            "a[href*='/in/'][class*='recruiter']",
            "div[class*='hiring-team'] a[href*='/in/']",
            "section[class*='hiring'] a[href*='/in/']",
            "div[class*='poster'] a[href*='/in/']",
            # Guest view — poster card
            "a.base-card__full-link[href*='/in/']",
            "div[class*='hirer'] a[href*='/in/']",
            # Any profile link near "Posted by" text
            "a[href*='linkedin.com/in/']",
        ]
        for sel in poster_selectors:
            try:
                els = page.query_selector_all(sel)
                for el in els:
                    href = el.get_attribute("href") or ""
                    if "/in/" in href and "/jobs/" not in href:
                        # Clean URL
                        profile_url = href.split("?")[0]
                        if not profile_url.startswith("http"):
                            profile_url = "https://www.linkedin.com" + profile_url
                        return profile_url
            except Exception:
                pass
    except Exception:
        pass
    return ""

# ============================================================
# 🔍  DETAIL ENRICHER (from enricher script)
# ============================================================
def enrich_job_detail(page, url: str) -> dict:
    """
    Visit a job detail page and extract full data via scraping.
    Uses portal-specific selectors with retries.
    Returns dict with extracted fields.
    """
    portal_key = next((k for k in PORTAL_SELECTORS if k in url), "default")
    wait_secs = next((v for k, v in PORTAL_WAIT.items() if k in url), 4)
    selectors = PORTAL_SELECTORS.get(portal_key, []) + UNIVERSAL_FALLBACKS

    empty = {
        "job_description": "", "hr_email": "", "salary_range": "",
        "experience_years": "", "roles_responsibilities": "",
        "requirements_section": "", "detail_fetched": False,
        "company_website": "", "easy_apply_link": "",
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(wait_secs)

            # Wait for meaningful content
            try:
                page.wait_for_selector(
                    "h1, div[class*='description'], article, div#jobDescriptionText",
                    timeout=8000)
            except Exception:
                pass

            html = page.content()

            # ── LinkedIn: try Guest API first (faster, no rendering needed) ──
            if "linkedin.com" in url:
                from html.parser import HTMLParser
                job_id_m = re.search(r"-(\d{7,})(?:[/?]|$)", url)
                job_id = job_id_m.group(1) if job_id_m else ""
                if job_id:
                    try:
                        guest_resp = requests.get(
                            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
                            headers={
                                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                                "Accept": "text/html",
                                "Referer": "https://www.linkedin.com/jobs/",
                            },
                            timeout=15, verify=False
                        )
                        if guest_resp.status_code == 200 and len(guest_resp.text) > 200:
                            # Extract description from guest API HTML
                            desc_patterns = [
                                r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                                r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>',
                                r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>',
                            ]
                            for pat in desc_patterns:
                                dm = re.search(pat, guest_resp.text, re.DOTALL | re.I)
                                if dm:
                                    clean = re.sub(r"<[^>]+>", " ", dm.group(1))
                                    clean = re.sub(r"\s+", " ", clean).strip()
                                    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
                                    if len(clean) > 200:
                                        roles = extract_roles(clean)
                                        reqs = extract_requirements(clean)
                                        sal = extract_salary(clean)
                                        exp = extract_experience(clean)
                                        email = extract_best_email(guest_resp.text)
                                        poster_profile = extract_linkedin_poster_profile(page, url)
                                        return {
                                            "job_description": clean[:5000],
                                            "hr_email": email,
                                            "salary_range": sal,
                                            "experience_years": exp,
                                            "roles_responsibilities": roles[:2000],
                                            "requirements_section": reqs[:2000],
                                            "detail_fetched": True,
                                            "company_website": "",
                                            "easy_apply_link": poster_profile,
                                        }
                    except Exception as e:
                        log.debug(f"  LinkedIn guest API error: {e}")

            # ── Try portal-specific selectors ─────────────────
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
                except Exception:
                    continue

            # ── Smart JS fallback — find longest job-like div ──
            if len(desc) < 100:
                try:
                    desc_js = page.evaluate("""() => {
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
                    if desc_js and len(desc_js) > len(desc):
                        desc = desc_js
                except Exception:
                    pass

            if len(desc) > 80:
                roles = extract_roles(desc)
                reqs = extract_requirements(desc)
                sal = extract_salary(desc)
                exp = extract_experience(desc)
                email = extract_best_email(html)

                co_url = ""
                try:
                    co_el = page.query_selector(
                        "a[href*='careers'], a[data-testid='employer-website']")
                    if co_el:
                        co_url = co_el.get_attribute("href") or ""
                except Exception:
                    pass

                # LinkedIn poster profile for messaging
                poster_profile = ""
                if "linkedin.com" in url:
                    poster_profile = extract_linkedin_poster_profile(page, url)

                return {
                    "job_description": desc[:5000],
                    "hr_email": email,
                    "salary_range": sal,
                    "experience_years": exp,
                    "roles_responsibilities": roles[:2000],
                    "requirements_section": reqs[:2000],
                    "detail_fetched": True,
                    "company_website": co_url,
                    "easy_apply_link": poster_profile,
                }

        except Exception as e:
            log.debug(f"  Enrich attempt {attempt+1} error: {e}")

        if attempt < max_retries - 1:
            time.sleep(random.uniform(2.0, 6.0))

    return empty

# ============================================================
# 🤖  AI RESCORE (only for jobs with full description)
# ============================================================
def ai_rescore(job: dict) -> dict:
    """Re-score with NVIDIA NIM. Only called for jobs with good descriptions."""
    desc = (job.get("job_description") or "")[:3000]
    title = job.get("job_title", "")
    company = job.get("company_name", "")
    location = job.get("location", "")

    if len(desc) < 50:
        return {
            "validation_score": 60, "validation_status": "Partial",
            "ai_summary": "No description available", "roles_summary": "",
            "tech_stack": job.get("tech_stack", ""), "experience_years": "Not specified",
            "remote_type": "Remote" if "remote" in (title + location).lower() else "Not specified",
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
                timeout=30,
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
                log.debug(f"  AI rate limited, retry {attempt+1}...")
                time.sleep(5)
            else:
                log.debug(f"  AI error {resp.status_code}")
        except json.JSONDecodeError:
            pass
        except Exception as e:
            log.debug(f"  AI error: {e}")
            if attempt < 2:
                time.sleep(random.uniform(2, 4))

    return {
        "validation_score": 60, "validation_status": "Partial",
        "ai_summary": "AI unavailable", "roles_summary": "",
        "tech_stack": job.get("tech_stack", ""), "experience_years": "Not specified",
        "remote_type": "Not specified", "visa_sponsorship": False,
    }

# ============================================================
# 📊  VALIDATION REPORTERS
# ============================================================
def print_portal_coverage(df):
    """Show which of 14 portals returned jobs."""
    print("\n" + "═" * 70)
    print("  📊 PORTAL COVERAGE (14 expected sites)")
    print("═" * 70)
    portal_counts = df["portal"].value_counts().to_dict() if not df.empty else {}
    total_portals_with_data = 0
    rows = []
    for portal in ALL_14_PORTALS:
        cnt = portal_counts.get(portal, 0)
        status = "✅" if cnt > 0 else "❌ ZERO"
        if cnt > 0:
            total_portals_with_data += 1
        rows.append([portal, cnt, status])
    if HAS_TABULATE:
        print(tabulate(rows, headers=["Portal", "Jobs", "Status"], tablefmt="rounded_outline"))
    else:
        for row in rows:
            print(f"  {row[0]:<20} → {row[1]:>4} {row[2]}")
    print(f"\n  📈 Portals with data: {total_portals_with_data}/14")
    return portal_counts

def print_us_filter_report(df):
    """Show non-US job detection results."""
    print("\n" + "═" * 70)
    print("  🌍 US LOCATION FILTER RESULTS")
    print("═" * 70)
    non_us_count = 0
    non_us_samples = []
    for _, row in df.iterrows():
        loc = str(row.get("location", ""))
        link = str(row.get("apply_link", ""))
        desc = str(row.get("job_description", ""))
        if is_non_us_job(loc, link, desc):
            non_us_count += 1
            if len(non_us_samples) < 5:
                non_us_samples.append(f"  {row.get('job_title', '?')[:35]} | {loc[:30]} | {row.get('portal', '?')}")
    print(f"  Total jobs:        {len(df)}")
    print(f"  Non-US detected:   {non_us_count}")
    print(f"  US-only jobs:      {len(df) - non_us_count}")
    if non_us_samples:
        print(f"\n  📍 Sample Non-US jobs:")
        for s in non_us_samples:
            print(s)
    return non_us_count

def print_column_fill_rates(df):
    """Validate all 29 columns with fill rates and root cause hints."""
    print("\n" + "═" * 70)
    print("  📋 COLUMN FILL RATE ANALYSIS (29 columns)")
    print("═" * 70)
    total = len(df)
    if total == 0:
        print("  ❌ No data!")
        return

    EXPECTED_SCHEMA = {
        "id":                    {"critical": True},
        "job_hash":              {"critical": True},
        "fetch_date":            {"critical": True},
        "portal":                {"critical": True},
        "search_keyword":        {"critical": True},
        "job_title":             {"critical": True},
        "company_name":          {"critical": True},
        "location":              {"critical": True},
        "remote_type":           {"critical": False},
        "salary_range":          {"critical": False},
        "experience_years":      {"critical": False},
        "tech_stack":            {"critical": False},
        "posted_date":           {"critical": False},
        "job_description":       {"critical": False},
        "description_length":    {"critical": False},
        "roles_responsibilities":{"critical": False},
        "requirements_section":  {"critical": False},
        "roles_summary":         {"critical": False},
        "apply_link":            {"critical": True},
        "easy_apply_link":       {"critical": False},
        "company_career_url":    {"critical": False},
        "company_website":       {"critical": False},
        "hr_email":              {"critical": False},
        "job_id":                {"critical": False},
        "visa_sponsorship":      {"critical": False},
        "validation_score":      {"critical": True},
        "validation_status":     {"critical": True},
        "ai_summary":            {"critical": False},
        "detail_fetched":        {"critical": False},
    }

    EMPTY_VALUES = {"", "0", "false", "not specified", "not Specified", "n/a",
                    "unknown", "pending", "none", "0.0", "False"}

    rows = []
    issues = []
    for col, spec in EXPECTED_SCHEMA.items():
        if col not in df.columns:
            rows.append(["❌", col, "YES" if spec["critical"] else "no", "MISSING", "0%"])
            issues.append(f"MISSING column: {col}")
            continue
        filled = 0
        for val in df[col]:
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            if val_str.lower() not in EMPTY_VALUES and len(val_str) > 0:
                filled += 1
        pct = filled * 100 // total
        if pct >= 80:
            status = "✅"
        elif pct >= 50:
            status = "⚠️"
        elif pct > 0:
            status = "🟡"
        else:
            status = "❌"

        crit = "YES" if spec["critical"] else "no"
        rows.append([status, col, crit, f"{filled}/{total}", f"{pct}%"])

        if spec["critical"] and pct < 80:
            issues.append(f"CRITICAL '{col}' only {pct}% filled!")
        elif pct < 30:
            root_cause = ""
            if col == "roles_responsibilities":
                root_cause = " → regex needs \\n after headers, most scraped text uses spaces"
            elif col == "requirements_section":
                root_cause = " → same regex issue as roles_responsibilities"
            elif col == "easy_apply_link":
                root_cause = " → only set for LinkedIn Easy Apply jobs"
            elif col == "hr_email":
                root_cause = " → most job pages don't expose HR emails"
            elif col == "salary_range":
                root_cause = " → many US jobs don't list salary"
            issues.append(f"LOW '{col}' only {pct}%{root_cause}")

    if HAS_TABULATE:
        print(tabulate(rows, headers=["", "Column", "Critical", "Filled", "Rate"], tablefmt="rounded_outline"))
    else:
        for row in rows:
            print(f"  {row[0]} {row[1]:<28} {row[2]:<8} {row[3]:<12} {row[4]}")

    if issues:
        print(f"\n  ⚠️  ISSUES ({len(issues)}):")
        for issue in issues:
            print(f"     • {issue}")

def print_keyword_check(df):
    """Check what search keywords were used."""
    print("\n" + "═" * 70)
    print("  🔍 SEARCH KEYWORD CHECK")
    print("═" * 70)
    if df.empty:
        print("  ❌ No data!")
        return
    kw_counts = df["search_keyword"].value_counts().to_dict()
    rows = []
    bad_keywords = []
    for kw, cnt in sorted(kw_counts.items(), key=lambda x: -x[1]):
        # Check for the "P Developer" bug (single-char keywords)
        if len(kw.split()[0]) <= 2 and kw.split()[0].isalpha():
            status = "❌ BUG"
            bad_keywords.append(kw)
        else:
            status = "✅"
        rows.append([kw, cnt, status])
    if HAS_TABULATE:
        print(tabulate(rows, headers=["Keyword", "Jobs", "Status"], tablefmt="rounded_outline"))
    else:
        for row in rows:
            print(f"  {row[0]:<35} → {row[1]:>4} {row[2]}")
    if bad_keywords:
        print(f"\n  ❌ BAD KEYWORDS DETECTED (single-char prefix bug):")
        for bk in bad_keywords:
            print(f"     • '{bk}' ← likely from string iteration bug!")

def print_linkedin_link_audit(df):
    """Audit LinkedIn easy_apply_link vs apply_link."""
    print("\n" + "═" * 70)
    print("  🔗 LINKEDIN LINK ANALYSIS")
    print("═" * 70)
    linkedin_jobs = df[df["portal"] == "LinkedIn"] if "portal" in df.columns else pd.DataFrame()
    if linkedin_jobs.empty:
        print("  ⚠️  No LinkedIn jobs found")
        return
    total_li = len(linkedin_jobs)
    with_easy = sum(1 for _, r in linkedin_jobs.iterrows()
                    if str(r.get("easy_apply_link", "")).strip() and
                    str(r.get("easy_apply_link", "")).strip() != str(r.get("apply_link", "")).strip())
    same_link = sum(1 for _, r in linkedin_jobs.iterrows()
                    if str(r.get("easy_apply_link", "")).strip() ==
                    str(r.get("apply_link", "")).strip() and
                    str(r.get("easy_apply_link", "")).strip())
    with_profile = sum(1 for _, r in linkedin_jobs.iterrows()
                       if "/in/" in str(r.get("easy_apply_link", "")))
    print(f"  LinkedIn jobs total:             {total_li}")
    print(f"  With poster profile link:        {with_profile}")
    print(f"  With easy_apply = same URL:      {same_link} (should be poster profile instead)")
    print(f"  With unique easy_apply_link:     {with_easy}")

def print_job_title_quality(df):
    """Check for bad job titles."""
    print("\n" + "═" * 70)
    print("  📝 JOB TITLE QUALITY CHECK")
    print("═" * 70)
    bad_titles = []
    for _, row in df.iterrows():
        title = str(row.get("job_title", ""))
        portal = str(row.get("portal", ""))
        if len(title) < 5:
            bad_titles.append((title, portal, "Too short"))
        elif title.lower() in ["unknown", "job posting", "job", "untitled"]:
            bad_titles.append((title, portal, "Generic/missing"))
        elif len(title.split()) == 1 and len(title) <= 2:
            bad_titles.append((title, portal, "Single char (keyword bug)"))
    good = len(df) - len(bad_titles)
    print(f"  Good titles:  {good}/{len(df)}")
    print(f"  Bad titles:   {len(bad_titles)}/{len(df)}")
    if bad_titles:
        print(f"\n  ❌ Sample bad titles:")
        for title, portal, reason in bad_titles[:10]:
            print(f"     '{title}' ({portal}) — {reason}")

def print_sample_records(df):
    """Show 5 sample records with key fields."""
    print("\n" + "═" * 70)
    print("  📋 SAMPLE ENRICHED RECORDS")
    print("═" * 70)
    good = df[df["description_length"].astype(int) > 50] if "description_length" in df.columns else df
    sample = good.head(5) if not good.empty else df.head(5)
    for _, r in sample.iterrows():
        print(f"\n  🏢 {str(r.get('company_name', '?'))[:30]} | {str(r.get('portal', '?'))}")
        print(f"  💼 {str(r.get('job_title', '?'))[:55]}")
        print(f"  📍 {str(r.get('location', '?'))[:35]} | 🏠 {str(r.get('remote_type', '?'))}")
        print(f"  💰 {str(r.get('salary_range', 'N/A'))[:40]}")
        print(f"  🛠️  {str(r.get('tech_stack', 'N/A'))[:60]}")
        print(f"  📅 Exp: {str(r.get('experience_years', 'N/A'))[:40]}")
        print(f"  🤖 Score: {r.get('validation_score', '?')} | {r.get('validation_status', '?')}")
        if r.get("hr_email"):
            print(f"  📧 {r['hr_email']}")
        print(f"  🔗 {str(r.get('apply_link', ''))[:70]}")
        if r.get("easy_apply_link"):
            print(f"  💬 Message: {str(r['easy_apply_link'])[:70]}")
        roles = str(r.get("roles_responsibilities", ""))
        if roles and len(roles) > 10:
            print(f"  📋 Roles: {roles[:120]}...")
        else:
            print(f"  📋 Roles: ❌ EMPTY")
        desc = str(r.get("job_description", ""))
        print(f"  📄 Desc: {' '.join(desc.split()[:20])}...")

# ============================================================
# 🚀  MAIN VALIDATION PIPELINE
# ============================================================
def run():
    print("═" * 70)
    print("  🚀 FULL END-TO-END VALIDATION — V12")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📁 DB: {DB_PATH}")
    print("═" * 70)

    # ── Step 0: Init DB ───────────────────────────────────────
    init_bronze_table()

    # ── Step 1: Clear DB ──────────────────────────────────────
    print("\n🗑️  DELETING ALL DATA IN jobs_harvested_bronze...")
    conn = get_connection()
    conn.execute("DELETE FROM jobs_harvested_bronze")
    conn.commit()
    conn.close()

    # ── Step 2: Run harvester with CORRECT keyword ────────────
    # FIX: Pass list, not string! "Python" → ["Python Developer"]
    from job_scrapper import run_harvester_v10, CONFIG as SCRAPER_CONFIG
    SCRAPER_CONFIG["enable_all_sites"] = True

    print("\n🚀 STARTING HARVESTER PIPELINE...")
    print("   Keywords: ['Python Developer'] (FIX: was 'Python' string → 'P Developer' bug)")
    start_time = time.time()
    jobs = run_harvester_v10(["Python Developer"])  # FIX: list not string!
    harvest_elapsed = time.time() - start_time
    print(f"\n✅ Harvester finished in {harvest_elapsed/60:.1f} minutes. Got {len(jobs)} jobs.")

    # ── Step 3: Read DB and check what's missing ──────────────
    print("\n📊 READING DB TO CHECK MISSING DATA...")
    df = query_df("SELECT * FROM jobs_harvested_bronze")
    total = len(df)
    print(f"   Total records in DB: {total}")

    if total == 0:
        print("❌ FAILED: No records found! Cannot continue.")
        sys.exit(1)

    # Count jobs missing description or roles_responsibilities
    missing_desc = sum(1 for _, r in df.iterrows()
                       if pd.isna(r.get("job_description")) or
                       len(str(r.get("job_description", "")).strip()) < 80)
    missing_roles = sum(1 for _, r in df.iterrows()
                        if pd.isna(r.get("roles_responsibilities")) or
                        len(str(r.get("roles_responsibilities", "")).strip()) < 10)
    print(f"   Missing/short description: {missing_desc}/{total}")
    print(f"   Missing roles_responsibilities: {missing_roles}/{total}")

    # ── Step 4: RE-ENRICH — Scrape detail pages for missing data ──
    # This is the KEY optimization: scrape first, AI later = less tokens!
    to_enrich = df[
        (df["job_description"].isna() | (df["job_description"].str.len() < 80)) |
        (df["roles_responsibilities"].isna() | (df["roles_responsibilities"].str.len() < 10))
    ]
    enrich_count = len(to_enrich)
    print(f"\n🔍 RE-ENRICHMENT PHASE: {enrich_count} jobs need detail scraping...")
    print("   (Using portal-specific selectors — saves AI tokens!)")

    if enrich_count > 0:
        from playwright.sync_api import sync_playwright
        import playwright_stealth

        enriched = 0
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                      "--disable-dev-shm-usage"]
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,ico}", lambda r: r.abort())
            page = ctx.new_page()
            try:
                playwright_stealth.Stealth().apply_stealth_sync(page)
            except Exception:
                pass

            for idx, (_, row) in enumerate(to_enrich.iterrows()):
                url = str(row.get("apply_link", ""))
                job_hash = str(row.get("job_hash", ""))
                title = str(row.get("job_title", "?"))[:45]
                portal = str(row.get("portal", "?"))

                if not url or not job_hash:
                    continue

                log.info(f"  [{idx+1:3}/{enrich_count}] 🌐 {portal:12} | {title}")

                detail = enrich_job_detail(page, url)

                if detail["detail_fetched"]:
                    desc = detail["job_description"]
                    update_fields = {
                        "job_description": desc,
                        "description_length": len(desc.split()),
                        "detail_fetched": 1,
                        "roles_responsibilities": detail.get("roles_responsibilities", ""),
                        "requirements_section": detail.get("requirements_section", ""),
                    }
                    if detail.get("hr_email"):
                        update_fields["hr_email"] = detail["hr_email"]
                    if detail.get("salary_range"):
                        update_fields["salary_range"] = detail["salary_range"]
                    if detail.get("experience_years"):
                        update_fields["experience_years"] = detail["experience_years"]
                    if detail.get("company_website"):
                        update_fields["company_website"] = detail["company_website"]
                    if detail.get("easy_apply_link"):
                        update_fields["easy_apply_link"] = detail["easy_apply_link"]

                    ok, err = update_row("jobs_harvested_bronze", update_fields,
                                         f"job_hash = '{job_hash}'")
                    if ok:
                        enriched += 1
                        log.info(f"         ✅ {len(desc.split())} words | roles: {'YES' if detail.get('roles_responsibilities') else 'NO'}")
                    else:
                        log.error(f"         ❌ DB update error: {err}")
                else:
                    log.warning(f"         ⚠️  Scrape failed")

                time.sleep(random.uniform(1.5, 3.5))

                # Progress log every 20 jobs
                if (idx + 1) % 20 == 0:
                    log.info(f"  📈 Progress: {enriched}/{idx+1} enriched")

            page.close()
            ctx.close()
            browser.close()

        print(f"\n  ✅ Re-enrichment complete: {enriched}/{enrich_count} pages enriched")

    # ── Step 5: AI RESCORE only jobs with full descriptions ───
    # Reload DB after enrichment
    df = query_df("SELECT * FROM jobs_harvested_bronze")
    has_desc = df[df["description_length"].astype(int) > 100] if "description_length" in df.columns else pd.DataFrame()
    needs_rescore = has_desc[
        (has_desc["ai_summary"].isna()) |
        (has_desc["ai_summary"].str.strip() == "") |
        (has_desc["ai_summary"].str.strip() == "AI unavailable") |
        (has_desc["ai_summary"].str.strip() == "N/A")
    ] if not has_desc.empty else pd.DataFrame()

    rescore_count = len(needs_rescore)
    print(f"\n🤖 AI RESCORE PHASE: {rescore_count} jobs with descriptions need scoring...")
    print("   (Only scoring jobs that have full descriptions — token efficient!)")

    rescored = 0
    for idx, (_, row) in enumerate(needs_rescore.iterrows()):
        job_hash = str(row.get("job_hash", ""))
        title = str(row.get("job_title", "?"))[:40]

        log.info(f"  [{idx+1:3}/{rescore_count}] 🤖 {title}")
        ai_result = ai_rescore(row.to_dict())

        update_fields = {
            "validation_score": ai_result["validation_score"],
            "validation_status": ai_result["validation_status"],
            "ai_summary": ai_result.get("ai_summary", ""),
            "roles_summary": ai_result.get("roles_summary", ""),
            "remote_type": ai_result.get("remote_type", ""),
            "visa_sponsorship": 1 if ai_result.get("visa_sponsorship") else 0,
        }
        if ai_result.get("tech_stack"):
            update_fields["tech_stack"] = ai_result["tech_stack"]
        if ai_result.get("experience_years", "") not in ("Not specified", ""):
            update_fields["experience_years"] = ai_result["experience_years"]
        if ai_result.get("salary_mentioned") and not str(row.get("salary_range", "")).strip():
            update_fields["salary_range"] = ai_result["salary_mentioned"]

        ok, err = update_row("jobs_harvested_bronze", update_fields,
                             f"job_hash = '{job_hash}'")
        if ok:
            rescored += 1
        if (idx + 1) % 10 == 0:
            log.info(f"  📈 Progress: {rescored}/{idx+1} rescored")

    print(f"  ✅ AI rescore complete: {rescored}/{rescore_count} jobs scored")

    # ── Step 6: FLAG NON-US JOBS ──────────────────────────────
    print("\n🌍 FLAGGING NON-US JOBS...")
    df = query_df("SELECT * FROM jobs_harvested_bronze")
    non_us_flagged = 0
    for _, row in df.iterrows():
        loc = str(row.get("location", ""))
        link = str(row.get("apply_link", ""))
        desc = str(row.get("job_description", ""))
        if is_non_us_job(loc, link, desc):
            ok, err = update_row("jobs_harvested_bronze",
                                 {"validation_status": "Non-US"},
                                 f"job_hash = '{row['job_hash']}'")
            if ok:
                non_us_flagged += 1
    print(f"  Flagged {non_us_flagged} non-US jobs with validation_status='Non-US'")

    # ── Step 7: FULL VALIDATION REPORT ────────────────────────
    # Reload final data
    df = query_df("SELECT * FROM jobs_harvested_bronze")
    total = len(df)

    total_elapsed = time.time() - start_time
    print(f"\n\n{'═' * 70}")
    print(f"  🎯 FULL VALIDATION REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  ⏱️  Total elapsed: {total_elapsed/60:.1f} minutes")
    print(f"  📊 Total records: {total}")
    print(f"{'═' * 70}")

    if total == 0:
        print("❌ No records to validate!")
        return

    # 7a. Portal coverage
    print_portal_coverage(df)

    # 7b. Keyword check
    print_keyword_check(df)

    # 7c. US location filter
    print_us_filter_report(df)

    # 7d. Column fill rates
    print_column_fill_rates(df)

    # 7e. LinkedIn link audit
    print_linkedin_link_audit(df)

    # 7f. Job title quality
    print_job_title_quality(df)

    # 7g. Validation status distribution
    print("\n" + "═" * 70)
    print("  🎯 VALIDATION STATUS DISTRIBUTION")
    print("═" * 70)
    status_counts = df["validation_status"].value_counts().to_dict()
    for status, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        icon = {"Valid": "✅", "Partial": "⚠️", "Junk": "❌", "Non-US": "🌍", "Pending": "⏳"}.get(status, "?")
        print(f"  {icon} {status:<15} → {cnt}")

    # 7h. Score distribution
    print("\n" + "═" * 70)
    print("  📊 SCORE DISTRIBUTION")
    print("═" * 70)
    score_df = query_df("""
        SELECT
            CASE
                WHEN validation_score >= 80 THEN '80-100 (Excellent)'
                WHEN validation_score >= 60 THEN '60-79 (Good)'
                WHEN validation_score >= 40 THEN '40-59 (Partial)'
                ELSE '0-39 (Low)'
            END as score_range,
            COUNT(*) as cnt
        FROM jobs_harvested_bronze
        GROUP BY score_range
        ORDER BY score_range DESC
    """)
    if not score_df.empty:
        for _, row in score_df.iterrows():
            print(f"  {row['score_range']:<25} → {row['cnt']}")

    # 7i. Description stats
    desc_filled = sum(1 for _, r in df.iterrows()
                      if int(r.get("description_length", 0) or 0) > 50)
    roles_filled = sum(1 for _, r in df.iterrows()
                       if str(r.get("roles_responsibilities", "")).strip()
                       and len(str(r.get("roles_responsibilities", "")).strip()) > 10)
    email_filled = sum(1 for _, r in df.iterrows()
                       if str(r.get("hr_email", "")).strip())
    print(f"\n  📝 With full description:      {desc_filled}/{total} ({desc_filled*100//total}%)")
    print(f"  📋 With roles_responsibilities:{roles_filled}/{total} ({roles_filled*100//total}%)")
    print(f"  📧 With HR email:              {email_filled}/{total} ({email_filled*100//total}%)")

    # 7j. Sample records
    print_sample_records(df)

    print(f"\n{'═' * 70}")
    print("  ✅ VALIDATION COMPLETE!")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    run()
