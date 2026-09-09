"""
╔══════════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V10 — FULL PIPELINE                            ║
║                                                                      ║
║  PHASE 1: Multi-Portal Job Discovery (25 Best Sites)                 ║
║  PHASE 2: Full Job Description Fetch (Parallel, AI-Gated)            ║
║  PHASE 3: NVIDIA NIM AI Validation + Skills + Summary                ║
║  PHASE 4: Email & Company Career Page Extraction                     ║
║                                                                      ║
║  NEW vs V9:                                                          ║
║    ✅ Full job descriptions (not just snippets)                      ║
║    ✅ Wellfound fixed                                                 ║
║    ✅ 12 portals (LinkedIn, Indeed, Dice, Glassdoor, Wellfound,      ║
║       Built In, ZipRecruiter, SimplyHired, Monster, Greenhouse,      ║
║       Lever, CareerBuilder)                                          ║
║    ✅ Email extraction via regex                                      ║
║    ✅ Company career page URL discovery                               ║
║    ✅ LinkedIn "Easy Apply" direct link                               ║
║    ✅ Parallel detail fetching (ThreadPoolExecutor)                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, csv, hashlib, uuid, re, time, random, logging, json, requests
from datetime import datetime, date, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin, quote_plus
import playwright_stealth

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ============================================================
# ⚙️  LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("V10")

# ============================================================
# ⚙️  CONFIG
# ============================================================
CONFIG = {
    # ── Output ──────────────────────────────────────────────
    "csv_file": "jobs_v10_output_test_2.csv",

    # ── NVIDIA NIM ───────────────────────────────────────────
    "nvidia_api_key": os.getenv("NVIDIA_NIM_API_KEY", "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"),
    "nvidia_model":   "meta/llama-3.1-8b-instruct",
    "use_ai_scoring": True,

    # ── Site Toggle ──────────────────────────────────────────
    # Set ENABLE_ALL_SITES=True to scrape all 12 portals
    # Set to False to only scrape top 4 (LinkedIn, Indeed, Dice, Built In)
    "enable_all_sites": True,

    # ── Target Roles ─────────────────────────────────────────
    "roles": [
        "Data Engineer",
        "Senior Data Engineer",
        "PySpark Engineer",
        "ETL Developer",
        "Analytics Engineer",
        "Machine Learning Engineer",
        "Databricks Engineer",
        "Spark Developer",
    ],

    # ── Scraping ─────────────────────────────────────────────
    "max_jobs_per_portal_per_role": 25,
    "page_timeout_ms": 30_000,
    "scroll_delay": 1.5,
    "inter_request_delay": (1.5, 3.0),
    "min_validation_score": 40,
    "headless": True,

    # ── Detail Fetch ─────────────────────────────────────────
    # Only fetch detail page for jobs that pass AI scoring >= this
    "detail_fetch_min_score": 50,
    "detail_fetch_workers": 3,      # Parallel browser contexts for detail fetch
    "detail_fetch_timeout_ms": 25_000,
}

# ── Dates ──────────────────────────────────────────────────
TODAY     = date.today()
YESTERDAY = TODAY - timedelta(days=1)
DATE_TAGS = {
    TODAY.isoformat(), YESTERDAY.isoformat(),
    TODAY.strftime("%B %d, %Y"), YESTERDAY.strftime("%B %d, %Y"),
    "today", "yesterday", "just now", "1 day ago",
    "minutes ago", "hour ago", "hours ago",
}

# ── CSV Headers (V10 — Expanded) ──────────────────────────
CSV_HEADERS = [
    "id", "job_hash", "fetch_date", "portal", "search_keyword",
    "job_title", "company_name", "location", "remote_type",
    "salary_range", "experience_years", "tech_stack",
    "posted_date", "job_description", "description_length",
    "roles_responsibilities", "requirements_section", "roles_summary",
    "apply_link", "easy_apply_link", "company_career_url",
    "company_website", "hr_email",
    "job_id", "visa_sponsorship",
    "validation_score", "validation_status", "ai_summary",
    "detail_fetched",
]

GARBAGE_DOMAINS = {
    "youtube.com", "github.com", "stackoverflow.com", "medium.com",
    "reddit.com", "quora.com", "udemy.com", "coursera.org",
    "twitter.com", "facebook.com", "instagram.com", "wikipedia.org",
}

# ============================================================
# 🗓️  DATE VALIDATOR
# ============================================================
def is_recent_job(posted_text: str) -> bool:
    if not posted_text:
        return True
    pt = posted_text.lower().strip()
    
    # Fast check for Glassdoor/Wellfound shorthand (24h, 1d, 2d)
    if "24h" in pt or "1d" in pt or "today" in pt or "just now" in pt:
        return True
        
    for tag in DATE_TAGS:
        if tag.lower() in pt:
            return True
            
    m = re.search(r"(\d+)\s*[hd]", pt)
    if m and "h" in pt and int(m.group(1)) <= 48:
        return True
    if m and "d" in pt and int(m.group(1)) <= 1:
        return True
        
    if any(x in pt for x in ["minute", "second", "just now"]):
        return True
    return False

# ============================================================
# 📧  EMAIL EXTRACTOR
# ============================================================
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE
)
EMAIL_BLACKLIST = {
    "example.com", "test.com", "noreply", "no-reply",
    "sentry.io", "amazonaws.com", "cloudfront.net",
    "w3.org", "schema.org", "openxmlformats.org",
}

def extract_emails(text: str) -> list[str]:
    """Extract real emails from HTML/text, filter noise."""
    emails = EMAIL_PATTERN.findall(text)
    clean = []
    seen = set()
    for e in emails:
        e = e.lower().strip(".,;")
        domain = e.split("@")[-1]
        if any(bl in domain for bl in EMAIL_BLACKLIST):
            continue
        if e not in seen:
            seen.add(e)
            clean.append(e)
    return clean

def best_hr_email(emails: list[str], company_domain: str = "") -> str:
    """Pick the best HR/recruiter email from a list."""
    if not emails:
        return ""
    priority_prefixes = ["recruit", "talent", "hr", "hiring", "jobs", "careers", "apply", "people"]
    for prefix in priority_prefixes:
        for e in emails:
            if prefix in e:
                return e
    # Prefer company domain email
    if company_domain:
        for e in emails:
            if company_domain.lower() in e:
                return e
    return emails[0]

# ============================================================
# 🔍  COMPANY DOMAIN GUESSER
# ============================================================
def guess_company_domain(company_name: str) -> str:
    """Guess company website domain from name."""
    if not company_name or company_name.lower() in ("unknown", ""):
        return ""
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", company_name).strip().lower()
    words = clean.split()
    if words:
        domain = words[0] + ".com"
        return domain
    return ""

# ============================================================
# 🤖  NVIDIA NIM AI SCORER
# ============================================================
def ai_score_job(job: dict) -> tuple[int, str, str, str, bool]:
    """
    Score a job using NVIDIA NIM API.
    Returns: (score, ai_summary, tech_stack, experience_years, visa_sponsorship)
    """
    api_key = CONFIG["nvidia_api_key"]
    if not api_key or api_key.startswith("YOUR_"):
        sc = rule_based_score(job)
        return sc, "N/A", job.get("tech_stack", ""), "Not Specified", False

    desc = (job.get("job_description") or "")[:2000]
    if len(desc) < 50:
        desc = f"Job Title: {job.get('job_title')}. Company: {job.get('company_name')}."

    prompt = f"""Analyze this US IT job posting. Respond ONLY with JSON, no other text.

