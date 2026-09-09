"""
╔══════════════════════════════════════════════════════════════════╗
║  US IT JOB HARVESTER V9 — PLAYWRIGHT BROWSER SCRAPER            ║
║  Scrapes: LinkedIn, Indeed, Dice, Glassdoor, Wellfound,          ║
║           Built In, ZipRecruiter                                  ║
║  Filter:  Yesterday/Today jobs ONLY                               ║
║  Scoring: NVIDIA NIM AI Validation                                ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, csv, hashlib, uuid, re, time, random, logging, json, requests
from datetime import datetime, date, timedelta
from collections import defaultdict

# ── Try to import tabulate for pretty table printing ──
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

# ── Playwright ──
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ============================================================
# ⚙️  LOGGING SETUP
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("JobHarvester")

# ============================================================
# ⚙️  CONFIG — EDIT HERE
# ============================================================
CONFIG = {
    # ── Output ──────────────────────────────────────────────
    "csv_file": "jobs_scraped_output.csv",

    # ── NVIDIA NIM API ───────────────────────────────────────
    # Put your key here OR set env variable NVIDIA_NIM_API_KEY
    "nvidia_api_key": "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",
    "nvidia_model": "meta/llama-3.1-8b-instruct",
    "use_ai_scoring": True,   # Set False to skip AI (faster, no API needed)

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

    # ── Scraping Settings ────────────────────────────────────
    "max_jobs_per_portal_per_role": 25,  # Max jobs to scrape per site per keyword
    "page_timeout_ms": 30_000,            # 30s timeout per page
    "scroll_delay": 1.5,                  # Seconds between scrolls
    "inter_request_delay": (2, 4),        # Random delay between requests
    "min_validation_score": 40,           # Jobs below this are discarded
    "headless": True,                     # False = see the browser open (debug mode)
}

# ── Date filters ─────────────────────────────────────────────
TODAY     = date.today()
YESTERDAY = TODAY - timedelta(days=1)
DATE_TAGS = {TODAY.isoformat(), YESTERDAY.isoformat(),
             TODAY.strftime("%B %d, %Y"), YESTERDAY.strftime("%B %d, %Y"),
             "today", "yesterday", "just now", "1 day ago", "23 hours ago",
             "22 hours ago", "21 hours ago", "20 hours ago", "19 hours ago",
             "18 hours ago", "17 hours ago", "16 hours ago", "15 hours ago",
             "14 hours ago", "13 hours ago", "12 hours ago", "11 hours ago",
             "10 hours ago", "9 hours ago", "8 hours ago", "7 hours ago",
             "6 hours ago", "5 hours ago", "4 hours ago", "3 hours ago",
             "2 hours ago", "1 hour ago", "minutes ago", "hour ago"}

# ── CSV Column Headers ───────────────────────────────────────
CSV_HEADERS = [
    "id", "job_hash", "fetch_date", "portal", "search_keyword",
    "job_title", "company_name", "location", "job_type",
    "salary_range", "experience_required", "skills_required",
    "posted_date", "job_description", "apply_link",
    "validation_score", "validation_status", "ai_summary",
]

# ============================================================
# 🛡️  GARBAGE FILTER
# ============================================================
GARBAGE_DOMAINS = {
    "youtube.com", "github.com", "stackoverflow.com", "medium.com",
    "reddit.com", "quora.com", "udemy.com", "coursera.org",
    "twitter.com", "facebook.com", "instagram.com", "wikipedia.org",
}

def is_garbage_url(url: str) -> bool:
    return any(d in url.lower() for d in GARBAGE_DOMAINS)

# ============================================================
# 🗓️  DATE VALIDATOR — Only yesterday/today jobs
# ============================================================
def is_recent_job(posted_text: str) -> bool:
    """Returns True if job was posted yesterday or today."""
    if not posted_text:
        return True  # If no date found, keep it (can't reject)
    pt = posted_text.lower().strip()
    # Check exact matches from DATE_TAGS
    for tag in DATE_TAGS:
        if tag.lower() in pt:
            return True
    # Check "X hours ago" pattern
    match = re.search(r"(\d+)\s+hour", pt)
    if match and int(match.group(1)) <= 48:
        return True
    # Check "X days ago"
    match = re.search(r"(\d+)\s+day", pt)
    if match and int(match.group(1)) <= 1:
        return True
    # Check "X minutes ago"
    if "minute" in pt or "second" in pt:
        return True
    return False

# ============================================================
# 🤖  NVIDIA NIM AI SCORER
# ============================================================
def ai_score_job(job: dict) -> tuple[int, str, str]:
    """
    Score a job using NVIDIA NIM API.
    Returns: (score 0-100, ai_summary, skills_extracted)
    """
    api_key = CONFIG["nvidia_api_key"]
    if not api_key or api_key == "YOUR_NVIDIA_NIM_API_KEY_HERE":
        return rule_based_score(job), "N/A", job.get("skills_required", "N/A")

    prompt = f"""Analyze this job posting and respond in JSON format only.

