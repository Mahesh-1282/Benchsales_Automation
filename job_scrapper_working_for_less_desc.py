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

import os, csv, hashlib, uuid, re, time, random, logging, json, requests, sys
from pathlib import Path
from datetime import datetime, date, timedelta
import ssl
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin, quote_plus
import playwright_stealth

# Import local db_utils
sys.path.insert(0, str(Path(__file__).parent.parent / "03_databricks_app"))
from db_utils import execute_sql, query_df, insert_row, esc, update_row

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
# ── Token Tracking ─────────────────────────────────────────
TOKEN_TRACKER = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_api_calls": 0,
    "calls_by_model": {},
    "tokens_per_job": [],
}

def track_tokens(model: str, input_tokens: int, output_tokens: int, job_hash: str = ""):
    """Track token usage per API call."""
    TOKEN_TRACKER["total_input_tokens"] += input_tokens
    TOKEN_TRACKER["total_output_tokens"] += output_tokens
    TOKEN_TRACKER["total_api_calls"] += 1
    TOKEN_TRACKER["calls_by_model"][model] = TOKEN_TRACKER["calls_by_model"].get(model, 0) + 1
    if job_hash:
        TOKEN_TRACKER["tokens_per_job"].append({
            "job_hash": job_hash, "model": model,
            "input": input_tokens, "output": output_tokens
        })

def print_token_summary():
    """Print token usage summary."""
    t = TOKEN_TRACKER
    print("\n" + "═" * 50)
    print("🔢 TOKEN USAGE SUMMARY")
    print("═" * 50)
    print(f"  Total API Calls     : {t['total_api_calls']}")
    print(f"  Total Input Tokens  : {t['total_input_tokens']:,}")
    print(f"  Total Output Tokens : {t['total_output_tokens']:,}")
    print(f"  Total Tokens        : {t['total_input_tokens'] + t['total_output_tokens']:,}")
    if t['tokens_per_job']:
        avg_per_job = (t['total_input_tokens'] + t['total_output_tokens']) / max(len(set(j['job_hash'] for j in t['tokens_per_job'])), 1)
        print(f"  Avg Tokens/Job      : {avg_per_job:,.0f}")
    for model, count in t['calls_by_model'].items():
        print(f"  {model}: {count} calls")
    print("═" * 50)