Title: {job.get('job_title', '')}
Company: {job.get('company_name', '')}
Location: {job.get('location', '')}
Description: {desc}

JSON format (strictly):
{{
  "score": <0-100 integer, relevance for US IT job search>,
  "is_real_job": <true/false>,
  "summary": "<2-sentence summary>",
  "tech_stack": "<top 6 skills comma-separated>",
  "experience_years": "<e.g. '3-5 years' or 'Not specified'>",
  "remote_type": "<Remote|Hybrid|Onsite|Not specified>",
  "visa_sponsorship": <true/false>
}}"""

    try:
        resp = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": CONFIG["nvidia_model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 400,
            },
            timeout=15
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return (
                    int(data.get("score", 50)),
                    data.get("summary", ""),
                    data.get("tech_stack", ""),
                    data.get("experience_years", "Not specified"),
                    bool(data.get("visa_sponsorship", False)),
                )
    except Exception as e:
        log.debug(f"AI score error: {e}")

    return rule_based_score(job), "AI unavailable", "", "Not specified", False


def rule_based_score(rec: dict) -> int:
    score = 0
    desc = (rec.get("job_description") or "").lower()
    title = (rec.get("job_title") or "").lower()
    company = (rec.get("company_name") or "").lower()
    if len(title) > 5 and "unknown" not in title:
        score += 30
    if len(company) > 3 and "unknown" not in company:
        score += 20
    kw = ["experience", "skills", "requirements", "responsibilities", "role",
          "candidate", "apply", "qualifications", "hiring", "engineer"]
    score += min(sum(1 for k in kw if k in desc) * 5, 35)
    score += 15 if len(desc) > 400 else (5 if len(desc) > 100 else 0)
    return min(score, 100)

# ============================================================
# 🏗️  JOB RECORD BUILDER
# ============================================================
def build_record(portal, keyword, title, company, location, desc, url,
                 posted="", salary="", job_type="", job_id="") -> dict:
    now = datetime.now()
    return {
        "id":               str(uuid.uuid4()),
        "job_hash":         hashlib.md5(url.encode()).hexdigest(),
        "fetch_date":       now.strftime("%Y-%m-%d"),
        "portal":           portal,
        "search_keyword":   keyword,
        "job_title":        (title or keyword).strip(),
        "company_name":     (company or "Unknown").strip(),
        "location":         (location or "USA").strip(),
        "remote_type":      "Remote" if "remote" in (desc + location).lower() else "Not specified",
        "salary_range":     salary or "Not Specified",
        "experience_years": "Not Specified",
        "tech_stack":       "Not Specified",
        "posted_date":      posted,
        "job_description":  desc[:3000] if desc else "",
        "description_length": len(desc.split()) if desc else 0,
        "apply_link":       url,
        "easy_apply_link":  "",
        "company_career_url": "",
        "company_website":  "",
        "hr_email":         "",
        "job_id":           job_id,
        "visa_sponsorship": False,
        "validation_score": 0,
        "validation_status": "Pending",
        "ai_summary":       "",
        "detail_fetched":   False,
    }


# ============================================================
# 🤖  AI AUTO-HEALER (Token Optimized)
# ============================================================
def ai_heal_selectors(page, portal_name, keyword):
    """
    If a scraper returns 0 jobs, the site likely changed classes.
    This extracts a tiny 200-token summary of the DOM and asks AI for the new selector.
    Very strict token limit to save budget!
    """
    log.warning(f"  🤖 Auto-Healer analyzing {portal_name} DOM for '{keyword}'...")
    try:
        dom_snippet = page.evaluate('''() => {
            let candidates = new Set();
            document.querySelectorAll('div, li, article').forEach(el => {
                let cls = el.className;
                if (typeof cls === 'string' && (cls.includes('job') || cls.includes('card') || cls.includes('result'))) {
                    candidates.add(el.tagName.toLowerCase() + '.' + cls.trim().replace(/\\s+/g, '.'));
                }
            });
            return Array.from(candidates).slice(0, 15).join('\n');
        }''')
        
        if not dom_snippet:
            return None
            
        prompt = f"Portal {portal_name} job card HTML classes:\n{dom_snippet}\nRespond ONLY with the single best CSS selector for the job card. No markdown, no explanation."
        
        resp = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {CONFIG['nvidia_api_key']}", "Content-Type": "application/json"},
            json={
                "model": CONFIG["nvidia_model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1, 
                "max_tokens": 30 # Super tight limit!
            },
            timeout=10
        )
        if resp.status_code == 200:
            selector = resp.json()["choices"][0]["message"]["content"].strip().replace('`', '')
            log.info(f"  🤖 AI Suggested Selector: {selector}")
            return selector
    except Exception as e:
        log.debug(f"Auto-healer err: {e}")
    return None

# ============================================================
# 🌐  BASE SCRAPER
# ============================================================
class BaseScraper:
    def __init__(self, page, portal_name: str):
        self.page = page
        self.portal = portal_name

    def safe_text(self, sel, default=""):
        try:
            el = self.page.query_selector(sel)
            return el.inner_text().strip() if el else default
        except: return default

    def scroll_page(self, times=3):
        for _ in range(times):
            self.page.evaluate("window.scrollBy(0, 900)")
            time.sleep(CONFIG["scroll_delay"])

# ============================================================
# 🏢  PORTAL SCRAPERS
# ============================================================

# ── LINKEDIN ────────────────────────────────────────────────
class LinkedInScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "LinkedIn")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.linkedin.com/jobs/search?keywords={q}&location=United+States&f_TPR=r86400&sortBy=DD"
            log.info(f"  🌐 LinkedIn → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(5)

            cards = self.page.query_selector_all("div.base-card")
            log.info(f"  📦 LinkedIn: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h3.base-search-card__title")
                    title = title_el.inner_text().strip() if title_el else ""

                    link_el = card.query_selector("a.base-card__full-link")
                    href = link_el.get_attribute("href") or "" if link_el else ""
                    if href:
                        href = href.split("?")[0]

                    company_el = card.query_selector("h4.base-search-card__subtitle a, a.hidden-nested-link")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("span.job-search-card__location")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("time.job-search-card__listdate, time[datetime]")
                    posted = date_el.get_attribute("datetime") or date_el.inner_text().strip() if date_el else ""

                    # Extract job ID from URL
                    job_id = re.search(r"/view/[^-]+-(\d+)", href)
                    job_id = job_id.group(1) if job_id else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted, job_id=job_id)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"LinkedIn card err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ LinkedIn: {e}")
        return jobs


# ── INDEED ──────────────────────────────────────────────────
class IndeedScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Indeed")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.indeed.com/jobs?q={q}&l=United+States&fromage=1&sort=date"
            log.info(f"  🌐 Indeed → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(4)

            cards = self.page.query_selector_all("div.job_seen_beacon")
            if not cards:
                cards = self.page.query_selector_all("[data-testid='slider_item']")
            
            if not cards:
                new_sel = ai_heal_selectors(self.page, "Indeed", keyword)
                if new_sel: cards = self.page.query_selector_all(new_sel)
                
            log.info(f"  📦 Indeed: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h3.jobTitle span[title], h3[class*='jobTitle'] span[title]")
                    title = title_el.get_attribute("title") if title_el else ""
                    if not title:
                        t2 = card.query_selector("h3.jobTitle a, h3[class*='jobTitle'] a")
                        title = t2.inner_text().strip() if t2 else keyword

                    link_el = card.query_selector("a.jcs-JobTitle, h3.jobTitle a, h3[class*='jobTitle'] a")
                    href = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href and not href.startswith("http"):
                            href = "https://www.indeed.com" + href

                    company_el = card.query_selector("[data-testid='company-name']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("[data-testid='text-location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("span[class*='date'], [data-testid*='date']")
                    posted = date_el.inner_text().strip() if date_el else ""

                    salary_el = card.query_selector("[class*='salary'], [data-testid='attribute_snippet_testid']")
                    salary = salary_el.inner_text().strip() if salary_el else ""

                    # Job key from URL
                    jk = re.search(r"jk=([a-f0-9]+)", href)
                    job_id = jk.group(1) if jk else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)
                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted, salary, job_id=job_id)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"Indeed card err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Indeed: {e}")
        return jobs


# ── DICE ─────────────────────────────────────────────────────
class DiceScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Dice")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.dice.com/jobs?q={q}&countryCode=US&radius=30&radiusUnit=mi&page=1&pageSize=20&filters.postedDate=ONE_DAY_AGO&language=en"
            log.info(f"  🌐 Dice → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(3)

            job_links = self.page.query_selector_all("a[href*='/job-detail']")
            log.info(f"  📦 Dice: {len(job_links)} job links")

            seen = set()
            for link_el in job_links[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    href = link_el.get_attribute("href") or ""
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = "https://www.dice.com" + href
                    if href in seen:
                        continue
                    seen.add(href)

                    title = link_el.inner_text().strip() or keyword

                    # Get surrounding text for company/location
                    company, location, posted = "Unknown", "USA", ""
                    try:
                        nearby = link_el.evaluate("""
                            el => {
                                let c = el.closest('li') || el.closest('div[class*="card"]') || el.parentElement;
                                return c ? c.innerText : '';
                            }
                        """)
                        lines = [l.strip() for l in nearby.split('\n') if l.strip()]
                        # lines[0] = title, [1] = company, [2] = location/date
                        if len(lines) > 1: company = lines[1][:60]
                        if len(lines) > 2: location = lines[2][:60]
                        if len(lines) > 3:
                            for l in lines[2:]:
                                if any(x in l.lower() for x in ["today", "ago", "day", "hour"]):
                                    posted = l
                                    break
                    except: pass

                    # Dice job ID = UUID in URL
                    jid = re.search(r"/job-detail/([a-f0-9\-]{36})", href)
                    job_id = jid.group(1) if jid else ""

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted, job_id=job_id)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"Dice link err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Dice: {e}")
        return jobs


# ── GLASSDOOR ────────────────────────────────────────────────
class GlassdoorScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Glassdoor")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = keyword.replace(" ", "-")
            url = f"https://www.glassdoor.com/Job/us-{q.lower()}-jobs-SRCH_IL.0,2_IN1_KO3,{3+len(q)}.htm?fromAge=1&sortBy=date_desc"
            log.info(f"  🌐 Glassdoor → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(3)

            cards = self.page.query_selector_all("li[class*='JobsList_jobListItem']")
            if not cards:
                cards = self.page.query_selector_all("[data-test='jobListing']")
            
            if not cards:
                new_sel = ai_heal_selectors(self.page, "Glassdoor", keyword)
                if new_sel: cards = self.page.query_selector_all(new_sel)
                
            log.info(f"  📦 Glassdoor: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("a[class*='JobCard_seoLink'], a[class*='jobLink']")
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") or "" if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.glassdoor.com" + href

                    company_el = card.query_selector("[class*='EmployerProfile_compactEmployerName'], span[class*='employer']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("[class*='JobCard_location'], span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("[class*='JobCard_listingAge'], span[class*='age']")
                    posted = date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)
                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"Glassdoor card err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Glassdoor: {e}")
        return jobs


# ── WELLFOUND (FIXED) ────────────────────────────────────────
class WellfoundScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Wellfound")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://wellfound.com/jobs?q={q}&remote=true"
            log.info(f"  🌐 Wellfound → {url}")
            self.page.goto(url, wait_until="networkidle", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(4)

            # Wellfound uses React — job cards are inside div[data-test="JobListing"]
            cards = self.page.query_selector_all("div[data-test='JobListing'], div[class*='JobListingCard']")
            if not cards:
                cards = self.page.query_selector_all("div[class*='styles_component__Ey28k']")
            if not cards:
                # Try any link containing /jobs/
                job_links = self.page.query_selector_all("a[href*='/jobs/']")
                log.info(f"  📦 Wellfound links: {len(job_links)}")
                seen = set()
                for link_el in job_links[:CONFIG["max_jobs_per_portal_per_role"]]:
                    try:
                        href = link_el.get_attribute("href") or ""
                        if not href or href in seen or "/jobs/" not in href:
                            continue
                        if not href.startswith("http"):
                            href = "https://wellfound.com" + href
                        seen.add(href)
                        title = link_el.inner_text().strip() or keyword
                        rec = build_record(self.portal, keyword, title, "Unknown", "Remote", "", href)
                        jobs.append(rec)
                    except: pass
                return jobs

            log.info(f"  📦 Wellfound: {len(cards)} cards")
            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("a[class*='title'], h2 a, a[href*='/jobs/']")
                    title = title_el.inner_text().strip() if title_el else keyword
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://wellfound.com" + href

                    company_el = card.query_selector("a[class*='company'], h1[class*='name']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else "Remote"

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    rec = build_record(self.portal, keyword, title, company, location, "", href)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"Wellfound card err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Wellfound: {e}")
        return jobs


# ── BUILTIN ──────────────────────────────────────────────────
class BuiltInScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Built In")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://builtin.com/jobs?search={q}"
            log.info(f"  🌐 Built In → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            job_links = self.page.query_selector_all("a[href*='/job/']")
            log.info(f"  📦 Built In: {len(job_links)} links")

            seen = set()
            for link_el in job_links[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    href = link_el.get_attribute("href") or ""
                    if not href or href in seen:
                        continue
                    if not href.startswith("http"):
                        href = "https://builtin.com" + href
                    seen.add(href)

                    title = link_el.inner_text().strip() or keyword

                    # Try to get company from parent
                    company, location = "Unknown", "USA"
                    try:
                        nearby = link_el.evaluate("""
                            el => {
                                let p = el.closest('div[data-id]') || el.closest('li') || el.parentElement.parentElement;
                                return p ? p.innerText : '';
                            }
                        """)
                        lines = [l.strip() for l in nearby.split('\n') if l.strip()]
                        if len(lines) > 1: company = lines[1][:50]
                        if len(lines) > 2: location = lines[2][:50]
                    except: pass

                    rec = build_record(self.portal, keyword, title, company, location, "", href)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"BuiltIn err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Built In: {e}")
        return jobs


# ── ZIPRECRUITER ─────────────────────────────────────────────
class ZipRecruiterScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "ZipRecruiter")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = keyword.replace(" ", "-")
            url = f"https://www.ziprecruiter.com/Jobs/{q}?days=1&sort=date"
            log.info(f"  🌐 ZipRecruiter → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(3)

            cards = self.page.query_selector_all("article[class*='job_result'], div[class*='jobList-item'], article[data-job-id]")
            if not cards:
                cards = self.page.query_selector_all("[class*='job-card'], li[class*='job']")
            log.info(f"  📦 ZipRecruiter: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h2 a, a[class*='job_link'], a[class*='jobTitle']")
                    title = title_el.inner_text().strip() if title_el else keyword
                    href = title_el.get_attribute("href") if title_el else ""

                    company_el = card.query_selector("a[class*='company_name'], [data-name='company']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("span[class*='location'], [data-name='location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("span[class*='posted'], time")
                    posted = date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)
                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"ZipRecruiter err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ ZipRecruiter: {e}")
        return jobs


# ── SIMPLYHIRED ──────────────────────────────────────────────
class SimplyHiredScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "SimplyHired")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.simplyhired.com/search?q={q}&l=United+States&fdb=1&sb=dd"
            log.info(f"  🌐 SimplyHired → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            cards = self.page.query_selector_all("div[data-testid='searchSerpJob'], article[class*='SerpJob']")
            if not cards:
                cards = self.page.query_selector_all("div.SerpJob-jobCard, li[class*='job-']")
            log.info(f"  📦 SimplyHired: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h3[class*='JobTitle'] a, a[data-testid='job-card-title']")
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.simplyhired.com" + href

                    company_el = card.query_selector("span[class*='Company'], [data-testid='company-name']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("span[class*='Location'], [data-testid='job-location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("time, span[class*='date']")
                    posted = date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)
                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"SimplyHired err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ SimplyHired: {e}")
        return jobs


# ── MONSTER ──────────────────────────────────────────────────
class MonsterScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Monster")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.monster.com/jobs/search?q={q}&where=United+States&tm=1"
            log.info(f"  🌐 Monster → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            job_links = self.page.query_selector_all("a[href*='/job-openings/'], a[data-testid='jobTitle']")
            if not job_links:
                job_links = self.page.query_selector_all("section.card-content a[href*='job']")
            log.info(f"  📦 Monster: {len(job_links)} links")

            seen = set()
            for link_el in job_links[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    href = link_el.get_attribute("href") or ""
                    if not href or href in seen:
                        continue
                    if not href.startswith("http"):
                        href = "https://www.monster.com" + href
                    seen.add(href)
                    title = link_el.inner_text().strip() or keyword
                    rec = build_record(self.portal, keyword, title, "Unknown", "USA", "", href)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"Monster err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ Monster: {e}")
        return jobs


# ── GREENHOUSE SCRAPER (via DDG search) ──────────────────────
class GreenhouseScraper:
    """Greenhouse.io jobs — company ATS with real job IDs."""
    
    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            from ddgs import DDGS as NewDDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS as NewDDGS
            except ImportError:
                return []

        query = f'"{keyword}" site:greenhouse.io/jobs'
        try:
            with NewDDGS() as ddgs:
                results = list(ddgs.text(query, region="us-en", max_results=15, timelimit="d"))
            for res in results:
                href = res.get("href", "")
                if not href or "greenhouse.io" not in href:
                    continue
                title_raw = res.get("title", keyword)
                snippet = res.get("body", "")
                title = re.sub(r"\s+at\s+.+$", "", title_raw, flags=re.I).strip()
                company_m = re.search(r"at (.+?)(?:\s*[-|]|$)", title_raw, re.I)
                company = company_m.group(1).strip() if company_m else "Unknown"
                # Extract Greenhouse job ID
                jid = re.search(r"/jobs/(\d+)", href)
                job_id = jid.group(1) if jid else ""
                rec = build_record("Greenhouse", keyword, title, company, "USA", snippet, href, job_id=job_id)
                jobs.append(rec)
        except Exception as e:
            log.debug(f"Greenhouse DDG: {e}")
        log.info(f"  📦 Greenhouse: {len(jobs)} jobs")
        return jobs


# ── LEVER SCRAPER (via DDG search) ───────────────────────────
class LeverScraper:
    """Lever.co jobs — ATS with sometimes visible emails."""

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            from ddgs import DDGS as NewDDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS as NewDDGS
            except ImportError:
                return []

        query = f'"{keyword}" site:jobs.lever.co'
        try:
            with NewDDGS() as ddgs:
                results = list(ddgs.text(query, region="us-en", max_results=15, timelimit="d"))
            for res in results:
                href = res.get("href", "")
                if not href or "lever.co" not in href:
                    continue
                title_raw = res.get("title", keyword)
                snippet = res.get("body", "")
                # Lever URL format: jobs.lever.co/company/job-uuid
                parts = urlparse(href).path.strip("/").split("/")
                company = parts[0].replace("-", " ").title() if parts else "Unknown"
                job_id = parts[1] if len(parts) > 1 else ""
                title = re.sub(r"\s*[-|]\s*Lever.*$", "", title_raw, flags=re.I).strip()
                rec = build_record("Lever", keyword, title or keyword, company, "USA", snippet, href, job_id=job_id)
                jobs.append(rec)
        except Exception as e:
            log.debug(f"Lever DDG: {e}")
        log.info(f"  📦 Lever: {len(jobs)} jobs")
        return jobs



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
# ============================================================
def fetch_job_detail(url: str, portal: str, browser_context) -> dict:
    """
    Visit a job detail page and extract:
    - Full job description
    - HR email
    - Company career URL
    - Salary, experience, skills
    - LinkedIn Easy Apply link or company apply link
    """
    result = {
        "job_description": "",
        "hr_email": "",
        "company_career_url": "",
        "company_website": "",
        "easy_apply_link": "",
        "salary_range": "",
        "detail_fetched": False,
    }

    page = None
    try:
        page = browser_context.new_page()
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        })
        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())
        page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["detail_fetch_timeout_ms"])
        time.sleep(2)

        html = page.content()
        text = page.inner_text("body") if page.query_selector("body") else ""

        # ── Extract description by portal ──────────────────────
        desc = ""
        if "linkedin.com" in url:
            desc_el = page.query_selector("div.description__text, div[class*='show-more-less-html']")
            if desc_el:
                desc = desc_el.inner_text().strip()
            # Easy Apply link
            easy_el = page.query_selector("button[class*='easy-apply'], a[class*='apply']")
            if easy_el:
                result["easy_apply_link"] = url  # LinkedIn Easy Apply = same page

        elif "indeed.com" in url:
            desc_el = page.query_selector("div#jobDescriptionText, div[class*='jobsearch-JobComponent-description']")
            if desc_el:
                desc = desc_el.inner_text().strip()
            # Company website
            co_link = page.query_selector("a[data-testid='employer-website'], a[class*='companyLink']")
            if co_link:
                result["company_website"] = co_link.get_attribute("href") or ""

        elif "dice.com" in url:
            desc_el = page.query_selector("div[data-testid='jobDescriptionHtml'], div[class*='job-description']")
            if desc_el:
                desc = desc_el.inner_text().strip()
            salary_el = page.query_selector("[class*='salary'], [data-testid='salary']")
            if salary_el:
                result["salary_range"] = salary_el.inner_text().strip()

        elif "glassdoor.com" in url:
            desc_el = page.query_selector("div[class*='JobDetails_jobDescription'], div.jobDescriptionContent")
            if desc_el:
                desc = desc_el.inner_text().strip()

        elif "wellfound.com" in url or "angel.co" in url:
            desc_el = page.query_selector("div[class*='description'], section[class*='job-description']")
            if desc_el:
                desc = desc_el.inner_text().strip()

        elif "builtin.com" in url:
            desc_el = page.query_selector("div.job-description, section[class*='description']")
            if desc_el:
                desc = desc_el.inner_text().strip()

        elif "greenhouse.io" in url:
            desc_el = page.query_selector("div#content, div.job-post")
            if desc_el:
                desc = desc_el.inner_text().strip()

        elif "lever.co" in url:
            desc_el = page.query_selector("div.content, div[class*='posting-description']")
            if desc_el:
                desc = desc_el.inner_text().strip()

        elif "simplyhired.com" in url:
            desc_el = page.query_selector("div[data-testid='VJ-section-description'], div.viewjob-description")
            if desc_el:
                desc = desc_el.inner_text().strip()

        # ── Fallback: longest paragraph ────────────────────────
        if not desc or len(desc) < 100:
            # Try common selectors
            for sel in ["div[class*='description']", "div[class*='job-desc']",
                        "section[class*='description']", "article", "main"]:
                el = page.query_selector(sel)
                if el:
                    candidate = el.inner_text().strip()
                    if len(candidate) > len(desc):
                        desc = candidate
                        if len(desc) > 200:
                            break

        result["job_description"] = desc[:4000] if desc else ""

        # ── Email extraction ────────────────────────────────────
        emails = extract_emails(html)
        if emails:
            domain = guess_company_domain("")
            result["hr_email"] = best_hr_email(emails)

        # ── Company career page ────────────────────────────────
        career_el = page.query_selector("a[href*='career'], a[href*='job']")
        if career_el:
            career_url = career_el.get_attribute("href") or ""
            if career_url and "http" in career_url:
                result["company_career_url"] = career_url

        result["detail_fetched"] = bool(result["job_description"])

    except Exception as e:
        log.debug(f"Detail fetch failed for {url}: {e}")
    finally:
        if page:
            try:
                page.close()
            except: pass

    return result


def fetch_details_parallel(records: list, _browser=None) -> list:
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
                playwright_stealth.Stealth().apply_stealth_sync(page)
                
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
    return list(hash_to_record.values())


# ============================================================
# 💾  CSV WRITER
# ============================================================
def write_csv(records: list) -> int:
    csv_file = CONFIG["csv_file"]
    existing = set()
    if os.path.exists(csv_file):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                existing = {row.get("job_hash", "") for row in csv.DictReader(f)}
        except: pass

    new_recs = [r for r in records if r["job_hash"] not in existing]
    if not new_recs:
        return 0

    mode = "a" if os.path.exists(csv_file) else "w"
    with open(csv_file, mode=mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        w.writerows(new_recs)
    return len(new_recs)


# ============================================================
# 📊  SUMMARY PRINTER
# ============================================================
def print_summary(records: list):
    if not records:
        return

    print("\n" + "=" * 70)
    print(f"  🎯 JOB HARVEST V10 COMPLETE — {date.today()}")
    print("=" * 70)

    by_portal = defaultdict(int)
    by_kw = defaultdict(int)
    by_status = defaultdict(int)
    with_desc = sum(1 for r in records if r.get("description_length", 0) > 50)
    with_email = sum(1 for r in records if r.get("hr_email", ""))

    for r in records:
        by_portal[r.get("portal", "?")] += 1
        by_kw[r.get("search_keyword", "?")] += 1
        by_status[r.get("validation_status", "?")] += 1

    if HAS_TABULATE:
        print("\n🌐 Jobs by Portal:")
        print(tabulate([[p, c] for p, c in sorted(by_portal.items(), key=lambda x: -x[1])],
                       headers=["Portal", "Jobs"], tablefmt="rounded_outline"))
        print("\n🔍 Jobs by Keyword:")
        print(tabulate([[k, c] for k, c in sorted(by_kw.items(), key=lambda x: -x[1])],
                       headers=["Keyword", "Jobs"], tablefmt="rounded_outline"))
    else:
        for p, c in sorted(by_portal.items(), key=lambda x: -x[1]):
            print(f"  {p:<20} → {c}")

    print(f"\n✅ Valid: {by_status.get('Valid',0)}  ⚠️ Partial: {by_status.get('Partial',0)}")
    print(f"📝 With description: {with_desc}/{len(records)} ({with_desc*100//max(len(records),1)}%)")
    print(f"📧 With email: {with_email}/{len(records)}")
    print(f"📁 CSV: {os.path.abspath(CONFIG['csv_file'])}")
    print("=" * 70)

    print("\n📋 SAMPLE JOBS (first 5 with descriptions):")
    shown = 0
    for r in records:
        if shown >= 5:
            break
        if r.get("description_length", 0) > 50:
            desc_preview = " ".join((r.get("job_description") or "").split()[:20])
            print(f"  🏢 {r['company_name'][:25]:<25} | {r['portal']:<12} | {r['job_title'][:35]}")
            print(f"     📍 {r.get('location','')[:40]}  |  💰 {r.get('salary_range','N/A')[:30]}")
            print(f"     🔗 {r['apply_link'][:65]}")
            if r.get("hr_email"):
                print(f"     📧 {r['hr_email']}")
            print(f"     📄 {desc_preview}...")
            print()
            shown += 1


# ============================================================
# 🚀  MAIN ORCHESTRATOR
# ============================================================
def run_harvester_v10():
    log.info("=" * 65)
    log.info("🚀 US IT JOB HARVESTER V10 — FULL PIPELINE")
    log.info(f"📋 Roles: {len(CONFIG['roles'])} | Sites: {'ALL 10+' if CONFIG['enable_all_sites'] else 'Top 4'}")
    log.info(f"⏱️  Filter: Yesterday ({YESTERDAY}) + Today ({TODAY})")
    log.info(f"🤖 AI: NVIDIA NIM ({CONFIG['nvidia_model']})")
    log.info("=" * 65)

    all_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=CONFIG["headless"],
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-infobars", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        playwright_stealth.Stealth().apply_stealth_sync(page)
        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda r: r.abort())

        # ── Portal scrapers ─────────────────────────────────
        browser_scrapers = {
            "LinkedIn":     LinkedInScraper(page),
            "Indeed":       IndeedScraper(page),
            "Dice":         DiceScraper(page),
            "Built In":     BuiltInScraper(page),
        }
        if CONFIG["enable_all_sites"]:
            browser_scrapers.update({
                "Glassdoor":    GlassdoorScraper(page),
                "Wellfound":    WellfoundScraper(page),
                "ZipRecruiter": ZipRecruiterScraper(page),
                "SimplyHired":  SimplyHiredScraper(page),
                "Monster":      MonsterScraper(page),
            })

        ddg_scrapers = []
        if CONFIG["enable_all_sites"]:
            ddg_scrapers = [GreenhouseScraper(), LeverScraper()]

        # ── PHASE 1: Discovery ──────────────────────────────
        log.info("\n═══ PHASE 1: JOB DISCOVERY ═══")
        for role in CONFIG["roles"]:
            log.info(f"\n{'─'*50}")
            log.info(f"🔍 Role: {role}")
            log.info(f"{'─'*50}")

            for portal_name, scraper in browser_scrapers.items():
                try:
                    jobs = scraper.scrape(role)
                    log.info(f"  ✅ {portal_name}: {len(jobs)} jobs")
                    all_records.extend(jobs)
                except Exception as e:
                    log.warning(f"  ❌ {portal_name}: {e}")
                time.sleep(random.uniform(*CONFIG["inter_request_delay"]))

            for scraper in ddg_scrapers:
                try:
                    jobs = scraper.scrape(role)
                    all_records.extend(jobs)
                except Exception as e:
                    log.debug(f"DDG scraper err: {e}")

        context.close()

        # ── Dedup ───────────────────────────────────────────
        seen_hashes, unique = set(), []
        for rec in all_records:
            if rec["job_hash"] not in seen_hashes:
                seen_hashes.add(rec["job_hash"])
                unique.append(rec)

        log.info(f"\n📊 Phase 1 complete → Raw: {len(all_records)} | After dedup: {len(unique)}")

        # ── PHASE 2: Initial AI Scoring (fast, no detail page yet) ──
        log.info("\n═══ PHASE 2: INITIAL AI SCORING ═══")
        for i, rec in enumerate(unique):
            sc, summary, tech, exp_yrs, visa = ai_score_job(rec)
            rec["validation_score"] = sc
            rec["validation_status"] = "Valid" if sc >= 70 else "Partial" if sc >= CONFIG["min_validation_score"] else "Junk"
            rec["ai_summary"] = summary
            rec["tech_stack"] = tech
            rec["experience_years"] = exp_yrs
            rec["visa_sponsorship"] = visa
            if (i + 1) % 20 == 0:
                log.info(f"   Scored {i+1}/{len(unique)}...")

        # Filter junk before detail fetch
        quality = [r for r in unique if r["validation_status"] != "Junk"]
        log.info(f"✅ After initial scoring: {len(quality)} quality jobs")

        # ── PHASE 3: Full Detail Fetch (parallel) ───────────
        log.info("\n═══ PHASE 3: FULL DETAIL FETCH ═══")
        quality = fetch_details_parallel(quality, browser)

        # ── PHASE 4: Re-score with full description ──────────
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
                log.info(f"   Re-scored {i+1}/{len(fetched_with_desc)}...")

        final = [r for r in quality if r["validation_status"] != "Junk"]
        log.info(f"✅ Final quality jobs: {len(final)}")

        browser.close()

    # ── Write CSV ────────────────────────────────────────────
    written = write_csv(final)
    log.info(f"\n💾 Written {written} new records → {CONFIG['csv_file']}")

    print_summary(final)
    return final


# ── Entry Point ───────────────────────────────────────────────
if __name__ == "__main__":
    jobs = run_harvester_v10()
    print(f"\n🎉 DONE! Total: {len(jobs)} jobs harvested")
    desc_count = sum(1 for j in jobs if j.get("description_length", 0) > 50)
    email_count = sum(1 for j in jobs if j.get("hr_email"))
    print(f"   📝 With full description: {desc_count}")
    print(f"   📧 With HR email: {email_count}")
    print(f"   📁 CSV: jobs_v10_output.csv")