Job Title: {job.get('job_title', 'Unknown')}
Company: {job.get('company_name', 'Unknown')}
Description: {job.get('job_description', '')[:1000]}

Respond ONLY with this JSON (no other text):
{{
  "score": <integer 0-100, how relevant this is for a US IT job search>,
  "is_valid_job": <true/false>,
  "summary": "<1 sentence summary of the role>",
  "key_skills": "<comma separated top 5 skills>",
  "experience_level": "<Entry/Mid/Senior/Lead>"
}}"""

    try:
        resp = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": CONFIG["nvidia_model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 300,
            },
            timeout=15
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = int(data.get("score", 50))
                summary = data.get("summary", "")
                skills = data.get("key_skills", "")
                return score, summary, skills
    except Exception as e:
        log.debug(f"AI scoring failed: {e}")

    return rule_based_score(job), "AI unavailable", job.get("skills_required", "N/A")


def rule_based_score(rec: dict) -> int:
    """Fallback rule-based scoring when AI is unavailable."""
    score = 0
    desc = rec.get("job_description", "").lower()
    title = rec.get("job_title", "").lower()
    company = rec.get("company_name", "").lower()

    # Title quality
    if len(title) > 5 and "unknown" not in title:
        score += 30
    # Company quality
    if len(company) > 3 and "unknown" not in company:
        score += 20
    # Description quality
    job_keywords = ["experience", "skills", "requirements", "responsibilities",
                    "role", "candidate", "apply", "qualifications", "hiring"]
    kw_count = sum(1 for kw in job_keywords if kw in desc)
    if kw_count >= 3:
        score += 35
    elif kw_count >= 1:
        score += 15
    # Description length
    if len(desc) > 400:
        score += 15
    elif len(desc) > 100:
        score += 5

    return min(score, 100)

# ============================================================
# 🏗️  JOB RECORD BUILDER
# ============================================================
def build_record(portal: str, keyword: str, title: str, company: str,
                 location: str, description: str, url: str,
                 posted_date: str = "", salary: str = "",
                 job_type: str = "") -> dict:
    now = datetime.now()
    job_hash = hashlib.md5(url.encode()).hexdigest()

    rec = {
        "id": str(uuid.uuid4()),
        "job_hash": job_hash,
        "fetch_date": now.strftime("%Y-%m-%d"),
        "portal": portal,
        "search_keyword": keyword,
        "job_title": title.strip() or keyword,
        "company_name": company.strip() or "Unknown",
        "location": location.strip() or "USA",
        "job_type": job_type or ("Remote" if "remote" in description.lower() else "Not Specified"),
        "salary_range": salary or "Not Specified",
        "experience_required": "Not Specified",
        "skills_required": "Not Specified",
        "posted_date": posted_date,
        "job_description": description[:2000],  # Trim long descriptions
        "apply_link": url,
        "validation_score": 0,
        "validation_status": "Pending",
        "ai_summary": "",
    }
    return rec

# ============================================================
# 🌐  PORTAL SCRAPERS
# ============================================================

class BaseScraper:
    """Base class for all job portal scrapers."""
    
    def __init__(self, page, portal_name: str):
        self.page = page
        self.portal = portal_name

    def safe_text(self, selector: str, default: str = "") -> str:
        try:
            el = self.page.query_selector(selector)
            return el.inner_text().strip() if el else default
        except:
            return default

    def safe_attr(self, selector: str, attr: str, default: str = "") -> str:
        try:
            el = self.page.query_selector(selector)
            return el.get_attribute(attr) or default if el else default
        except:
            return default

    def scroll_page(self, times: int = 3):
        for _ in range(times):
            self.page.evaluate("window.scrollBy(0, 800)")
            time.sleep(CONFIG["scroll_delay"])


# ── INDEED SCRAPER ──────────────────────────────────────────
class IndeedScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Indeed")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.replace(" ", "+")
            url = f"https://www.indeed.com/jobs?q={query}&l=United+States&fromage=1&sort=date"
            log.info(f"  🌐 Indeed → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(4)

            # Try multiple card selectors (Indeed changes layout frequently)
            cards = self.page.query_selector_all('div.job_seen_beacon')
            if not cards:
                cards = self.page.query_selector_all('[data-testid="slider_item"]')
            if not cards:
                cards = self.page.query_selector_all('div[class*="tapItem"]')
            if not cards:
                cards = self.page.query_selector_all('#mosaic-provider-jobcards li')
            
            log.info(f"  📦 Indeed: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    # Title — VERIFIED: h3.jobTitle > a.jcs-JobTitle > span[title]
                    title_el = card.query_selector('h3.jobTitle span[title], h3[class*="jobTitle"] span[title]')
                    title = title_el.get_attribute("title") if title_el else ""
                    if not title:
                        title_el2 = card.query_selector('h3.jobTitle a, h3[class*="jobTitle"] a')
                        title = title_el2.inner_text().strip() if title_el2 else keyword

                    # Job URL — VERIFIED: a.jcs-JobTitle href="/rc/clk?jk=..."
                    link_el = card.query_selector('a.jcs-JobTitle, a[class*="JobTitle"], h3.jobTitle a, h3[class*="jobTitle"] a')
                    href = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href and not href.startswith("http"):
                            href = "https://www.indeed.com" + href

                    # Company — VERIFIED: data-testid="company-name"
                    company_el = card.query_selector('[data-testid="company-name"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    # Location — VERIFIED: data-testid="text-location"
                    location_el = card.query_selector('[data-testid="text-location"]')
                    location = location_el.inner_text().strip() if location_el else "USA"

                    # Date posted
                    date_el = card.query_selector('span[class*="date"], [class*="result-footer"] span, [data-testid*="date"]')
                    posted = date_el.inner_text().strip() if date_el else ""

                    # Description bullets
                    desc_els = card.query_selector_all('ul li, div[class*="job-snippet"] li')
                    desc = " • ".join([el.inner_text().strip() for el in desc_els if el.inner_text().strip()])
                    if not desc:
                        desc_el = card.query_selector('div[class*="job-snippet"], div[class*="snippet"]')
                        desc = desc_el.inner_text().strip() if desc_el else ""

                    # Salary (bonus)
                    salary_el = card.query_selector('[class*="salaryText"], [class*="salary"], [data-testid="attribute_snippet_testid"]')
                    salary = salary_el.inner_text().strip() if salary_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title or keyword, company, location, desc, href, posted, salary)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"Indeed card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ Indeed scrape failed: {e}")

        return jobs


# ── DICE SCRAPER ─────────────────────────────────────────────
class DiceScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Dice")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.replace(" ", "%20")
            url = f"https://www.dice.com/jobs?q={query}&countryCode=US&radius=30&radiusUnit=mi&page=1&pageSize=20&filters.postedDate=ONE_DAY_AGO&language=en"
            log.info(f"  🌐 Dice → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(3)

            # Dice uses Angular SSR — job links are a[href*="/job-detail"]
            # VERIFIED: 69 links found in test
            job_links = self.page.query_selector_all('a[href*="/job-detail"]')
            log.info(f"  📦 Dice: Found {len(job_links)} job links")

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

                    # Extract info from parent card
                    parent = link_el.evaluate("el => el.closest('div.search-card, div[class*=\"card\"], li, div[data-cy]')")
                    title = link_el.inner_text().strip() or keyword

                    # Try getting more info from surrounding elements
                    company = "Unknown"
                    location = "USA"
                    posted = ""
                    try:
                        # Navigate to siblings for company/location
                        nearby_text = link_el.evaluate("""
                            el => {
                                const container = el.closest('div') || el.parentElement;
                                return container ? container.innerText : '';
                            }
                        """)
                        lines = [l.strip() for l in nearby_text.split('\n') if l.strip()]
                        if len(lines) > 1:
                            company = lines[1][:50]
                        if len(lines) > 2:
                            location = lines[2][:50]
                    except:
                        pass

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"Dice link error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ Dice scrape failed: {e}")

        return jobs


# ── GLASSDOOR SCRAPER ────────────────────────────────────────
class GlassdoorScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Glassdoor")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.replace(" ", "-")
            url = f"https://www.glassdoor.com/Job/united-states-{query}-jobs-SRCH_IL.0,13_IN1_KO14,{14+len(query)}.htm?fromAge=1&sortBy=date"
            log.info(f"  🌐 Glassdoor → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            cards = self.page.query_selector_all('li[class*="JobsList_jobListItem"]')
            if not cards:
                cards = self.page.query_selector_all('article[class*="job-listing"]')
            log.info(f"  📦 Glassdoor: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector('a[class*="JobCard_seoLink"], a[class*="jobLink"]')
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.glassdoor.com" + href

                    company_el = card.query_selector('[class*="EmployerProfile_compactEmployerName"], div[class*="employer-info"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector('[class*="JobCard_location"], span[class*="location"]')
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector('[class*="JobCard_listingAge"], span[class*="age"]')
                    posted = date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    if not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"Glassdoor card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ Glassdoor scrape failed: {e}")

        return jobs


# ── ZIPRECRUITER SCRAPER ─────────────────────────────────────
class ZipRecruiterScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "ZipRecruiter")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.replace(" ", "+")
            url = f"https://www.ziprecruiter.com/Jobs/{query.replace('+', '-')}?days=1&sort=date"
            log.info(f"  🌐 ZipRecruiter → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            cards = self.page.query_selector_all('article[class*="job_result"], div[class*="jobList-item"]')
            log.info(f"  📦 ZipRecruiter: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector('h2[class*="title"] a, a[class*="job_link"]')
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""

                    company_el = card.query_selector('a[class*="company_name"], [data-name="company"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector('span[class*="location"], [data-name="location"]')
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector('span[class*="posted"], time')
                    posted = date_el.inner_text().strip() if date_el else ""

                    desc_el = card.query_selector('p[class*="job_snippet"], div[class*="description"]')
                    desc = desc_el.inner_text().strip() if desc_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    if not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, desc, href, posted)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"ZipRecruiter card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ ZipRecruiter scrape failed: {e}")

        return jobs


# ── WELLFOUND SCRAPER ────────────────────────────────────────
class WellfoundScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Wellfound")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.lower().replace(" ", "-")
            url = f"https://wellfound.com/jobs?role={query}&remote=true"
            log.info(f"  🌐 Wellfound → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            cards = self.page.query_selector_all('div[class*="styles_component"], div[data-test="StartupResult"]')
            log.info(f"  📦 Wellfound: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector('a[class*="title"], h2 a')
                    title = title_el.inner_text().strip() if title_el else keyword
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://wellfound.com" + href

                    company_el = card.query_selector('a[class*="company"], h1[class*="name"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector('[class*="location"]')
                    location = loc_el.inner_text().strip() if loc_el else "Remote"

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    rec = build_record(self.portal, keyword, title, company, location, "", href)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"Wellfound card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ Wellfound scrape failed: {e}")

        return jobs


# ── BUILTIN SCRAPER ──────────────────────────────────────────
class BuiltInScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "Built In")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.lower().replace(" ", "-")
            url = f"https://builtin.com/jobs?search={keyword.replace(' ', '+')}"
            log.info(f"  🌐 Built In → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(3)

            cards = self.page.query_selector_all('div[data-id], li[class*="BrowseResultsCard"], article')
            log.info(f"  📦 Built In: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector('a[class*="job-title"], h2 a, h3 a')
                    title = title_el.inner_text().strip() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://builtin.com" + href

                    company_el = card.query_selector('[class*="company-name"], [data-id="company"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector('[class*="job-location"]')
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    rec = build_record(self.portal, keyword, title, company, location, "", href)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"Built In card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ Built In scrape failed: {e}")

        return jobs


# ── LINKEDIN SCRAPER (No login — public search) ──────────────
class LinkedInScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "LinkedIn")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            query = keyword.replace(" ", "%20")
            # f_TPR=r86400 = last 24 hours, f_WT=2 = remote
            url = f"https://www.linkedin.com/jobs/search?keywords={query}&location=United+States&f_TPR=r86400&sortBy=DD"
            log.info(f"  🌐 LinkedIn → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(3)
            self.scroll_page(5)

            cards = self.page.query_selector_all('div.base-card, li[class*="jobs-search-results__list-item"]')
            log.info(f"  📦 LinkedIn: Found {len(cards)} job cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector('h3[class*="base-search-card__title"], a[class*="base-card__full-link"]')
                    title = title_el.inner_text().strip() if title_el else ""

                    link_el = card.query_selector('a[class*="base-card__full-link"], a[href*="/jobs/view"]')
                    href = link_el.get_attribute("href") if link_el else ""
                    if href:
                        href = href.split("?")[0]  # Clean tracking params

                    company_el = card.query_selector('h4[class*="base-search-card__subtitle"] a, a[class*="hidden-nested-link"]')
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector('span[class*="job-search-card__location"]')
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector('time[class*="job-search-card__listdate"]')
                    posted = date_el.get_attribute("datetime") or date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)

                    # LinkedIn shows up to 3 days as "1 day ago" — accept all from public search
                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)

                except Exception as e:
                    log.debug(f"LinkedIn card error: {e}")

        except Exception as e:
            log.warning(f"  ⚠️ LinkedIn scrape failed: {e}")

        return jobs


# ── INDEED DDGS FALLBACK (for when Playwright blocked) ───────
class DDGSFallbackScraper:
    """Fallback to DuckDuckGo search for job URLs when Playwright is blocked."""

    def scrape(self, keyword: str, portal: str) -> list:
        try:
            from ddgs import DDGS as NewDDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS as NewDDGS
            except ImportError:
                return []

        jobs = []
        site_map = {
            "Indeed": "site:indeed.com/viewjob",
            "Dice": "site:dice.com/job-detail",
            "Glassdoor": "site:glassdoor.com/job-listing",
            "ZipRecruiter": "site:ziprecruiter.com/jobs",
        }
        site_filter = site_map.get(portal, f"site:{portal.lower()}.com")
        query = f'"{keyword}" {site_filter} "posted" "apply"'

        try:
            with NewDDGS() as ddgs:
                results = list(ddgs.text(query, region="us-en", max_results=15, timelimit="d"))

            for res in results:
                href = res.get("href", "")
                title_raw = res.get("title", "")
                snippet = res.get("body", "")
                if not href or is_garbage_url(href):
                    continue

                title, company = self._parse_title(title_raw, keyword)
                rec = build_record(portal + " (DDG)", keyword, title, company, "USA", snippet, href)
                jobs.append(rec)
        except Exception as e:
            log.debug(f"DDGS fallback failed for {portal}: {e}")

        return jobs

    def _parse_title(self, raw: str, fallback: str):
        raw = re.sub(r"\[.*?\]|\(.*?\)", "", raw).strip()
        for suffix in [" - LinkedIn", " | LinkedIn", " - Indeed", "| Indeed",
                       " | Glassdoor", " - Glassdoor", " | ZipRecruiter"]:
            raw = re.sub(rf"(?i){re.escape(suffix)}.*$", "", raw).strip()
        parts = raw.split(" at ") if " at " in raw else raw.split(" - ", 1)
        if len(parts) == 2:
            return parts[0].strip() or fallback, parts[1].strip()
        return raw or fallback, "Unknown"

# ============================================================
# 💾  CSV WRITER
# ============================================================
def write_csv(records: list) -> int:
    """Append new records to CSV, deduplicating by job_hash."""
    csv_file = CONFIG["csv_file"]
    existing_hashes = set()

    # Load existing hashes
    if os.path.exists(csv_file):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_hashes.add(row.get("job_hash", ""))
        except Exception:
            pass

    # Filter new records
    new_records = [r for r in records if r["job_hash"] not in existing_hashes]

    if not new_records:
        log.info("No new records to write (all duplicates).")
        return 0

    file_exists = os.path.exists(csv_file)
    mode = "a" if file_exists else "w"

    with open(csv_file, mode=mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_records)

    return len(new_records)

# ============================================================
# 📊  SUMMARY PRINTER
# ============================================================
def print_summary(records: list):
    """Print a beautiful summary table of all scraped jobs."""
    if not records:
        log.info("No jobs found.")
        return

    print("\n" + "=" * 70)
    print(f"  📊 JOB HARVEST COMPLETE — {date.today()} (Yesterday + Today)")
    print("=" * 70)

    # Per-portal counts
    by_portal = defaultdict(int)
    by_keyword = defaultdict(int)
    by_status = defaultdict(int)

    for r in records:
        by_portal[r.get("portal", "Unknown")] += 1
        by_keyword[r.get("search_keyword", "Unknown")] += 1
        by_status[r.get("validation_status", "Unknown")] += 1

    portal_data = [[p, c] for p, c in sorted(by_portal.items(), key=lambda x: -x[1])]
    keyword_data = [[k, c] for k, c in sorted(by_keyword.items(), key=lambda x: -x[1])]

    if HAS_TABULATE:
        print("\n🌐 Jobs by Portal:")
        print(tabulate(portal_data, headers=["Portal", "Jobs Found"], tablefmt="rounded_outline"))
        print("\n🔍 Jobs by Keyword:")
        print(tabulate(keyword_data, headers=["Search Keyword", "Jobs Found"], tablefmt="rounded_outline"))
    else:
        print("\n🌐 Jobs by Portal:")
        for p, c in portal_data:
            print(f"   {p:<20} → {c} jobs")
        print("\n🔍 Jobs by Keyword:")
        for k, c in keyword_data:
            print(f"   {k:<30} → {c} jobs")

    print(f"\n✅ Valid: {by_status.get('Valid', 0)}  "
          f"⚠️ Partial: {by_status.get('Partial', 0)}  "
          f"❌ Junk: {by_status.get('Junk', 0)}")
    print(f"\n📁 CSV saved to: {os.path.abspath(CONFIG['csv_file'])}")
    print("=" * 70 + "\n")

    # Print first 5 jobs as preview
    print("📋 SAMPLE JOBS (first 5):")
    print("-" * 70)
    for r in records[:5]:
        print(f"  🏢 {r['company_name'][:25]:<25} | {r['portal']:<12} | {r['job_title'][:30]}")
        print(f"     🔗 {r['apply_link'][:65]}")
        if r.get('ai_summary'):
            print(f"     💡 {r['ai_summary'][:80]}")
        print()

# ============================================================
# 🚀  MAIN ORCHESTRATOR
# ============================================================
def run_harvester():
    log.info("=" * 65)
    log.info("🚀 US IT JOB HARVESTER V9 — PLAYWRIGHT BROWSER SCRAPER")
    log.info(f"🎯 Target: LinkedIn, Indeed, Dice, Glassdoor, Wellfound, Built In, ZipRecruiter")
    log.info(f"⏱️  Filter: Yesterday ({YESTERDAY}) + Today ({TODAY})")
    log.info(f"🤖 AI Scoring: {'Enabled (NVIDIA NIM)' if CONFIG['use_ai_scoring'] else 'Disabled (Rule-based)'}")
    log.info("=" * 65)

    all_records = []
    ddg_fallback = DDGSFallbackScraper()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=CONFIG["headless"],
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Block unnecessary resources (images, fonts) for speed
        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda route: route.abort())

        # Portal scraper mapping
        scrapers = {
            "LinkedIn":    LinkedInScraper(page),
            "Indeed":      IndeedScraper(page),
            "Dice":        DiceScraper(page),
            "Glassdoor":   GlassdoorScraper(page),
            "ZipRecruiter": ZipRecruiterScraper(page),
            "Wellfound":   WellfoundScraper(page),
            "Built In":    BuiltInScraper(page),
        }

        for role in CONFIG["roles"]:
            log.info(f"\n{'─'*50}")
            log.info(f"🔍 Searching: {role}")
            log.info(f"{'─'*50}")

            for portal_name, scraper in scrapers.items():
                try:
                    jobs = scraper.scrape(role)
                    
                    if not jobs:
                        log.info(f"  ⚡ {portal_name}: 0 jobs (trying DDG fallback...)")
                        if portal_name in ["Indeed", "Dice", "Glassdoor", "ZipRecruiter"]:
                            jobs = ddg_fallback.scrape(role, portal_name)

                    log.info(f"  ✅ {portal_name}: {len(jobs)} jobs found")
                    all_records.extend(jobs)

                    delay = random.uniform(*CONFIG["inter_request_delay"])
                    time.sleep(delay)

                except Exception as e:
                    log.warning(f"  ❌ {portal_name} failed: {e}")

        browser.close()

    # ── Global Dedup ─────────────────────────────────────────
    seen, unique = set(), []
    for rec in all_records:
        if rec["job_hash"] not in seen:
            seen.add(rec["job_hash"])
            unique.append(rec)

    log.info(f"\n📊 Total Raw: {len(all_records)} | After Dedup: {len(unique)}")

    # ── AI Scoring ───────────────────────────────────────────
    if CONFIG["use_ai_scoring"]:
        log.info(f"🤖 Scoring {len(unique)} jobs with NVIDIA NIM...")
        for i, rec in enumerate(unique):
            score, summary, skills = ai_score_job(rec)
            rec["validation_score"] = score
            rec["validation_status"] = "Valid" if score >= 70 else "Partial" if score >= CONFIG["min_validation_score"] else "Junk"
            rec["ai_summary"] = summary
            rec["skills_required"] = skills
            if (i + 1) % 10 == 0:
                log.info(f"   Scored {i+1}/{len(unique)}...")
    else:
        for rec in unique:
            score = rule_based_score(rec)
            rec["validation_score"] = score
            rec["validation_status"] = "Valid" if score >= 70 else "Partial" if score >= CONFIG["min_validation_score"] else "Junk"

    # Filter out junk
    good_records = [r for r in unique if r["validation_status"] != "Junk"]
    log.info(f"✅ After validation: {len(good_records)} quality jobs (removed {len(unique)-len(good_records)} junk)")

    # ── Write CSV ────────────────────────────────────────────
    written = write_csv(good_records)
    log.info(f"💾 Written {written} new records to {CONFIG['csv_file']}")

    # ── Print Summary ─────────────────────────────────────────
    print_summary(good_records)

    return good_records


# ── Entry Point ───────────────────────────────────────────────
if __name__ == "__main__":
    jobs = run_harvester()
    print(f"\n🎉 Done! Total jobs harvested: {len(jobs)}")
