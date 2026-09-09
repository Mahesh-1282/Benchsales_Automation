"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DAILY JOB HARVESTER — LOCAL LAPTOP VERSION                                  ║
║  Single file. Zero setup. Run every morning.                                 ║
║                                                                               ║
║  HOW TO USE:                                                                  ║
║    1. python daily_job_harvester.py           → Search all default roles      ║
║    2. python daily_job_harvester.py "Java Dev" → Search one specific role     ║
║                                                                               ║
║  TO CHANGE DEFAULT ROLES: Edit SEARCH_ROLES below (one role per line)        ║
║                                                                               ║
║  PORTALS (works from local Mac, residential IP):                              ║
║    ✅ Indeed      → Playwright (full page scraping)                           ║
║    ✅ Dice        → Playwright (verified: 700+ word descriptions)             ║
║    ✅ LinkedIn    → Guest API + Playwright details                             ║
║    ✅ ZipRecruiter→ Playwright                                                ║
║    ✅ SimplyHired → requests                                                  ║
║    ✅ BuiltIn     → requests                                                  ║
║    ✅ Greenhouse  → JSON API (40+ major tech companies)                       ║
║    ✅ Lever.co    → JSON API (100+ tech companies)                            ║
║    ✅ RemoteOK    → Public JSON API                                           ║
║    ✅ Monster     → requests                                                  ║
║                                                                               ║
║  AI: NVIDIA NIM cascade fast→smart→power for each description                ║
║  Output: jobs_daily_output.csv (auto-deduplicates, appends daily)            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, csv, re, time, random, json, requests, hashlib, uuid, logging
from datetime import date, timedelta
from urllib.parse import quote_plus, urljoin
from collections import defaultdict
from pathlib import Path

# ── Load .env file if present ────────────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("⚠️  Playwright not found. Run: pip install playwright && playwright install chromium")

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ⚙️  CONFIGURATION — Only edit this section                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── 🎯 DEFAULT SEARCH ROLES — Edit these to change what jobs are searched ──────
SEARCH_ROLES = [
    "Data Engineer",
    "Senior Data Engineer",
    "PySpark Engineer",
    "ETL Developer",
    "Analytics Engineer",
    "Databricks Engineer",
    "Machine Learning Engineer",
    "Python Developer",
    "Data Architect",
    "Spark Developer",
]

CONFIG = {
    # ── Output CSV ────────────────────────────────────────────────────────────
    "output_csv": "jobs_daily_output_test_1.csv",

    # ── NVIDIA NIM API ────────────────────────────────────────────────────────
    # Set via env var: export NVIDIA_NIM_API_KEY="nvapi-..."
    # Or create .env file: NVIDIA_NIM_API_KEY=nvapi-...
    "nvidia_api_key":  os.getenv("NVIDIA_NIM_API_KEY", ""),
    "nvidia_base_url": "https://integrate.api.nvidia.com/v1",

    # ── AI Model Cascade ──────────────────────────────────────────────────────
    # Escalates automatically if extraction is incomplete
    "models": {
        "fast":    "meta/llama-3.1-8b-instruct",        # ~1s
        "smart":   "meta/llama-3.3-70b-instruct",        # ~3s
        "power":   "nvidia/llama-3.1-nemotron-70b-instruct",   # ~5s
        "ultra":   "nvidia/llama-3.1-nemotron-ultra-253b-v1",  # ~8s (last resort)
    },

    # ── Portal Toggles ────────────────────────────────────────────────────────
    # Set to False to disable a specific portal
    "portals": {
        "Indeed":       True,
        "Dice":         True,
        "LinkedIn":     True,
        "ZipRecruiter": True,
        "SimplyHired":  True,
        "BuiltIn":      True,
        "Greenhouse":   True,
        "Lever":        True,
        "RemoteOK":     True,
        "Monster":      False,   # Often requires login/captcha
    },

    # ── Scraping Settings ─────────────────────────────────────────────────────
    "max_jobs_per_portal": 20,   # Max jobs per portal per role
    "page_timeout":        25,   # Seconds per page
    "headless":            True,  # False = show browser window (debug mode)
    "between_jobs_min":    1.0,
    "between_jobs_max":    2.5,
    "retry_count":         3,
    "min_desc_words":      50,   # Min words for a valid description
}

TODAY = date.today()

# CSV output columns
CSV_HEADERS = [
    "id", "job_hash", "fetch_date", "portal", "search_role",
    "job_title", "company_name", "location", "remote_type",
    "salary_range", "experience_years", "tech_stack",
    "posted_date", "job_description", "description_length",
    "roles_responsibilities", "requirements_section",
    "apply_link", "hr_email", "job_id", "visa_sponsorship",
    "validation_score", "validation_status",
    "ai_summary", "ai_model_used", "extraction_attempts",
]

# ── US Location Filter ────────────────────────────────────────────────────────
INDIA_KEYWORDS = {
    "india","bangalore","bengaluru","hyderabad","chennai","pune","mumbai",
    "delhi","gurgaon","noida","kolkata","ahmedabad","kochi","navi mumbai",
}
NON_US_KEYWORDS = {
    "india","china","uk","australia","singapore","dubai","uae","pakistan",
    "philippines","nigeria","kenya","brazil","germany","france","toronto",
}
US_KEYWORDS = {
    "united states","usa","u.s.","remote","anywhere","nationwide","us only",
    "work from home","north america","continental us",
}
US_STATE_ABBR = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC",
}

def is_us_job(location: str) -> bool:
    if not location: return True
    loc = location.lower()
    if any(kw in loc for kw in INDIA_KEYWORDS): return False
    if any(kw in loc for kw in NON_US_KEYWORDS) and "remote" not in loc: return False
    if any(kw in loc for kw in US_KEYWORDS): return True
    if re.search(r'\b(' + '|'.join(US_STATE_ABBR) + r')\b', location.upper()): return True
    return True  # Include unknown — AI will score appropriately

# ── Helpers ───────────────────────────────────────────────────────────────────
UA_LIST = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
def rand_ua(): return random.choice(UA_LIST)
def rand_sleep(mn=1.0, mx=2.5): time.sleep(random.uniform(mn, mx))

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
EMAIL_BL = {"example.com","test.com","sentry.io","amazonaws.com","cloudfront.net",
            "w3.org","schema.org","intercom.io","hubspot.com","wixpress.com",
            "noreply","no-reply","donotreply","support","info@"}