CONFIG = {
    # ── Output ──────────────────────────────────────────────
    "csv_file": "jobs_v10_output_test_2.csv",

    # ── NVIDIA NIM AI ───────────────────────────────────────
    "nvidia_api_key": os.getenv("NVIDIA_NIM_API_KEY", "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"),
    # llama-3.2-11b-vision-instruct: fast, reliable, currently supported on this API tier
    "nvidia_simple_model": "meta/llama-3.2-11b-vision-instruct",
    "nvidia_ultra_model":  "meta/llama-3.2-11b-vision-instruct",
    # ── Gemini Fallback ─────────────────────────────────────
    "gemini_api_key": os.getenv("GEMINI_API_KEY", "AIzaSyAl9_gGM_Kf_hIIMM2u0tpdbvygKpDX-r0"),
    "use_ai_scoring": True,

    # ── Site Toggle ──────────────────────────────────────────
    "enable_all_sites": True,

    # ── Target Roles ─────────────────────────────────────────
    "roles": [r.strip() for r in os.getenv("SCRAPER_KEYWORDS", "Data Engineer, Senior Data Engineer").split(",") if r.strip()],

    # ── Scraping ─────────────────────────────────────────────
    "max_jobs_per_portal_per_role": 25,
    "page_timeout_ms": 30_000,
    "scroll_delay": 1.5,
    "inter_request_delay": (1.5, 3.0),
    "min_validation_score": 40,
    "headless": True,

    # ── Detail Fetch ─────────────────────────────────────────
    "detail_fetch_min_score": 50,
    "detail_fetch_workers": 3,
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
# 🤖  NVIDIA NIM AI CALLER (with Gemini fallback)
# ============================================================
def _call_nvidia_nim(prompt: str, model: str = None, max_tokens: int = 400, job_hash: str = "") -> dict | None:
    """Call NVIDIA NIM API. Returns parsed JSON response or None on failure."""
    api_key = CONFIG["nvidia_api_key"]
    if not api_key:
        return None
    if model is None:
        model = CONFIG["nvidia_simple_model"]
    
    fallback_models = [model, "meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct"]
    est_input = len(prompt) // 4
    
    for current_model in fallback_models:
        for retry in range(3):
            try:
                resp = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": current_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": max_tokens,
                    },
                    timeout=60  # Large descriptions and max_tokens=1500 need more headroom
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    usage = data.get("usage", {})
                    track_tokens(
                        current_model,
                        usage.get("prompt_tokens", est_input),
                        usage.get("completion_tokens", len(content) // 4),
                        job_hash
                    )
                    return {"content": content, "status": "ok"}
                elif resp.status_code in (429, 529):
                    wait_time = 5 * (retry + 1)
                    log.debug(f"  ⚠️ NVIDIA NIM overloaded ({resp.status_code}) for {current_model}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    log.debug(f"  ⚠️ NVIDIA NIM error {resp.status_code}: {resp.text[:100]} for {current_model}")
                    break # Try next model
            except Exception as e:
                log.debug(f"  ⚠️ NVIDIA NIM call error: {e} for {current_model}")
                break # Try next model
        
    return None

def _call_gemini(prompt: str, max_tokens: int = 400, response_mime: str = "application/json", job_hash: str = "") -> dict | None:
    """Fallback: Call Gemini API. Returns parsed response or None."""
    api_key = CONFIG["gemini_api_key"]
    if not api_key:
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_tokens,
            }
        }
        resp = requests.post(url, json=payload, timeout=20, verify=False)
        if resp.status_code == 200:
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            est_input = len(prompt) // 4
            track_tokens("gemini-1.5-flash", est_input, len(content) // 4, job_hash)
            return {"content": content, "status": "ok"}
        elif resp.status_code == 429:
            log.debug("  ⚠️ Gemini rate limit hit.")
        else:
            log.debug(f"  ⚠️ Gemini error {resp.status_code}")
    except Exception as e:
        log.debug(f"  ⚠️ Gemini call error: {e}")
    return None

def _ai_call(prompt: str, max_tokens: int = 400, use_ultra: bool = False, job_hash: str = "") -> str | None:
    """
    Unified AI caller:
      Tries NVIDIA NIM first. If rate limited or fails, falls back to Gemini immediately.
    """
    model = CONFIG["nvidia_ultra_model"] if use_ultra else CONFIG["nvidia_simple_model"]

    # 1. Try NVIDIA NIM
    result = _call_nvidia_nim(prompt, model=model, max_tokens=max_tokens, job_hash=job_hash)
    if result:
        return result["content"]

    # 2. Fallback to Gemini
    log.warning(f"  ⚠️ NVIDIA NIM failed for job {job_hash}. Falling back to Gemini...")
    fallback_result = _call_gemini(prompt, max_tokens=max_tokens, job_hash=job_hash)
    if fallback_result:
        return fallback_result["content"]

    log.debug("  ⚠️ AI API unavailable (both NIM and Gemini failed).")
    return None

# ============================================================
# 🔧  ROBUST JSON PARSER  (handles Gemini markdown fences)
# ============================================================
def _parse_ai_json(content: str) -> dict | None:
    """
    Parse JSON from AI response robustly.
    Handles:  raw JSON  |  ```json...```  |  ``` ... ```  |  prose + JSON block
    """
    if not content:
        return None
    # Strip markdown code fences
    clean = re.sub(r"```(?:json)?\s*", "", content, flags=re.I).replace("```", "").strip()
    # Try direct parse first
    try:
        return json.loads(clean)
    except Exception:
        pass
    # Find first { ... } block (greedy)
    m = re.search(r'\{.*\}', clean, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    # Last resort: find first [ ... ] (for list responses)
    m2 = re.search(r'\[.*\]', clean, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group())
        except Exception:
            pass
    return None

# ============================================================
# 🤖  AI SCORER (Gemini primary, NVIDIA fallback)
# ============================================================
def ai_score_job(job: dict) -> tuple[int, str, str, str, bool]:
    """
    Score a job using AI (Gemini primary, NVIDIA fallback).
    Returns: (score, ai_summary, tech_stack, experience_years, visa_sponsorship)
    """
    desc = job.get("job_description") or ""
    if len(desc) < 50:
        desc = f"Job Title: {job.get('job_title')}. Company: {job.get('company_name')}."

    prompt = f"""Analyze this US IT job posting. Return ONLY valid JSON, no markdown, no extra text.
Title: {job.get('job_title', '')}
Company: {job.get('company_name', '')}
Location: {job.get('location', '')}
Description: {desc}

Return exactly this JSON (no code fences, no extra words):
{{
  "score": <0-100 integer>,
  "is_real_job": <true or false>,
  "summary": "<2-sentence summary>",
  "tech_stack": "<comma-separated skills, e.g. Python, FastAPI, AWS, Docker>",
  "experience_years": "<e.g. 5+ years or Not specified>",
  "remote_type": "<Remote|Hybrid|Onsite|Not specified>",
  "visa_sponsorship": <true or false>
}}"""

    content = _ai_call(prompt, max_tokens=400, job_hash=job.get("job_hash", ""))
    if content:
        data = _parse_ai_json(content)
        if data and isinstance(data, dict):
            tech = data.get("tech_stack", "")
            if isinstance(tech, list):
                tech = ", ".join(str(t) for t in tech)
            try:
                return (
                    int(data.get("score", 50)),
                    str(data.get("summary", "")),
                    str(tech),
                    str(data.get("experience_years", "Not specified")),
                    bool(data.get("visa_sponsorship", False)),
                )
            except (ValueError, TypeError) as e:
                log.debug(f"AI score value error: {e}")

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
        "job_description":  desc if desc else "",
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
# 🤖  AI AUTO-HEALER (Nemotron Ultra for repair)
# ============================================================
SELECTOR_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "05_scraper_testing", "selector_cache.json")

def _load_selector_cache() -> dict:
    """Load cached AI-healed selectors from previous runs."""
    try:
        if os.path.exists(SELECTOR_CACHE_FILE):
            with open(SELECTOR_CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_selector_cache(cache: dict):
    """Save healed selectors for future runs."""
    try:
        os.makedirs(os.path.dirname(SELECTOR_CACHE_FILE), exist_ok=True)
        with open(SELECTOR_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def ai_heal_selectors(page, portal_name, keyword):
    """
    3-Tier Auto-Healing:
    Tier 1: Check selector cache from previous successful heals
    Tier 2: AI-suggested CSS selector from DOM class analysis (Nemotron Ultra)
    Tier 3: Falls through to ai_extract_jobs_from_dom() in caller
    """
    # Tier 1: Check cache
    cache = _load_selector_cache()
    cached_selector = cache.get(portal_name)
    if cached_selector:
        log.info(f"  💾 Using cached selector for {portal_name}: {cached_selector}")
        cards = page.query_selector_all(cached_selector)
        if cards:
            log.info(f"  ✅ Cached selector worked! Found {len(cards)} cards")
            return cached_selector
        else:
            log.warning(f"  ⚠️ Cached selector no longer works for {portal_name}")
    
    # Tier 2: AI-suggested selector using Nemotron Ultra
    log.warning(f"  🤖 Auto-Healer (Nemotron Ultra) analyzing {portal_name} DOM for '{keyword}'...")
    try:
        dom_snippet = page.evaluate('''() => {
            let candidates = new Set();
            document.querySelectorAll('div, li, article, section, a').forEach(el => {
                let cls = el.className;
                if (typeof cls === 'string' && (cls.includes('job') || cls.includes('card') || cls.includes('result') || cls.includes('listing') || cls.includes('posting'))) {
                    candidates.add(el.tagName.toLowerCase() + '.' + cls.trim().replace(/\\s+/g, '.'));
                }
            });
            return Array.from(candidates).slice(0, 20).join('\n');
        }''')
        
        if not dom_snippet:
            return None
            
        prompt = f"""You are a CSS selector expert. The job portal {portal_name} has changed its HTML structure.
Below are the CSS classes found on the page. Pick the SINGLE BEST CSS selector that would match job listing cards.

Classes found:
{dom_snippet}

Respond with ONLY the CSS selector string. No markdown, no explanation, no backticks."""
        
        content = _ai_call(prompt, max_tokens=30, use_ultra=True)
        if content:
            selector = content.strip().replace('`', '').replace('\n', '')
            log.info(f"  🤖 AI Suggested Selector: {selector}")
            # Validate the selector works
            try:
                test_cards = page.query_selector_all(selector)
                if test_cards:
                    log.info(f"  ✅ AI selector validated! Found {len(test_cards)} cards")
                    # Save to cache
                    cache[portal_name] = selector
                    _save_selector_cache(cache)
                    return selector
                else:
                    log.warning(f"  ⚠️ AI selector found 0 cards, will fall through to Tier 3")
            except Exception:
                log.warning(f"  ⚠️ AI selector invalid: {selector}")
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

# ── LINKEDIN GUEST API — Full Description Without Login ──────
def fetch_linkedin_description(job_url: str, job_id: str = "") -> str:
    """
    Fetch full LinkedIn job description using multiple strategies:
    1. LinkedIn Guest API endpoint (no login required, returns full HTML)
    2. Playwright browser with "See more" button click
    Returns the full description text or empty string.
    """
    desc = ""

    # ── Strategy 1: LinkedIn Guest API (fastest, no login needed) ──
    if not job_id:
        m = re.search(r"-(\d{7,})(?:[/?]|$)", job_url)
        if m:
            job_id = m.group(1)

    if job_id:
        guest_api_urls = [
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
            f"https://www.linkedin.com/jobs/view/{job_id}/",
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.linkedin.com/jobs/",
        }
        for api_url in guest_api_urls:
            try:
                resp = requests.get(api_url, headers=headers, timeout=15, verify=False)
                if resp.status_code == 200 and len(resp.text) > 200:
                    # Parse HTML from guest API response
                    from html.parser import HTMLParser

                    class _TextExtractor(HTMLParser):
                        def __init__(self):
                            super().__init__()
                            self.texts = []
                            self._skip_tags = {"script", "style", "noscript"}
                            self._current_skip = 0

                        def handle_starttag(self, tag, attrs):
                            if tag in self._skip_tags:
                                self._current_skip += 1

                        def handle_endtag(self, tag):
                            if tag in self._skip_tags and self._current_skip > 0:
                                self._current_skip -= 1

                        def handle_data(self, data):
                            if self._current_skip == 0:
                                stripped = data.strip()
                                if stripped:
                                    self.texts.append(stripped)

                    parser = _TextExtractor()
                    parser.feed(resp.text)
                    candidate = "\n".join(parser.texts)

                    # Also try to find description div specifically
                    desc_patterns = [
                        r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                        r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>',
                    ]
                    for pat in desc_patterns:
                        dm = re.search(pat, resp.text, re.DOTALL | re.I)
                        if dm:
                            inner_html = dm.group(1)
                            # Strip inner tags
                            clean = re.sub(r"<[^>]+>", " ", inner_html)
                            clean = re.sub(r"\s+", " ", clean).strip()
                            clean = re.sub(r"&#\d+;", "", clean)
                            clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
                            if len(clean) > 200:
                                log.info(f"  ✅ LinkedIn Guest API (regex) got {len(clean)} chars for job {job_id}")
                                return clean

                    if len(candidate) > 300:
                        log.info(f"  ✅ LinkedIn Guest API (text) got {len(candidate)} chars for job {job_id}")
                        return candidate
            except Exception as e:
                log.debug(f"  LinkedIn guest API error ({api_url}): {e}")

    # ── Strategy 2: Playwright with 'See more' click ──────────
    log.debug(f"  LinkedIn guest API failed for {job_url}, trying Playwright...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                      "--disable-infobars", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())

            try:
                page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                time.sleep(3)

                # Click "See more" / "Show more" expand buttons
                expand_selectors = [
                    "button.show-more-less-html__button",
                    "button[class*='show-more-less']",
                    "button[aria-label*='See more']",
                    "button[aria-label*='Show more']",
                    "span.show-more-less-html__button--more",
                    ".see-more-jobs-button",
                    "footer button",
                ]
                for sel in expand_selectors:
                    try:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            time.sleep(1.5)
                            log.debug(f"  ✅ Clicked expand button: {sel}")
                            break
                    except Exception:
                        pass

                # Now extract — try multiple selectors in order of reliability
                linkedin_desc_selectors = [
                    # Logged-in view selectors
                    "div.jobs-description__content div.jobs-description-content__text",
                    "div.jobs-description-content",
                    "div.jobs-description__content",
                    # Public/guest view selectors
                    "div.description__text--rich",
                    "div.description__text",
                    "div[class*='show-more-less-html__markup']",
                    "section.description div",
                    "div[class*='description__text']",
                    # About the job section
                    "section[class*='description']",
                    "div.decorated-job-posting__details",
                    # Fallback broad selectors
                    "div[class*='job-description']",
                    "article div[class*='description']",
                ]

                for sel in linkedin_desc_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            candidate = el.inner_text().strip()
                            if len(candidate) > len(desc):
                                desc = candidate
                            if len(desc) > 300:
                                log.info(f"  ✅ LinkedIn Playwright got {len(desc)} chars via: {sel}")
                                break
                    except Exception:
                        pass

                # If still short, get entire 'About the job' section via JS
                if len(desc) < 200:
                    try:
                        desc_js = page.evaluate("""
                            () => {
                                // Try common LinkedIn containers
                                let selectors = [
                                    '.jobs-description__content',
                                    '.description__text',
                                    '[class*="show-more-less-html"]',
                                    '.jobs-box__html-content',
                                    'section.description',
                                ];
                                for (let sel of selectors) {
                                    let el = document.querySelector(sel);
                                    if (el && el.innerText && el.innerText.length > 200) {
                                        return el.innerText.trim();
                                    }
                                }
                                // Last resort: find longest text block
                                let best = '';
                                document.querySelectorAll('div, section, article').forEach(el => {
                                    let t = el.innerText || '';
                                    if (t.length > best.length && t.length < 15000) best = t;
                                });
                                return best.trim();
                            }
                        """)
                        if desc_js and len(desc_js) > len(desc):
                            desc = desc_js
                            log.info(f"  ✅ LinkedIn JS extraction got {len(desc)} chars")
                    except Exception as e:
                        log.debug(f"  LinkedIn JS extraction error: {e}")

            except Exception as e:
                log.debug(f"  LinkedIn Playwright page error: {e}")
            finally:
                try:
                    context.close()
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        log.debug(f"  LinkedIn Playwright outer error: {e}")

    return desc


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
            if not cards:
                # LinkedIn may show different layout
                cards = self.page.query_selector_all("li.jobs-search-results__list-item, div[data-job-id]")
            log.info(f"  📦 LinkedIn: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h3.base-search-card__title, h3[class*='job-card-list__title'], a[class*='job-card-list__title']")
                    title = title_el.inner_text().strip() if title_el else ""

                    link_el = card.query_selector("a.base-card__full-link, a[class*='job-card-list__title'], a[data-control-name='search_srp_result']")
                    href = link_el.get_attribute("href") or "" if link_el else ""
                    if href:
                        href = href.split("?")[0]

                    company_el = card.query_selector("h4.base-search-card__subtitle a, a.hidden-nested-link, span[class*='job-card-container__company-name'], a[class*='job-card-container__company-name']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("span.job-search-card__location, span[class*='job-card-container__metadata-item']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("time.job-search-card__listdate, time[datetime]")
                    posted = date_el.get_attribute("datetime") or date_el.inner_text().strip() if date_el else ""

                    # Extract job ID from URL
                    job_id_m = re.search(r"-(\d{7,})(?:[/?]|$)", href)
                    job_id = job_id_m.group(1) if job_id_m else ""

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
                raw_text = self.page.inner_text("body")
                return ai_extract_jobs_from_dom(raw_text, "Indeed", keyword)
                
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
                raw_text = self.page.inner_text("body")
                return ai_extract_jobs_from_dom(raw_text, "Glassdoor", keyword)
                
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
                # Use AI Fallback extraction
                raw_text = self.page.inner_text("body")
                return ai_extract_jobs_from_dom(raw_text, "Wellfound", keyword)
                
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
    """Extract roles/responsibilities with RELAXED regex — handles both \n and whitespace."""
    patterns = [
        r"(?:key\s+)?responsibilities[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits|about\s+(?:us|the)|who\s+you|experience|education|preferred|nice\s+to\s+have|compensation)|\Z)",
        r"(?:what\s+you(?:'ll)?\s+do|your\s+role|day[\s\-.]to[\s\-.]day|in\s+this\s+role)[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits|about|what\s+you(?:'ll)?\s+need|who\s+you)|\Z)",
        r"(?:role\s+(?:overview|description|summary))[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits)|\Z)",
        r"(?:duties\s+(?:and|&)\s+responsibilities|job\s+duties)[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:requirements|qualifications|skills|benefits)|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 50: return s  # Removed character limit
    return ""

def extract_requirements(text: str) -> str:
    """Extract requirements with RELAXED regex — handles both \n and whitespace."""
    patterns = [
        r"(?:requirements|qualifications|must\s+have|required\s+skills|what\s+you(?:'ll)?\s+need|minimum\s+qualifications)[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:benefits|about\s+(?:us|the)|what\s+we|nice\s+to\s+have|preferred|compensation|responsibilities|how\s+to\s+apply)|\Z)",
        r"(?:you(?:'ll)?\s+(?:need|bring)|we(?:'re)?\s+looking\s+for)[\s:]*[:\-\u2013]?\s*(.*?)(?=(?:benefits|about|nice\s+to\s+have|preferred|compensation)|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            s = m.group(1).strip()
            if len(s) > 50: return s  # Removed character limit
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
    """Re-score a job using its full description. Uses _parse_ai_json for robust parsing."""
    desc = job.get("job_description") or ""
    title = job.get("job_title", "")
    company = job.get("company_name", "")
    location = job.get("location", "")

    if len(desc) < 50:
        return {
            "validation_score": 60, "validation_status": "Partial",
            "ai_summary": "No description available", "roles_summary": "",
            "tech_stack": job.get("tech_stack", ""), "experience_years": "Not specified",
            "remote_type": "Remote" if "remote" in (title + location).lower() else "Not specified",
            "visa_sponsorship": False, "salary_mentioned": "",
        }

    prompt = f"""Analyze this US IT job posting. Return ONLY valid JSON, no markdown, no extra text.

Title: {title}
Company: {company}
Location: {location}
Description:
{desc}

Return exactly this JSON:
{{
  "score": <0-100 integer>,
  "is_real_job": <true or false>,
  "summary": "<2-sentence summary>",
  "roles_summary": "<3-5 bullet key responsibilities>",
  "roles_responsibilities": "<detailed list of roles and responsibilities from the description>",
  "requirements_section": "<detailed list of requirements from the description>",
  "tech_stack": "<all skills comma-separated, e.g. Python, FastAPI, AWS, Docker>",
  "experience_years": "<e.g. 5+ years or Not specified>",
  "remote_type": "<Remote|Hybrid|Onsite|Not specified>",
  "salary_mentioned": "<salary string or empty>",
  "visa_sponsorship": <true or false>
}}"""

    content = _ai_call(prompt, max_tokens=1500, job_hash=job.get("job_hash", ""))
    if content:
        data = _parse_ai_json(content)
        if data and isinstance(data, dict):
            score = int(data.get("score", 60))
            tech = data.get("tech_stack", "")
            if isinstance(tech, list):
                tech = ", ".join(str(t) for t in tech)
            try:
                return {
                    "validation_score": score,
                    "validation_status": "Valid" if score >= 70 else "Partial" if score >= 40 else "Junk",
                    "ai_summary": str(data.get("summary", "")),
                    "roles_summary": str(data.get("roles_summary", "")),
                    "roles_responsibilities": str(data.get("roles_responsibilities", "")),
                    "requirements_section": str(data.get("requirements_section", "")),
                    "tech_stack": str(tech),
                    "experience_years": str(data.get("experience_years", "Not specified")),
                    "remote_type": str(data.get("remote_type", "Not specified")),
                    "salary_mentioned": str(data.get("salary_mentioned", "")),
                    "visa_sponsorship": bool(data.get("visa_sponsorship", False)),
                }
            except (ValueError, TypeError):
                pass

    # Fallback to regex extractors on complete AI failure
    exp_years = "Not specified"
    tech_stack = job.get("tech_stack", "")
    
    if len(desc) > 50:
        exp_match = re.search(r'(\d+)\+?\s*years?\s*(?:of)?\s*experience', desc, re.IGNORECASE)
        if exp_match:
            exp_years = f"{exp_match.group(1)}+ years"
            
        common_techs = ["python", "java", "aws", "azure", "gcp", "docker", "kubernetes", "react", "angular", "vue", "sql", "nosql", "spark", "kafka", "snowflake", "databricks"]
        found_techs = [t.title() for t in common_techs if re.search(rf'\b{t}\b', desc, re.IGNORECASE)]
        if found_techs:
            tech_stack = ", ".join(found_techs)

    return {
        "validation_score": 60, "validation_status": "Partial",
        "ai_summary": "AI unavailable", "roles_summary": "",
        "roles_responsibilities": "", "requirements_section": "",
        "tech_stack": tech_stack, "experience_years": exp_years,
        "remote_type": "Remote" if "remote" in desc.lower() else "Not specified", "visa_sponsorship": False, "salary_mentioned": "",
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
            # Use dedicated LinkedIn fetcher (Guest API + Playwright fallback)
            job_id_m = re.search(r"-(\d{7,})(?:[/?]|$)", url)
            job_id = job_id_m.group(1) if job_id_m else ""
            desc = fetch_linkedin_description(url, job_id)
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

        result["job_description"] = desc if desc else ""

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


# ── Portal-specific selectors ────────────────
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

PORTAL_WAIT = {
    "dice.com": 5, "linkedin.com": 4, "indeed.com": 3,
    "glassdoor.com": 4, "wellfound.com": 5, "builtin.com": 3,
    "simplyhired.com": 3, "ziprecruiter.com": 3,
    "monster.com": 3, "greenhouse.io": 2, "lever.co": 2,
    "hiring.cafe": 4, "careerbuilder.com": 3, "welcometothejungle.com": 4,
}

def extract_linkedin_poster_profile(page, url: str) -> str:
    """Try to extract LinkedIn profile URL of the job poster for messaging."""
    if "linkedin.com" not in url:
        return ""
    try:
        poster_selectors = [
            "a[href*='/in/'][class*='poster']",
            "a[href*='/in/'][class*='hiring']",
            "a[href*='/in/'][class*='recruiter']",
            "div[class*='hiring-team'] a[href*='/in/']",
            "section[class*='hiring'] a[href*='/in/']",
            "div[class*='poster'] a[href*='/in/']",
            "a.base-card__full-link[href*='/in/']",
            "div[class*='hirer'] a[href*='/in/']",
            "a[href*='linkedin.com/in/']",
        ]
        for sel in poster_selectors:
            try:
                els = page.query_selector_all(sel)
                for el in els:
                    href = el.get_attribute("href") or ""
                    if "/in/" in href and "/jobs/" not in href:
                        profile_url = href.split("?")[0]
                        if not profile_url.startswith("http"):
                            profile_url = "https://www.linkedin.com" + profile_url
                        return profile_url
            except Exception:
                pass
    except Exception:
        pass
    return ""

def fetch_details_parallel(records: list, _browser=None) -> list:
    """
    Robust detail fetcher using portal-specific selectors.
    Scrapes the full job description and other fields reliably.
    """
    to_fetch = records
    log.info(f"🔍 Fetching details for {len(to_fetch)} jobs...")

    hash_to_record = {r["job_hash"]: r for r in records}
    completed = 0

    def fetch_one(rec):
        from playwright.sync_api import sync_playwright
        detail = {
            "job_description": "", "roles_responsibilities": "",
            "requirements_section": "", "salary_range": "",
            "experience_years": "", "detail_fetched": False,
            "hr_email": "", "company_website": "",
            "company_career_url": "", "easy_apply_link": ""
        }
        url = rec["apply_link"]
        portal_key = next((k for k in PORTAL_SELECTORS if k in url), "default")
        wait_secs = next((v for k, v in PORTAL_WAIT.items() if k in url), 4)
        selectors = PORTAL_SELECTORS.get(portal_key, []) + UNIVERSAL_FALLBACKS

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
                page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())
                
                # Apply human-like delays
                time.sleep(random.uniform(1.5, 3.5))
                
                desc = ""
                html = ""
                
                # ── LinkedIn: try Guest API first ──
                if "linkedin.com" in url:
                    job_id_m = re.search(r"-(\d{7,})(?:[/?]|$)", url)
                    li_job_id = job_id_m.group(1) if job_id_m else rec.get("job_id", "")
                    if li_job_id:
                        try:
                            guest_resp = requests.get(
                                f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{li_job_id}",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=15, verify=False
                            )
                            if guest_resp.status_code == 200 and len(guest_resp.text) > 200:
                                html = guest_resp.text
                                for pat in [r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                                            r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>',
                                            r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>']:
                                    dm = re.search(pat, html, re.DOTALL | re.I)
                                    if dm:
                                        clean = re.sub(r"<[^>]+>", " ", dm.group(1))
                                        clean = re.sub(r"\s+", " ", clean).strip()
                                        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
                                        if len(clean) > 200:
                                            desc = clean
                                            break
                        except Exception as e:
                            log.debug(f"LinkedIn API error: {e}")
                
                # ── Browser scraping if Guest API failed or not LinkedIn ──
                if len(desc) < 100:
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["detail_fetch_timeout_ms"])
                        time.sleep(wait_secs)
                        try:
                            page.wait_for_selector("h1, div[class*='description'], article, div#jobDescriptionText", timeout=8000)
                        except Exception:
                            pass
                        html = page.content()

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

                        # Smart JS fallback
                        if len(desc) < 100:
                            try:
                                desc_js = page.evaluate("""() => {
                                    let best = '';
                                    for (let el of document.querySelectorAll('div,section,article')) {
                                        const t = el.innerText || '';
                                        if (t.length > best.length && t.length < 15000) {
                                            const l = t.toLowerCase();
                                            if (l.includes('responsib') || l.includes('qualif') || l.includes('experience') || l.includes('skills')) best = t;
                                        }
                                    }
                                    return best;
                                }""")
                                if desc_js and len(desc_js) > len(desc):
                                    desc = desc_js
                            except Exception:
                                pass
                    except Exception as e:
                        log.debug(f"Browser fetch error: {e}")

                    # ── Cloudflare Block Detection ──
                    if "Additional Verification Required" in desc or "Ray ID" in desc or "Cloudflare" in desc:
                        desc = ""
                        
                    # ── PRIMP Fallback (Bypasses Cloudflare / TLS Fingerprinting) ──
                    if len(desc) < 100:
                        try:
                            import primp
                            from bs4 import BeautifulSoup
                            client = primp.Client(impersonate="chrome_120")
                            resp = client.get(url, timeout=15)
                            if resp.status_code == 200:
                                html = resp.text
                                soup = BeautifulSoup(html, 'html.parser')
                                
                                primp_desc = ""
                                for sel in selectors:
                                    els = soup.select(sel)
                                    if els:
                                        for el in els:
                                            text = el.get_text(separator=' ', strip=True)
                                            if len(text) > len(primp_desc) and len(text) > 80:
                                                primp_desc = text
                                            if len(primp_desc) > 500:
                                                break
                                    if len(primp_desc) > 500:
                                        break
                                
                                if len(primp_desc) < 100:
                                    # bs4 smart fallback
                                    best = ""
                                    for tag in soup.find_all(['div', 'section', 'article']):
                                        t = tag.get_text(separator=' ', strip=True)
                                        if len(t) > len(best) and len(t) < 15000:
                                            l = t.lower()
                                            if 'responsib' in l or 'qualif' in l or 'experience' in l or 'skills' in l:
                                                best = t
                                    if best:
                                        primp_desc = best
                                
                                if len(primp_desc) > 80 and "Additional Verification Required" not in primp_desc:
                                    desc = primp_desc
                        except Exception as e:
                            log.debug(f"Primp fallback error: {e}")


                if len(desc) > 80:
                    detail["job_description"] = desc  # Full desc, no slicing
                    detail["description_length"] = len(desc.split())
                    detail["roles_responsibilities"] = extract_roles(desc)
                    detail["requirements_section"] = extract_requirements(desc)
                    detail["salary_range"] = extract_salary(desc)
                    detail["experience_years"] = extract_experience(desc)
                    detail["detail_fetched"] = True
                    
                    emails = extract_emails(html) if html else []
                    if emails: detail["hr_email"] = best_hr_email(emails)
                    
                    try:
                        co_el = page.query_selector("a[href*='career'], a[href*='job']")
                        if co_el:
                            co_url = co_el.get_attribute("href") or ""
                            if co_url and "http" in co_url:
                                detail["company_career_url"] = co_url
                    except Exception: pass
                    
                    if "linkedin.com" in url:
                        detail["easy_apply_link"] = extract_linkedin_poster_profile(page, url)

                context.close()
                browser.close()
        except Exception as e:
            log.debug(f"Parallel fetch wrapper error: {e}")
            
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


def ai_extract_jobs_from_dom(raw_text: str, portal_name: str, keyword: str) -> list:
    """Tier 3 Fallback: Extract jobs from raw page text using AI (Nemotron Ultra)."""
    prompt = f"""Extract job postings from this text from {portal_name} for the keyword '{keyword}'.
Return a valid JSON list of dictionaries. Each dictionary must have:
"title": <job title>,
"company": <company name>,
"location": <location>,
"salary": <salary>,
"job_description": <full job description, roles and responsibilities in text format without html tags>,
"tech_stack": <tech stack comma separated>,
"remote_type": <remote or onsite>,
"link": <url if available, else "">

Return ONLY valid JSON.
Text:
{raw_text[:8000]}"""
    
    content = _ai_call(prompt, max_tokens=2000, use_ultra=True)
    if content:
        try:
            m = re.search(r'\[.*\]', content, re.DOTALL)
            if m:
                jobs = json.loads(m.group())
            else:
                jobs = json.loads(content)
            
            records = []
            for j in jobs:
                rec = build_record(
                    portal=portal_name,
                    keyword=keyword,
                    title=j.get("title", ""),
                    company=j.get("company", ""),
                    location=j.get("location", ""),
                    desc=j.get("job_description", ""),
                    url=j.get("link", ""),
                    salary=j.get("salary", "")
                )
                rec["tech_stack"] = j.get("tech_stack", "")
                rec["remote_type"] = j.get("remote_type", "")
                records.append(rec)
            log.info(f"  🤖 AI DOM Extraction: {len(records)} jobs from {portal_name}")
            return records
        except Exception as e:
            log.warning(f"  [AI DOM Extraction] Parse error: {e}")
    return []

class HiringCafeScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "HiringCafe")
        
    def scrape(self, keyword: str) -> list:
        log.info(f"  [HiringCafe] Started search for '{keyword}'...")
        jobs = []
        try:
            url = f"https://hiring.cafe/?search={quote_plus(keyword)}"
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            
            # Try traditional DOM extraction first
            items = self.page.query_selector_all("a[href*='/job/']")
            for item in items[:15]:
                try:
                    title = item.inner_text().split("\n")[0] if item.inner_text() else "Unknown"
                    link = urljoin("https://hiring.cafe", item.get_attribute("href"))
                    if len(title) > 3:
                        jobs.append(build_record(
                            self.portal, keyword, title, "Unknown", "USA", "", link
                        ))
                except Exception:
                    pass
                    
            if not jobs:
                log.info("  [HiringCafe] Standard selectors found 0 jobs. Falling back to Ultra AI DOM extraction...")
                raw_text = self.page.evaluate("document.body.innerText")
                extracted = ai_extract_jobs_from_dom(raw_text, "HiringCafe", keyword)
                for ext in extracted:
                    jobs.append(build_record(
                        self.portal, keyword, ext.get("title", "Unknown"),
                        ext.get("company", "Unknown"), ext.get("location", "USA"), "",
                        ext.get("link", url)
                    ))
                    
        except Exception as e:
            log.warning(f"  [HiringCafe] Error: {e}")
        return jobs

class WelcomeToTheJungleScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "WTTJ")
        
    def scrape(self, keyword: str) -> list:
        log.info(f"  [WTTJ] Started search for '{keyword}'...")
        jobs = []
        try:
            url = f"https://www.welcometothejungle.com/en/jobs?query={quote_plus(keyword)}"
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            
            # Try traditional DOM extraction
            items = self.page.query_selector_all("li div[data-testid='search-results-list-item-wrapper']")
            for item in items[:15]:
                try:
                    title_el = item.query_selector("h4, h3")
                    title = title_el.inner_text() if title_el else "Unknown"
                    link_el = item.query_selector("a")
                    link = urljoin("https://www.welcometothejungle.com", link_el.get_attribute("href")) if link_el else url
                    if len(title) > 3:
                        jobs.append(build_record(
                            self.portal, keyword, title, "Unknown", "USA", "", link
                        ))
                except Exception:
                    pass
                    
            if not jobs:
                log.info("  [WTTJ] Standard selectors found 0 jobs. Falling back to Ultra AI DOM extraction...")
                raw_text = self.page.evaluate("document.body.innerText")
                extracted = ai_extract_jobs_from_dom(raw_text, "WelcomeToTheJungle", keyword)
                for ext in extracted:
                    jobs.append(build_record(
                        self.portal, keyword, ext.get("title", "Unknown"),
                        ext.get("company", "Unknown"), ext.get("location", "USA"), "",
                        ext.get("link", url)
                    ))
                    
        except Exception as e:
            log.warning(f"  [WTTJ] Error: {e}")
        return jobs


# ── CAREERBUILDER ──────────────────────────────────────────────
class CareerBuilderScraper(BaseScraper):
    def __init__(self, page):
        super().__init__(page, "CareerBuilder")

    def scrape(self, keyword: str) -> list:
        jobs = []
        try:
            q = quote_plus(keyword)
            url = f"https://www.careerbuilder.com/jobs?keywords={q}&location=United+States&posted=1"
            log.info(f"  🌐 CareerBuilder → {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=CONFIG["page_timeout_ms"])
            time.sleep(4)
            self.scroll_page(3)

            # Primary selectors
            cards = self.page.query_selector_all("li.data-results-content-parent, div[class*='data-results-content']")
            if not cards:
                cards = self.page.query_selector_all("a[data-job-did], div[class*='job-listing']")
            
            # Tier 2: AI heal
            if not cards:
                healed = ai_heal_selectors(self.page, "CareerBuilder", keyword)
                if healed:
                    cards = self.page.query_selector_all(healed)
            
            # Tier 3: Full AI extraction
            if not cards:
                log.info("  [CareerBuilder] Falling back to AI DOM extraction...")
                raw_text = self.page.inner_text("body")
                return ai_extract_jobs_from_dom(raw_text, "CareerBuilder", keyword)

            log.info(f"  📦 CareerBuilder: {len(cards)} cards")

            seen = set()
            for card in cards[:CONFIG["max_jobs_per_portal_per_role"]]:
                try:
                    title_el = card.query_selector("h2 a, a[class*='data-results-title'], a[class*='job-title']")
                    title = title_el.inner_text().strip() if title_el else keyword
                    href = title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.careerbuilder.com" + href

                    company_el = card.query_selector("div[class*='data-details'] span, span[class*='company']")
                    company = company_el.inner_text().strip() if company_el else "Unknown"

                    loc_el = card.query_selector("div[class*='data-details'] span:nth-child(2), span[class*='location']")
                    location = loc_el.inner_text().strip() if loc_el else "USA"

                    date_el = card.query_selector("div[class*='date'], time")
                    posted = date_el.inner_text().strip() if date_el else ""

                    if not href or href in seen:
                        continue
                    seen.add(href)
                    if posted and not is_recent_job(posted):
                        continue

                    rec = build_record(self.portal, keyword, title, company, location, "", href, posted)
                    jobs.append(rec)
                except Exception as e:
                    log.debug(f"CareerBuilder card err: {e}")
        except Exception as e:
            log.warning(f"  ⚠️ CareerBuilder: {e}")
        return jobs


# ============================================================
# 💾  SQLITE DB WRITER
# ============================================================
def write_to_db(records: list) -> int:
    """
    Upsert records into jobs_harvested_bronze.
    - If job_hash is NEW → INSERT
    - If job_hash EXISTS → UPDATE all enriched fields (description, tech_stack, ai_summary etc.)
    This ensures Phase 3/4 enriched data always wins.
    """
    new_recs = 0
    updated = 0

    # Query existing hashes
    existing_df = query_df("SELECT job_hash FROM jobs_harvested_bronze")
    existing_hashes = set(existing_df["job_hash"]) if not existing_df.empty else set()

    for r in records:
        if r["job_hash"] not in existing_hashes:
            bronze_row = {
                "id": str(uuid.uuid4()),
                "job_hash": r["job_hash"],
                "fetch_date": r["fetch_date"],
                "portal": r.get("portal", ""),
                "search_keyword": r.get("search_keyword", ""),
                "job_title": r.get("job_title", ""),
                "company_name": r.get("company_name", ""),
                "location": r.get("location", ""),
                "remote_type": r.get("remote_type", ""),
                "salary_range": r.get("salary_range", ""),
                "experience_years": r.get("experience_years", ""),
                "tech_stack": r.get("tech_stack", ""),
                "posted_date": r.get("posted_date", ""),
                "job_description": r.get("job_description", ""),
                "description_length": r.get("description_length", 0),
                "roles_responsibilities": r.get("roles_responsibilities", ""),
                "requirements_section": r.get("requirements_section", ""),
                "roles_summary": r.get("roles_summary", ""),
                "apply_link": r.get("apply_link", ""),
                "easy_apply_link": r.get("easy_apply_link", ""),
                "company_career_url": r.get("company_career_url", ""),
                "company_website": r.get("company_website", ""),
                "hr_email": r.get("hr_email", ""),
                "job_id": r.get("job_id", ""),
                "visa_sponsorship": r.get("visa_sponsorship", ""),
                "validation_score": r.get("validation_score", 0),
                "validation_status": r.get("validation_status", ""),
                "ai_summary": r.get("ai_summary", ""),
                "detail_fetched": 1 if r.get("detail_fetched") else 0,
            }
            ok, err = insert_row("jobs_harvested_bronze", bronze_row)
            if ok:
                new_recs += 1
                existing_hashes.add(r["job_hash"])
            else:
                log.error(f"DB Insert Error: {err}")
        else:
            # UPDATE existing record with enriched Phase 3/4 data
            update_fields = {
                "job_description": r.get("job_description", ""),
                "description_length": r.get("description_length", 0),
                "tech_stack": r.get("tech_stack", ""),
                "experience_years": r.get("experience_years", ""),
                "remote_type": r.get("remote_type", ""),
                "salary_range": r.get("salary_range", ""),
                "roles_responsibilities": r.get("roles_responsibilities", ""),
                "requirements_section": r.get("requirements_section", ""),
                "roles_summary": r.get("roles_summary", ""),
                "hr_email": r.get("hr_email", ""),
                "validation_score": r.get("validation_score", 0),
                "validation_status": r.get("validation_status", ""),
                "ai_summary": r.get("ai_summary", ""),
                "visa_sponsorship": r.get("visa_sponsorship", ""),
                "detail_fetched": 1 if r.get("detail_fetched") else 0,
            }
            ok, err = update_row("jobs_harvested_bronze", update_fields,
                                 f"job_hash = '{r['job_hash']}'")
            if ok:
                updated += 1
            else:
                log.error(f"DB Update Error: {err}")

    if updated:
        log.info(f"   ↩️  Updated {updated} existing records with enriched data")
    return new_recs



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
    print(f"📁 DB: SQLite (jobs_harvested_bronze)")
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
# 🤖  AI KEYWORD EXPANSION
# ============================================================
def ai_expand_keywords(tech_keywords: list[str]) -> list[str]:
    """
    Given raw technology names (e.g. ['Java', 'Python']),
    AI generates proper US IT job search keywords.
    
    SAFETY: If a string is passed instead of list, wraps it in a list
    to prevent the 'P Developer' single-char iteration bug.
    """
    # ── TYPE SAFETY GUARD ──────────────────────────────────────
    # If caller passes "Python" instead of ["Python"], wrap it!
    if isinstance(tech_keywords, str):
        log.warning(f"  ⚠️ ai_expand_keywords received string '{tech_keywords}', converting to list!")
        tech_keywords = [tech_keywords]
    
    if not tech_keywords:
        return ["Data Engineer", "Senior Data Engineer"]
    
    prompt = f"""You are a US IT job search expert. Given these technology/skill keywords, generate the best job search terms.
For each technology, create 2-3 specific job titles that US companies actually post.

Input technologies: {', '.join(tech_keywords)}

Return ONLY a JSON list of strings. Example: ["Java Developer", "Senior Java Engineer", "Python Developer"]
No explanation, just the JSON list."""
    
    content = _ai_call(prompt, max_tokens=300)
    if content:
        keywords = _parse_ai_json(content)
        if isinstance(keywords, list) and keywords:
            log.info(f"  🤖 AI expanded {len(tech_keywords)} techs → {len(keywords)} search keywords")
            return keywords
    
    # Fallback: create basic patterns
    expanded = []
    for tech in tech_keywords:
        expanded.append(f"{tech} Developer")
        expanded.append(f"Senior {tech} Engineer")
    return expanded


# ============================================================
# 🚀  MAIN ORCHESTRATOR
# ============================================================
def run_harvester_v10(keywords: list[str] = None):
    """
    Main scraper pipeline.
    keywords: Optional list of technology names (e.g. ['Java', 'Python', 'Data Engineer']).
              If None, uses CONFIG['roles'] from env or defaults.
    """
    # Determine roles to search
    if keywords:
        roles = ai_expand_keywords(keywords)
    else:
        roles = CONFIG["roles"]
    
    log.info("=" * 65)
    log.info("🚀 US IT JOB HARVESTER V11 — FULL PIPELINE")
    log.info(f"📋 Roles: {len(roles)} | Sites: {'ALL 14' if CONFIG['enable_all_sites'] else 'Top 4'}")
    log.info(f"⏱️  Filter: Yesterday ({YESTERDAY}) + Today ({TODAY})")
    log.info(f"🤖 AI: NVIDIA NIM ({CONFIG['nvidia_simple_model']}) + Ultra ({CONFIG['nvidia_ultra_model']})")
    log.info(f"   Gemini fallback: {'Yes' if CONFIG['gemini_api_key'] else 'No'}")
    log.info(f"🔍 Keywords: {roles}")
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
                "Glassdoor":      GlassdoorScraper(page),
                "Wellfound":      WellfoundScraper(page),
                "ZipRecruiter":   ZipRecruiterScraper(page),
                "SimplyHired":    SimplyHiredScraper(page),
                "Monster":        MonsterScraper(page),
                "HiringCafe":     HiringCafeScraper(page),
                "WTTJ":           WelcomeToTheJungleScraper(page),
                "CareerBuilder":  CareerBuilderScraper(page),
            })

        ddg_scrapers = []
        if CONFIG["enable_all_sites"]:
            ddg_scrapers = [GreenhouseScraper(), LeverScraper()]

        # ── PHASE 1: Discovery ──────────────────────
        log.info("\n═══ PHASE 1: JOB DISCOVERY ═══")
        for role in roles:
            log.info(f"\n{'─'*50}")
            log.info(f"🔍 Role: {role}")
            log.info(f"{'─'*50}")

            for portal_name, scraper in browser_scrapers.items():
                try:
                    jobs = scraper.scrape(role)
                    log.info(f"  ✅ {portal_name}: {len(jobs)} jobs")
                    all_records.extend(jobs)
                    write_to_db(jobs) # Real-time parallel insertion
                except Exception as e:
                    log.warning(f"  ❌ {portal_name}: {e}")
                time.sleep(random.uniform(*CONFIG["inter_request_delay"]))

            for scraper in ddg_scrapers:
                try:
                    jobs = scraper.scrape(role)
                    all_records.extend(jobs)
                    write_to_db(jobs) # Real-time parallel insertion
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

        # ── PHASE 2 SKIPPED: Scrape first, AI later strategy ────────
        # We no longer do initial AI scoring. We fetch details for all unique jobs.
        for rec in unique:
            rec["validation_score"] = 60  # Default to pass threshold
            rec["validation_status"] = "Pending"
        
        quality = unique
        log.info(f"✅ Preparing {len(quality)} jobs for Detail Fetch (AI Initial Scoring skipped)")

        # ── PHASE 3: Full Detail Fetch (parallel) ───────────
        log.info("\n═══ PHASE 3: FULL DETAIL FETCH ═══")
        quality = fetch_details_parallel(quality, browser)
        write_to_db(quality)  # INSTANTLY SAVE DESCRIPTIONS TO DB

        # ── PHASE 4: Re-score with full description (PARALLEL) ──
        log.info("\n═══ PHASE 4: RE-SCORE WITH FULL DESCRIPTIONS (PARALLEL) ═══")
        fetched_with_desc = [r for r in quality if r.get("detail_fetched") and r.get("description_length", 0) > 100]
        log.info(f"🔄 Re-scoring {len(fetched_with_desc)} jobs with full descriptions...")
        
        rescored_count = 0
        def rescore_job(rec):
            try:
                time.sleep(1.5 + random.random()) # Concurrency throttling jitter
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

                # Real-time UI update
                update_row("jobs_harvested_bronze", {
                    "validation_score": rec["validation_score"],
                    "validation_status": rec["validation_status"],
                    "ai_summary": rec["ai_summary"],
                    "roles_summary": rec["roles_summary"],
                    "remote_type": rec["remote_type"],
                    "tech_stack": rec["tech_stack"],
                    "experience_years": rec["experience_years"],
                    "salary_range": rec["salary_range"],
                    "visa_sponsorship": int(rec["visa_sponsorship"] == "True") if isinstance(rec["visa_sponsorship"], str) else int(bool(rec["visa_sponsorship"])),
                    "job_description": rec["job_description"],
                    "description_length": rec["description_length"],
                    "roles_responsibilities": rec.get("roles_responsibilities", ""),
                    "requirements_section": rec.get("requirements_section", ""),
                    "hr_email": rec.get("hr_email", ""),
                    "company_career_url": rec.get("company_career_url", ""),
                    "easy_apply_link": rec.get("easy_apply_link", ""),
                    "detail_fetched": 1
                }, f"job_hash = '{rec['job_hash']}'")
            except Exception as e:
                log.debug(f"Rescore parallel error: {e}")

        # Execute parallel AI rescore
        workers = min(10, len(fetched_with_desc) if fetched_with_desc else 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(rescore_job, rec) for rec in fetched_with_desc]
            for i, future in enumerate(as_completed(futures)):
                future.result()
                rescored_count += 1
                if rescored_count % 10 == 0:
                    log.info(f"   Re-scored {rescored_count}/{len(fetched_with_desc)}...")

        final = [r for r in quality if r["validation_status"] != "Junk"]
        log.info(f"✅ Final quality jobs: {len(final)}")

        browser.close()

    # ── Write DB ────────────────────────────────────────────
    written = write_to_db(final)
    log.info(f"\n💾 Inserted {written} new records → SQLite jobs_harvested_bronze")

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
    print(f"   📁 DB: SQLite (jobs_harvested_bronze)")