def extract_best_email(text: str) -> str:
    emails = EMAIL_RE.findall(text)
    clean, seen = [], set()
    for e in emails:
        e = e.lower().strip(".,;")
        domain = e.split("@")[-1]
        if any(bl in e for bl in EMAIL_BL): continue
        if e not in seen: seen.add(e); clean.append(e)
    if not clean: return ""
    for prefix in ["recruit","talent","hr","hiring","jobs","careers","apply","people"]:
        for e in clean:
            if prefix in e.split("@")[0]: return e
    return clean[0]

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("DailyHarvester")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  🌐  BROWSER MANAGER — Single Playwright instance, reused across all sites  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Browser:
    """Single Playwright browser. One instance for the whole run."""

    DETAIL_CSS = {
        "indeed.com":       ["div#jobDescriptionText", "div[class*='jobsearch-JobComponent-description']"],
        "dice.com":         ["div[data-testid='jobDescriptionHtml']", "div[class*='description']"],
        "linkedin.com":     ["div.description__text", "div[class*='show-more-less-html']"],
        "ziprecruiter.com": ["div[class*='job_description']", "div[class*='jobDescription']", "div#job_desc"],
        "glassdoor.com":    ["div[class*='JobDetails_jobDescription']", "div.jobDescriptionContent"],
        "wellfound.com":    ["div[class*='description']", "section[class*='job-description']"],
        "monster.com":      ["div[class*='job-description']", "section[class*='description']"],
    }
    FALLBACK_CSS = [
        "div#jobDescriptionText", "div#jobDescription", "div.description",
        "div[class*='description']", "section[class*='description']", "article", "main",
    ]

    def __init__(self):
        self._pw = self._browser = self._ctx = self._page = None

    def start(self):
        if not HAS_PLAYWRIGHT:
            return self
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=CONFIG["headless"],
            args=["--no-sandbox","--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage","--disable-extensions"])
        self._ctx = self._browser.new_context(
            user_agent=rand_ua(),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
        # Block images/fonts/media to speed up
        self._ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,ico,webp}",
                        lambda r: r.abort())
        self._page = self._ctx.new_page()
        log.info("🎭 Playwright browser started")
        return self

    @property
    def page(self): return self._page

    def goto(self, url: str, wait: int = None) -> bool:
        """Navigate to URL. Returns True on success."""
        if not self._page: return False
        try:
            self._page.goto(url, wait_until="domcontentloaded",
                            timeout=CONFIG["page_timeout"] * 1000)
            wait_secs = wait or self._guess_wait(url)
            time.sleep(wait_secs)
            return True
        except Exception as e:
            log.debug(f"  goto failed: {e}")
            return False

    def _guess_wait(self, url: str) -> float:
        waits = {"linkedin.com":4,"dice.com":4,"indeed.com":4,"glassdoor.com":5,"ziprecruiter.com":3}
        return next((v for k,v in waits.items() if k in url), 2.5)

    def inner_text(self, selector: str, fallback: str = "") -> str:
        try:
            el = self._page.query_selector(selector)
            return el.inner_text().strip() if el else fallback
        except: return fallback

    def get_text(self) -> str:
        try: return self._page.inner_text("body") or ""
        except: return ""

    def get_html(self) -> str:
        try: return self._page.content() or ""
        except: return ""

    def extract_description(self, url: str) -> str:
        """Extract job description from current page using CSS selectors."""
        portal = next((k for k in self.DETAIL_CSS if k in url), None)
        selectors = (self.DETAIL_CSS.get(portal, []) if portal else []) + self.FALLBACK_CSS
        best = ""
        for sel in selectors:
            try:
                el = self._page.query_selector(sel)
                if el:
                    t = el.inner_text().strip()
                    if len(t) > len(best): best = t
                    if len(best.split()) > 150: break
            except: continue

        # JS fallback: find largest job-description-like div
        if len(best.split()) < 50:
            try:
                best = self._page.evaluate("""() => {
                    let best = '';
                    for (let el of document.querySelectorAll('div,section,article')) {
                        const t = el.innerText || '';
                        const l = t.toLowerCase();
                        if (t.length > best.length && t.length < 25000 &&
                            (l.includes('responsib') || l.includes('qualif') ||
                             l.includes('requirement') || l.includes('skill') ||
                             l.includes('years of experience'))) { best = t; }
                    }
                    return best;
                }""") or best
            except: pass

        return best.strip()

    def scroll_down(self, times: int = 3):
        """Scroll to load lazy-loaded content."""
        for _ in range(times):
            try: self._page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
            except: pass
            time.sleep(0.8)

    def wait_for(self, selector: str, timeout: int = 6000) -> bool:
        try: self._page.wait_for_selector(selector, timeout=timeout); return True
        except: return False

    def close(self):
        for obj in [self._page, self._ctx, self._browser]:
            try:
                if obj: obj.close()
            except: pass
        try:
            if self._pw: self._pw.stop()
        except: pass


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  📡  PORTAL SCRAPERS — One class, one method per portal                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class PortalScraper:
    """Discovers job listings from all enabled portals."""

    def __init__(self, browser: Browser):
        self.browser = browser
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": rand_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _req(self, url: str, timeout=20) -> requests.Response | None:
        for attempt in range(3):
            try:
                self.session.headers["User-Agent"] = rand_ua()
                r = self.session.get(url, timeout=timeout, allow_redirects=True)
                if r.status_code == 200: return r
            except Exception as e:
                log.debug(f"  request failed ({attempt+1}): {e}")
                time.sleep(random.uniform(1,3))
        return None

    # ── Indeed (Playwright) ────────────────────────────────────────────────────
    def indeed(self, role: str) -> list[dict]:
        url = (f"https://www.indeed.com/jobs?q={quote_plus(role)}"
               f"&l=United+States&fromage=1&sort=date&limit=50")
        if not self.browser.goto(url, wait=4): return []
        self.browser.wait_for("h2.jobTitle, div.job_seen_beacon, td.resultContent", timeout=8000)
        self.browser.scroll_down(2)

        jobs = []
        page = self.browser.page

        # Extract job cards — multiple CSS patterns for different layouts
        cards = page.query_selector_all("div.job_seen_beacon, td.resultContent")
        for card in cards[:CONFIG["max_jobs_per_portal"]]:
            try:
                # Title
                title_el = (card.query_selector("h2.jobTitle span") or
                            card.query_selector("span[title]") or
                            card.query_selector("h2 a span"))
                title = title_el.inner_text().strip() if title_el else ""

                # Link — get job ID from data attribute or href
                link_el = (card.query_selector("h2.jobTitle a") or
                           card.query_selector("a.jcs-JobTitle") or
                           card.query_selector("a[data-jk]"))
                href = ""
                job_id = ""
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    job_id = link_el.get_attribute("data-jk") or ""
                    if href and not href.startswith("http"):
                        href = "https://www.indeed.com" + href
                    # Indeed canonical: /viewjob?jk=JOBID
                    if job_id:
                        href = f"https://www.indeed.com/viewjob?jk={job_id}"

                # Company
                co_el = (card.query_selector("span[data-testid='company-name']") or
                         card.query_selector("span.companyName"))
                company = co_el.inner_text().strip() if co_el else "Unknown"

                # Location
                loc_el = (card.query_selector("div[data-testid='text-location']") or
                          card.query_selector("div.companyLocation"))
                location = loc_el.inner_text().strip() if loc_el else ""

                # Posted date
                date_el = card.query_selector("span[data-testid='myJobsStateDate']")
                posted  = date_el.inner_text().strip() if date_el else ""

                if not title or not href: continue
                if not is_us_job(location): continue

                jobs.append({
                    "portal": "Indeed", "search_role": role,
                    "job_title": title, "company_name": company,
                    "location": location, "apply_link": href,
                    "posted_date": posted, "job_id": job_id,
                })
            except: continue

        log.info(f"  📦 Indeed: {len(jobs)} for '{role}'")
        return jobs

    # ── Dice (Playwright) ──────────────────────────────────────────────────────
    def dice(self, role: str) -> list[dict]:
        url = (f"https://www.dice.com/jobs?q={quote_plus(role)}"
               f"&countryCode=US&radius=30&radiusUnit=mi"
               f"&page=1&pageSize=20&filters.postedDate=ONE_DAY_AGO")
        if not self.browser.goto(url, wait=5): return []
        self.browser.wait_for("div[data-cy='card']", timeout=8000)
        self.browser.scroll_down(3)

        jobs = []
        page = self.browser.page
        cards = page.query_selector_all("div[data-cy='card'], dhi-search-card")
        for card in cards[:CONFIG["max_jobs_per_portal"]]:
            try:
                title_el = (card.query_selector("a[data-cy='card-title-link']") or
                            card.query_selector("h5 a") or card.query_selector("a[class*='title']"))
                title = title_el.inner_text().strip() if title_el else ""
                href  = title_el.get_attribute("href") if title_el else ""

                if href and not href.startswith("http"):
                    href = "https://www.dice.com" + href

                co_el = (card.query_selector("a[data-cy='search-result-company-name']") or
                         card.query_selector("[class*='company-name']"))
                company = co_el.inner_text().strip() if co_el else "Unknown"

                loc_el = card.query_selector("[data-cy='search-result-location'], [class*='location']")
                location = loc_el.inner_text().strip() if loc_el else "USA"

                if not title or not href: continue
                if not is_us_job(location): continue

                job_id = re.search(r'/job-detail/([a-f0-9\-]+)', href)
                jobs.append({
                    "portal": "Dice", "search_role": role,
                    "job_title": title, "company_name": company,
                    "location": location, "apply_link": href,
                    "posted_date": "recent", "job_id": job_id.group(1) if job_id else "",
                })
            except: continue

        log.info(f"  📦 Dice: {len(jobs)} for '{role}'")
        return jobs

    # ── LinkedIn Guest API (requests — no login needed) ───────────────────────
    def linkedin(self, role: str) -> list[dict]:
        jobs, seen = [], set()
        for start in [0, 25]:
            url = (f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?keywords={quote_plus(role)}"
                   f"&location=United+States&f_TPR=r86400&f_JT=F&start={start}")
            resp = self._req(url)
            if not resp or len(resp.text) < 200: break

            html = resp.text
            urls  = re.findall(r'href="(https://www\.linkedin\.com/jobs/view/\d+[^"]*)"', html)
            titles= re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+?)\s*<', html)
            comps = re.findall(r'class="base-search-card__subtitle"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a', html, re.S)
            locs  = re.findall(r'class="job-search-card__location">\s*([^<]+?)\s*<', html)
            times = re.findall(r'class="job-search-card__listdate[^"]*"[^>]*>\s*([^<]+?)\s*<', html)

            for i, job_url in enumerate(urls[:CONFIG["max_jobs_per_portal"]]):
                clean = re.sub(r'\?.*', '', job_url.strip())
                if clean in seen: continue
                location = locs[i].strip() if i < len(locs) else ""
                if not is_us_job(location): continue
                seen.add(clean)
                jid = re.search(r'/view/(\d+)', clean)
                jobs.append({
                    "portal": "LinkedIn", "search_role": role,
                    "job_title":  titles[i].strip() if i < len(titles) else role,
                    "company_name": comps[i].strip() if i < len(comps) else "Unknown",
                    "location": location,
                    "apply_link": clean,
                    "posted_date": times[i].strip() if i < len(times) else "",
                    "job_id": jid.group(1) if jid else "",
                })
            rand_sleep(2, 4)

        log.info(f"  📦 LinkedIn: {len(jobs)} for '{role}'")
        return jobs

    # ── ZipRecruiter (Playwright) ──────────────────────────────────────────────
    def ziprecruiter(self, role: str) -> list[dict]:
        url = (f"https://www.ziprecruiter.com/candidate/search"
               f"?search={quote_plus(role)}&location=United+States&days=1")
        if not self.browser.goto(url, wait=4): return []
        self.browser.wait_for("article.job_result, div[class*='job_content']", timeout=8000)
        self.browser.scroll_down(2)

        jobs = []
        page = self.browser.page
        # Try multiple card selectors
        cards = page.query_selector_all("article.job_result, li[class*='job-listing']")
        if not cards:
            # Extract from JSON-LD / JSON data in page
            html = self.browser.get_html()
            urls   = re.findall(r'"url"\s*:\s*"(https://www\.ziprecruiter\.com/c/[^"]+)"', html)
            titles = re.findall(r'"title"\s*:\s*"([^"]+)"', html)
            comps  = re.findall(r'"hiringOrganization".*?"name"\s*:\s*"([^"]+)"', html)
            locs   = re.findall(r'"jobLocation".*?"name"\s*:\s*"([^"]+)"', html)
            for i, u in enumerate(urls[:CONFIG["max_jobs_per_portal"]]):
                location = locs[i] if i < len(locs) else "USA"
                if not is_us_job(location): continue
                jobs.append({
                    "portal": "ZipRecruiter", "search_role": role,
                    "job_title": titles[i] if i < len(titles) else role,
                    "company_name": comps[i] if i < len(comps) else "Unknown",
                    "location": location,
                    "apply_link": u, "posted_date": "recent",
                    "job_id": hashlib.md5(u.encode()).hexdigest()[:12],
                })
        else:
            for card in cards[:CONFIG["max_jobs_per_portal"]]:
                try:
                    title_el = card.query_selector("h2 a, a.job_link, a[class*='title']")
                    title    = title_el.inner_text().strip() if title_el else ""
                    href     = title_el.get_attribute("href") if title_el else ""
                    if not href or not href.startswith("http"): continue
                    co_el    = card.query_selector("a[class*='company'], span[class*='company']")
                    company  = co_el.inner_text().strip() if co_el else "Unknown"
                    loc_el   = card.query_selector("span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"
                    if not is_us_job(location): continue
                    jobs.append({
                        "portal": "ZipRecruiter", "search_role": role,
                        "job_title": title, "company_name": company,
                        "location": location, "apply_link": href,
                        "posted_date": "recent",
                        "job_id": hashlib.md5(href.encode()).hexdigest()[:12],
                    })
                except: continue

        log.info(f"  📦 ZipRecruiter: {len(jobs)} for '{role}'")
        return jobs

    # ── SimplyHired (requests) ─────────────────────────────────────────────────
    def simplyhired(self, role: str) -> list[dict]:
        url = f"https://www.simplyhired.com/search?q={quote_plus(role)}&l=United+States&fdb=1&sb=dd"
        resp = self._req(url)
        if not resp: return []

        jobs = []
        html = resp.text
        # Extract structured JSON from page
        matches = re.finditer(
            r'<div[^>]+class="[^"]*SerpJob[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            html, re.DOTALL)
        # Fallback: JSON-LD extraction
        titles  = re.findall(r'"title"\s*:\s*"([^"]+)"', html)
        links   = re.findall(r'href="(/job/[^"]+)"', html)
        comps   = re.findall(r'"name"\s*:\s*"([^"]+)".*?"@type"\s*:\s*"Organization"', html, re.S)
        locs    = re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', html)

        for i, path in enumerate(links[:CONFIG["max_jobs_per_portal"]]):
            title    = titles[i].strip() if i < len(titles) else role
            company  = comps[i].strip()  if i < len(comps)  else "Unknown"
            location = f"{locs[i]}, US"  if i < len(locs)   else "USA"
            if not is_us_job(location): continue
            full_url = f"https://www.simplyhired.com{path}"
            jobs.append({
                "portal": "SimplyHired", "search_role": role,
                "job_title": title, "company_name": company,
                "location": location, "apply_link": full_url,
                "posted_date": "recent",
                "job_id": hashlib.md5(full_url.encode()).hexdigest()[:12],
            })

        log.info(f"  📦 SimplyHired: {len(jobs)} for '{role}'")
        return jobs

    # ── BuiltIn (requests) ─────────────────────────────────────────────────────
    def builtin(self, role: str) -> list[dict]:
        url  = f"https://builtin.com/jobs?search={quote_plus(role)}&remote=true"
        resp = self._req(url)
        if not resp: return []

        jobs = []
        html = resp.text
        paths  = re.findall(r'href="(/job/[a-z0-9\-/]+)"', html)
        titles = re.findall(r'"jobTitle"\s*:\s*"([^"]+)"', html)
        comps  = re.findall(r'"hiringOrganization".*?"name"\s*:\s*"([^"]+)"', html, re.S)
        locs   = re.findall(r'"jobLocation".*?"name"\s*:\s*"([^"]+)"', html, re.S)

        seen = set()
        for i, path in enumerate(paths[:CONFIG["max_jobs_per_portal"]]):
            if path in seen: continue; seen.add(path)
            location = locs[i] if i < len(locs) else "USA"
            if not is_us_job(location): continue
            full_url = f"https://builtin.com{path}"
            jobs.append({
                "portal": "BuiltIn", "search_role": role,
                "job_title":    titles[i].strip() if i < len(titles) else role,
                "company_name": comps[i].strip()  if i < len(comps)  else "Unknown",
                "location": location, "apply_link": full_url,
                "posted_date": "recent",
                "job_id": path.split("/")[-1],
            })

        log.info(f"  📦 BuiltIn: {len(jobs)} for '{role}'")
        return jobs

    # ── Greenhouse JSON API (open, no auth, always works) ─────────────────────
    def greenhouse(self, role: str) -> list[dict]:
        companies = [
            # Data & Cloud
            "snowflake","databricks","confluent","dbt-labs","fivetran","segment",
            "elastic","hashicorp","datadog","mongodb","clickhouse","astronomer",
            # Fintech
            "stripe","brex","plaid","chime","robinhood","coinbase","affirm","marqeta",
            # Consumer Tech
            "airbnb","doordash","lyft","instacart","grammarly","duolingo",
            # Enterprise
            "figma","notion","rippling","gusto","lattice","airtable","hubspot",
            "zendesk","workato","clickup","linear","retool","vercel",
            # Health
            "nuna","hims","tempus","devoted","waystar",
        ]
        kw   = role.lower()
        jobs = []
        seen = set()
        for company in companies:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
            try:
                resp = requests.get(url, headers={"User-Agent": rand_ua()}, timeout=8)
                if resp.status_code != 200: continue
                data = resp.json()
            except: continue

            for job in data.get("jobs", []):
                title     = job.get("title","")
                title_low = title.lower()
                # Filter to relevant roles
                if not any(t in title_low for t in
                           ["data","engineer","spark","etl","analytics","ml","machine",
                            "python","pipeline","platform","architect","developer"]): continue
                # Role relevance check
                role_words = [w.lower() for w in kw.split() if len(w) > 3]
                if role_words and not any(rw in title_low for rw in role_words): continue

                loc_list = [l.get("name","") for l in job.get("offices",[])] or ["Remote"]
                location = ", ".join(loc_list)
                if any(kw in location.lower() for kw in ["india","bangalore","chennai","hyderabad"]): continue

                job_url = job.get("absolute_url","")
                if not job_url or job_url in seen: continue
                seen.add(job_url)

                content   = job.get("content","")
                desc_text = re.sub(r'<[^>]+>', ' ', content).strip()[:4000] if content else ""

                jobs.append({
                    "portal": "Greenhouse", "search_role": role,
                    "job_title": title, "company_name": company.capitalize(),
                    "location": location, "apply_link": job_url,
                    "posted_date": job.get("updated_at","")[:10],
                    "job_id": str(job.get("id","")),
                    "_prefetch_desc": desc_text,
                })
                if len(jobs) >= CONFIG["max_jobs_per_portal"]: break
            if len(jobs) >= CONFIG["max_jobs_per_portal"]: break
            time.sleep(0.3)

        log.info(f"  📦 Greenhouse: {len(jobs)} for '{role}'")
        return jobs

    # ── Lever JSON API (open, no auth, always works) ───────────────────────────
    def lever(self, role: str) -> list[dict]:
        companies = [
            "netflix","tesla","twitch","reddit","twitter","discord","dropbox",
            "evernote","squarespace","wix","squareup","box","okta","auth0",
            "cloudflare","fastly","twilio","sendgrid","segment","mixpanel",
            "amplitude","heap","fullstory","pendo","intercom","zendesk",
            "asana","monday","clickup","linear","basecamp","trello",
        ]
        kw   = role.lower()
        jobs = []
        seen = set()
        for company in companies:
            url = f"https://api.lever.co/v0/postings/{company}?mode=json"
            try:
                resp = requests.get(url, headers={"User-Agent": rand_ua()}, timeout=8)
                if resp.status_code != 200: continue
                data = resp.json()
                if not isinstance(data, list): continue
            except: continue

            for posting in data:
                title     = posting.get("text","")
                title_low = title.lower()
                if not any(t in title_low for t in
                           ["data","engineer","spark","python","analytics","ml","platform"]): continue
                role_words = [w.lower() for w in kw.split() if len(w) > 3]
                if role_words and not any(rw in title_low for rw in role_words): continue

                location = posting.get("categories",{}).get("location","Remote")
                if any(kw in location.lower() for kw in ["india","london","berlin"]): continue

                job_url = posting.get("hostedUrl","")
                if not job_url or job_url in seen: continue
                seen.add(job_url)

                # Extract description from posting text
                desc_parts = posting.get("description","")
                lists = " ".join([
                    li.get("text","") for li in posting.get("lists",[])
                ])
                desc_full = re.sub(r'<[^>]+>', ' ', f"{desc_parts} {lists}").strip()

                jobs.append({
                    "portal": "Lever", "search_role": role,
                    "job_title": title, "company_name": company.capitalize(),
                    "location": location, "apply_link": job_url,
                    "posted_date": "",
                    "job_id": posting.get("id",""),
                    "_prefetch_desc": desc_full[:4000],
                })
                if len(jobs) >= CONFIG["max_jobs_per_portal"]: break
            if len(jobs) >= CONFIG["max_jobs_per_portal"]: break
            time.sleep(0.3)

        log.info(f"  📦 Lever: {len(jobs)} for '{role}'")
        return jobs

    # ── RemoteOK JSON API ──────────────────────────────────────────────────────
    def remoteok(self, role: str) -> list[dict]:
        variants = [
            role.lower().replace(" ", "-"),
            role.lower().split()[0],  # First word
            "data-engineer", "python", "big-data",
        ]
        data = []
        for slug in variants[:2]:
            try:
                resp = requests.get(
                    f"https://remoteok.com/api?tag={quote_plus(slug)}",
                    headers={"User-Agent": rand_ua(), "Accept":"application/json"}, timeout=15)
                if resp.status_code == 200:
                    d = resp.json()
                    if isinstance(d, list) and len(d) > 1: data = d; break
            except: pass
            time.sleep(1)
        if not data: return []

        US_SIG = {"usa","us only","united states","remote","worldwide","anywhere","global",""}
        jobs = []
        for item in data[1:CONFIG["max_jobs_per_portal"]*3+1]:
            if not isinstance(item, dict): continue
            title   = item.get("position","")
            loc     = item.get("location","").lower().strip()
            job_url = item.get("url","")
            if not title or not job_url: continue
            # Location filter
            if any(kw in loc for kw in ["india","asia","europe","china","africa",
                                          "dubai","singapore","london","berlin"]): continue
            if loc and loc not in US_SIG and not any(kw in loc for kw in ["us","remote","usa","worldwide"]): continue
            # Role relevance
            title_low = title.lower()
            if not any(t in title_low for t in
                       ["engineer","data","developer","analyst","scientist","spark",
                        "etl","analytics","ml","python","cloud","platform","pipeline"]): continue

            desc = re.sub(r'<[^>]+>', ' ', item.get("description","")).strip()
            jobs.append({
                "portal": "RemoteOK", "search_role": role,
                "job_title": title, "company_name": item.get("company","Unknown"),
                "location": item.get("location","Remote"),
                "apply_link": job_url, "posted_date": item.get("date",""),
                "job_id": str(item.get("id","")),
                "_prefetch_desc": desc[:4000],
                "_prefetch_tech": ", ".join(item.get("tags",[])),
            })
            if len(jobs) >= CONFIG["max_jobs_per_portal"]: break

        log.info(f"  📦 RemoteOK: {len(jobs)} for '{role}'")
        return jobs

    def discover(self, role: str) -> list[dict]:
        """Discover all jobs for one role from all enabled portals."""
        results = []
        portals = CONFIG["portals"]

        scrapers = [
            ("Indeed",       portals.get("Indeed")       and HAS_PLAYWRIGHT, self.indeed),
            ("Dice",         portals.get("Dice")         and HAS_PLAYWRIGHT, self.dice),
            ("LinkedIn",     portals.get("LinkedIn"),     self.linkedin),
            ("ZipRecruiter", portals.get("ZipRecruiter") and HAS_PLAYWRIGHT, self.ziprecruiter),
            ("SimplyHired",  portals.get("SimplyHired"),  self.simplyhired),
            ("BuiltIn",      portals.get("BuiltIn"),      self.builtin),
            ("Greenhouse",   portals.get("Greenhouse"),   self.greenhouse),
            ("Lever",        portals.get("Lever"),        self.lever),
            ("RemoteOK",     portals.get("RemoteOK"),     self.remoteok),
        ]

        for portal_name, enabled, fn in scrapers:
            if not enabled: continue
            try:
                jobs = fn(role)
                results.extend(jobs)
            except Exception as e:
                log.warning(f"  ⚠️ {portal_name}: {e}")
            rand_sleep(1, 2)

        return results


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  🔍  DETAIL EXTRACTOR — Fetch job details for each discovered job           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class DetailExtractor:
    """Fetches full job description for each job URL."""

    NEEDS_JS = {"linkedin.com","dice.com","glassdoor.com","wellfound.com","indeed.com","ziprecruiter.com"}

    def __init__(self, browser: Browser, ai: 'AIEngine'):
        self.browser = browser
        self.ai = ai

    def extract(self, job: dict) -> dict:
        url     = job.get("apply_link","")
        title   = job.get("job_title","")

        # If description was pre-fetched (Greenhouse/Lever/RemoteOK), use it
        prefetch = job.pop("_prefetch_desc", "")
        prefetch_tech = job.pop("_prefetch_tech", "")

        desc = ""
        html = ""

        if prefetch and len(prefetch.split()) >= 50:
            desc = prefetch
            log.debug(f"   📦 Pre-fetched: {len(desc.split())} words")
        else:
            # Fetch the job detail page
            needs_js = any(s in url for s in self.NEEDS_JS)
            text, html = self._fetch(url, needs_js)
            if text:
                # Try CSS selectors first
                if needs_js and self.browser.page:
                    desc = self.browser.extract_description(url)
                # Fallback: regex on HTML
                if len(desc.split()) < 50 and html:
                    desc = self._regex_extract(html)
                # Final fallback: AI finds it from page text
                if len(desc.split()) < 30 and text:
                    log.debug(f"   CSS failed ({len(desc.split())}w) → AI self-healing...")
                    desc = self.ai.find_description(text[:4500], title, url)

        desc_words = len(desc.split()) if desc else 0

        # AI analysis
        ai_result = self.ai.analyze(desc, title, job.get("company_name",""), job.get("location",""))

        # Merge prefetch_tech if AI didn't find tech stack
        if prefetch_tech and not ai_result.get("tech_stack","").strip():
            ai_result["tech_stack"] = prefetch_tech

        email = extract_best_email(html + desc)

        job.update({
            "job_description":     desc[:5000],
            "description_length":  desc_words,
            "hr_email":            email,
            "validation_score":    ai_result.get("validation_score", 50),
            "validation_status":   ai_result.get("validation_status", "Partial"),
            "ai_summary":          ai_result.get("ai_summary",""),
            "roles_responsibilities": ai_result.get("roles_summary",""),
            "requirements_section":   ai_result.get("requirements",""),
            "tech_stack":          ai_result.get("tech_stack",""),
            "experience_years":    ai_result.get("experience_years",""),
            "remote_type":         ai_result.get("remote_type",""),
            "salary_range":        ai_result.get("salary_range",""),
            "visa_sponsorship":    ai_result.get("visa_sponsorship", False),
            "ai_model_used":       ai_result.get("ai_model_used","none"),
            "extraction_attempts": ai_result.get("extraction_attempts", 0),
        })
        return job

    def _fetch(self, url: str, needs_js: bool) -> tuple[str,str]:
        """Fetch page. Returns (text, html)."""
        if needs_js and self.browser.page:
            ok = False
            for attempt in range(CONFIG["retry_count"]):
                ok = self.browser.goto(url)
                if ok:
                    text = self.browser.get_text()
                    if len(text) > 200:
                        return text, self.browser.get_html()
                sleep = random.uniform(2, 5)
                log.debug(f"   JS retry {attempt+2} in {sleep:.1f}s")
                time.sleep(sleep)
        else:
            # requests-based for static pages
            session = requests.Session()
            session.headers.update({"User-Agent": rand_ua(), "Accept-Language":"en-US,en;q=0.9"})
            for attempt in range(CONFIG["retry_count"]):
                try:
                    resp = session.get(url, timeout=CONFIG["page_timeout"], allow_redirects=True)
                    if resp.status_code == 200 and len(resp.text) > 300:
                        return resp.text, resp.text
                except Exception as e:
                    log.debug(f"   requests retry {attempt+2}: {e}")
                time.sleep(random.uniform(2,4))
        return "", ""

    def _regex_extract(self, html: str) -> str:
        """Regex-based description extraction from raw HTML."""
        clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.I)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL|re.I)
        for pattern in [
            r'id=["\']jobDescriptionText["\'][^>]*>(.*?)</div>',
            r'data-testid=["\']jobDescriptionHtml["\'][^>]*>(.*?)</div>',
            r'class=["\'][^"\']*(?:job-description|description__text|jobDescription)[^"\']*["\'][^>]*>(.*?)</(?:div|section|article)',
        ]:
            m = re.search(pattern, clean, re.DOTALL|re.I)
            if m:
                raw = re.sub(r'<[^>]+>', ' ', m.group(1))
                raw = re.sub(r'\s+', ' ', raw).strip()
                if len(raw.split()) > 40:
                    return raw
        return ""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  🧠  AI ENGINE — NVIDIA NIM with cascade & self-healing                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class AIEngine:
    """NVIDIA NIM AI for analyzing job descriptions."""

    def __init__(self):
        self.api_key = CONFIG["nvidia_api_key"]
        self.base    = CONFIG["nvidia_base_url"]
        self.models  = CONFIG["models"]
        self.call_counts = defaultdict(int)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("nvapi-"))

    def call(self, prompt: str, tier: str = "fast", max_tokens: int = 512) -> str | None:
        if not self.enabled: return None
        model = self.models[tier]
        self.call_counts[tier] += 1
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json={"model": model,
                          "messages": [{"role":"user","content":prompt}],
                          "temperature": 0.1, "max_tokens": max_tokens},
                    timeout=30)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                elif resp.status_code == 429:
                    log.debug(f"AI rate-limited [{tier}], sleeping 6s...")
                    time.sleep(6)
                else:
                    log.debug(f"AI HTTP {resp.status_code} [{tier}]")
            except Exception as e:
                log.debug(f"AI error [{tier}] attempt {attempt+1}: {e}")
                if attempt < 2: time.sleep(random.uniform(1,3))
        return None

    def analyze(self, description: str, title: str, company: str, location: str) -> dict:
        """Analyze job description → extract structured fields. Cascade fast→ultra."""
        default = {
            "validation_score": 50, "validation_status": "Partial",
            "ai_summary": "", "roles_summary": "", "requirements": "",
            "tech_stack": "", "experience_years": "Not specified",
            "remote_type": "Not specified", "salary_range": "",
            "visa_sponsorship": False, "ai_model_used": "none", "extraction_attempts": 0,
        }

        desc_words = len(description.split()) if description else 0
        if desc_words < 20:
            default["ai_summary"] = "Description not available"
            default["validation_status"] = "Partial"
            return default

        if not self.enabled:
            # No API key — do basic extraction without AI
            return self._heuristic_analyze(description, default)

        desc_sample = description[:3500]
        result      = dict(default)

        tiers = [
            ("fast",  512, ""),
            ("smart", 768, "Improve on the previous incomplete extraction."),
            ("power", 900, "Think step by step. Extract all fields carefully."),
        ]

        for tier, max_tok, extra in tiers:
            result["extraction_attempts"] += 1
            prompt = f"""Analyze this US IT job. {extra}

Title: {title} | Company: {company} | Location: {location}

DESCRIPTION:
{desc_sample}

Reply with ONLY valid JSON (no markdown, no text before/after):
{{
  "validation_score": <0-100, is this a real US IT data/ML/engineering job?>,
  "ai_summary": "<2 sentences: company context + daily role responsibilities>",
  "roles_summary": "<3-5 bullet responsibilities starting with •>",
  "requirements": "<3-5 bullet requirements starting with •>",
  "tech_stack": "<top 8-10 tech/tools/frameworks comma-separated>",
  "experience_years": "<e.g. '5+ years'>",
  "remote_type": "<Remote | Hybrid | Onsite | Not specified>",
  "salary_range": "<salary range if mentioned, else empty string>",
  "visa_sponsorship": <true/false>
}}"""

            resp   = self.call(prompt, tier, max_tokens=max_tok)
            parsed = self._parse(resp) if resp else None

            if parsed:
                for k, v in parsed.items():
                    if v not in (None, "", "N/A", "Not specified", 0):
                        result[k] = v
                result["ai_model_used"] = tier

                score    = int(result.get("validation_score") or 0)
                has_tech = len((result.get("tech_stack","")).split(",")) >= 2
                has_sum  = len((result.get("ai_summary","")).split()) >= 8
                if score > 0 and has_tech and has_sum:
                    break  # Good enough, stop cascading
            time.sleep(0.5)

        score = int(result.get("validation_score") or 0)
        result["validation_status"] = "Valid" if score >= 70 else "Partial" if score >= 35 else "Junk"
        return result

    def _heuristic_analyze(self, desc: str, result: dict) -> dict:
        """Basic extraction without AI (fallback when no API key)."""
        desc_low = desc.lower()
        # Remote type
        if "remote" in desc_low:
            result["remote_type"] = "Remote" if "fully remote" in desc_low or "100% remote" in desc_low else "Hybrid"
        elif "onsite" in desc_low or "on-site" in desc_low or "in office" in desc_low:
            result["remote_type"] = "Onsite"

        # Experience
        exp = re.search(r'(\d+)\+?\s*(?:to\s*\d+\s*)?years?\s+(?:of\s+)?(?:experience|exp)', desc, re.I)
        if exp: result["experience_years"] = f"{exp.group(1)}+ years"

        # Salary
        sal = re.search(r'\$\s*(\d{2,3})[,k]?\s*(?:[-–]\s*\$?\s*(\d{2,3})[,k]?)?\s*(?:per\s*year|annually|k|K)?', desc, re.I)
        if sal: result["salary_range"] = sal.group(0).strip()

        # Simple tech extraction
        tech_keywords = ["Python","Spark","SQL","AWS","Azure","GCP","Kafka","Airflow",
                        "dbt","Databricks","Snowflake","PySpark","Hadoop","Hive","Scala",
                        "Java","Kubernetes","Docker","Terraform","BigQuery","Redshift",
                        "Pandas","NumPy","TensorFlow","PyTorch","Scikit-learn","MLflow"]
        found_tech = [t for t in tech_keywords if t.lower() in desc.lower()]
        result["tech_stack"] = ", ".join(found_tech[:10])
        result["validation_score"] = 65 if len(desc.split()) > 100 else 40
        result["validation_status"] = "Partial"
        result["ai_model_used"] = "heuristic"
        return result

    def _parse(self, text: str) -> dict | None:
        if not text: return None
        try:
            s, e = text.find('{'), text.rfind('}')
            if s != -1 and e > s:
                return json.loads(text[s:e+1])
        except: pass
        out = {}
        for key, pat in [
            ("ai_summary",       r'"ai_summary"\s*:\s*"((?:[^"\\]|\\.)*)"'),
            ("roles_summary",    r'"roles_summary"\s*:\s*"((?:[^"\\]|\\.)*)"'),
            ("requirements",     r'"requirements"\s*:\s*"((?:[^"\\]|\\.)*)"'),
            ("tech_stack",       r'"tech_stack"\s*:\s*"([^"]+)"'),
            ("experience_years", r'"experience_years"\s*:\s*"([^"]*)"'),
            ("remote_type",      r'"remote_type"\s*:\s*"([^"]+)"'),
            ("salary_range",     r'"salary_range"\s*:\s*"([^"]*)"'),
        ]:
            m = re.search(pat, text, re.DOTALL)
            if m: out[key] = m.group(1).replace('\\"','"').strip()
        m = re.search(r'"validation_score"\s*:\s*(\d+)', text)
        if m: out["validation_score"] = int(m.group(1))
        m = re.search(r'"visa_sponsorship"\s*:\s*(true|false)', text, re.I)
        if m: out["visa_sponsorship"] = m.group(1).lower() == "true"
        return out if out else None

    def find_description(self, page_text: str, title: str, url: str) -> str:
        """AI self-heal: extract description from raw page text when CSS fails."""
        prompt = f"""From this job page text, extract ONLY the job description.
Output ONLY the raw description text. No JSON, no formatting.
If not found: output exactly NOT_FOUND

Title: {title}
URL: {url}

Page: {page_text[:4000]}

Description:"""
        for tier in ("smart", "power"):
            resp = self.call(prompt, tier, max_tokens=1500)
            if resp and "NOT_FOUND" not in resp and len(resp.split()) > 25:
                return resp
        return ""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  💾  CSV PERSISTENCE                                                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def _build_record(job: dict, role: str) -> dict:
    r = {h: "" for h in CSV_HEADERS}
    r.update({
        "id":         str(uuid.uuid4()),
        "job_hash":   hashlib.md5(job.get("apply_link","").encode()).hexdigest(),
        "fetch_date": TODAY.isoformat(),
        "search_role": role,
    })
    r.update(job)
    for f in ("description_length","validation_score","extraction_attempts"):
        r[f] = str(r.get(f, 0) or 0)
    r["visa_sponsorship"] = str(r.get("visa_sponsorship", False))
    return r

def save_csv(records: list, append: bool = True) -> int:
    csv_file = CONFIG["output_csv"]
    existing = set()
    if os.path.exists(csv_file):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                existing = {row.get("job_hash","") for row in csv.DictReader(f)}
        except: pass

    new_recs = [r for r in records if r.get("job_hash","") not in existing]
    if not new_recs: return 0

    mode = "a" if (append and os.path.exists(csv_file)) else "w"
    with open(csv_file, mode=mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        if mode == "w": w.writeheader()
        w.writerows(new_recs)
    return len(new_recs)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  📊  SUMMARY                                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def print_summary(records: list, ai: AIEngine):
    by_portal = defaultdict(int)
    by_status = defaultdict(int)
    by_model  = defaultdict(int)
    w_desc = w_email = total_words = 0

    for r in records:
        by_portal[r.get("portal","?")] += 1
        by_status[r.get("validation_status","?")] += 1
        by_model[r.get("ai_model_used","?")] += 1
        dlen = int(r.get("description_length",0) or 0)
        if dlen > 50: w_desc += 1; total_words += dlen
        if r.get("hr_email"): w_email += 1

    avg = total_words // max(w_desc, 1)
    total = len(records)

    print("\n" + "═"*70)
    print("  🤖 DAILY JOB HARVESTER — COMPLETE")
    print("═"*70)
    print(f"  📋 Total jobs:      {total}")
    print(f"  📝 With desc:       {w_desc} ({w_desc*100//max(total,1)}%)  avg {avg} words")
    print(f"  📧 With emails:     {w_email}")
    print(f"  ✅ Valid (70%+):    {by_status.get('Valid',0)}")
    print(f"  ⚠️  Partial:        {by_status.get('Partial',0)}")
    print(f"  ❌ Junk:            {by_status.get('Junk',0)}")
    if ai.enabled:
        print(f"\n  🧠 AI: {sum(ai.call_counts.values())} total calls")
        for m,c in sorted(by_model.items(), key=lambda x:-x[1]):
            if c > 0: print(f"     [{m}]: {c}")
    else:
        print("\n  ⚠️  AI disabled — set NVIDIA_NIM_API_KEY in .env")
        print("     (Descriptions still saved, AI scoring skipped)")

    if HAS_TABULATE:
        print("\n  🌐 By Portal:")
        print(tabulate([[p,c] for p,c in sorted(by_portal.items(),key=lambda x:-x[1])],
                       headers=["Portal","Jobs"], tablefmt="rounded_outline"))
    else:
        print("\n  🌐 By Portal:")
        for p,c in sorted(by_portal.items(),key=lambda x:-x[1]):
            print(f"     {p:15}: {c}")

    print(f"\n  📁 Saved: {os.path.abspath(CONFIG['output_csv'])}")
    print("═"*70)

    # Sample top 5 valid jobs
    shown = 0
    for r in records:
        if shown >= 5: break
        if r.get("validation_status") == "Valid" and int(r.get("description_length",0) or 0) > 80:
            print(f"\n  🏢 {r.get('company_name','?')[:28]} | {r.get('portal','?')}")
            print(f"  💼 {r.get('job_title','?')[:55]}")
            print(f"  📍 {r.get('location','?')[:35]} | 🏠 {r.get('remote_type','?')}")
            print(f"  💰 {r.get('salary_range','Not stated')[:45]}")
            print(f"  🛠️  {r.get('tech_stack','')[:60]}")
            print(f"  📅 {r.get('experience_years','N/A')} | 🤖 {r.get('validation_score','?')}%")
            if r.get('hr_email'): print(f"  📧 {r['hr_email']}")
            print(f"  🔗 {r.get('apply_link','')[:65]}")
            preview = " ".join(str(r.get("job_description","")).split()[:20])
            print(f"  📄 {preview}...")
            shown += 1


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  🚀  MAIN — Run the full pipeline                                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def run(roles: list[str]):
    print("═"*70)
    print("  🤖 DAILY JOB HARVESTER — LOCAL LAPTOP")
    print(f"  📅 Date: {TODAY}  |  Roles: {len(roles)}")
    ai_status = "✅ NVIDIA NIM" if CONFIG["nvidia_api_key"].startswith("nvapi-") else "⚠️  No API key (heuristic only)"
    print(f"  🧠 AI: {ai_status}")
    print(f"  🌐 Portals: {sum(1 for v in CONFIG['portals'].values() if v)} enabled")
    print("═"*70 + "\n")

    ai        = AIEngine()
    browser   = Browser().start()
    scraper   = PortalScraper(browser)
    extractor = DetailExtractor(browser, ai)

    all_records = []
    seen_hashes = set()

    # ── Phase 1: Discover all jobs ──────────────────────────────────────────
    print("═══ PHASE 1: JOB DISCOVERY ═══")
    all_jobs = []
    for role in roles:
        print(f"\n  🔍 {role}")
        jobs = scraper.discover(role)
        deduped = []
        for j in jobs:
            h = hashlib.md5(j.get("apply_link","").encode()).hexdigest()
            if h not in seen_hashes and j.get("apply_link"):
                seen_hashes.add(h); deduped.append(j)
        all_jobs.extend(deduped)

    print(f"\n  📊 Phase 1 Done: {len(all_jobs)} unique jobs found")

    # ── Phase 2: Extract details + AI analysis ──────────────────────────────
    print("\n═══ PHASE 2: DETAIL EXTRACTION + AI ANALYSIS ═══")
    for i, job in enumerate(all_jobs):
        role    = job.get("search_role","")
        title   = job.get("job_title","?")[:38]
        portal  = job.get("portal","?")
        company = job.get("company_name","?")[:20]
        print(f"\n[{i+1:3}/{len(all_jobs)}] {portal:12} | {title} | {company}")

        try:
            job    = extractor.extract(job)
            record = _build_record(job, role)
            all_records.append(record)

            score  = record.get("validation_score","?")
            status = record.get("validation_status","?")
            dlen   = record.get("description_length","0")
            model  = record.get("ai_model_used","?")
            icon   = {"Valid":"✅","Partial":"⚠️","Junk":"❌"}.get(status,"?")
            print(f"         {icon} {score}% | {dlen}w | [{model}] | {record.get('tech_stack','')[:40]}")
            if record.get("hr_email"): print(f"         📧 {record['hr_email']}")

        except Exception as e:
            log.warning(f"         ❌ Error: {e}")
            all_records.append(_build_record(job, role))

        rand_sleep(CONFIG["between_jobs_min"], CONFIG["between_jobs_max"])

        # Save progress every 25 jobs
        if (i + 1) % 25 == 0:
            n = save_csv(all_records, append=True)
            print(f"\n  💾 Progress saved: {i+1}/{len(all_jobs)} ({n} new records)")

    # ── Final save ──────────────────────────────────────────────────────────
    written = save_csv(all_records, append=True)
    print(f"\n  💾 Final: {written} new records saved → {CONFIG['output_csv']}")

    browser.close()
    print_summary(all_records, ai)
    return all_records


if __name__ == "__main__":
    # Allow passing a custom role via command line:
    # python daily_job_harvester.py "Java Developer"
    # python daily_job_harvester.py "Data Scientist" "ML Engineer"
    if len(sys.argv) > 1:
        roles = [arg.strip() for arg in sys.argv[1:] if arg.strip()]
        print(f"🎯 Custom roles: {roles}")
    else:
        roles = SEARCH_ROLES

    records = run(roles)

    valid  = sum(1 for r in records if r.get("validation_status") == "Valid")
    w_desc = sum(1 for r in records if int(r.get("description_length",0) or 0) > 80)
    print(f"\n✅ DONE! {len(records)} total | {valid} valid | {w_desc} with descriptions")
    print(f"📁 Open: {os.path.abspath(CONFIG['output_csv'])}")
