"""
╔══════════════════════════════════════════════════════════════════════╗
║  JSEARCH LOCAL RUNNER                                                ║
║  Run this daily on your local machine.                               ║
║  Fetches jobs from JSearch API → saves to CSV                        ║
║  CSV maps EXACTLY to jobs_harvested_bronze schema                    ║
║                                                                      ║
║  Usage:                                                              ║
║    python jsearch_local.py                                           ║
║  Output:                                                             ║
║    daily_jobs_YYYYMMDD.csv   (upload this to Databricks manually)    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, csv, json, uuid, hashlib, re, requests, time, logging, sys
from datetime import date, datetime
from dotenv import load_dotenv
from pathlib import Path

# Import local db_utils
sys.path.insert(0, str(Path(__file__).parent.parent / "03_databricks_app"))
from db_utils import execute_sql, query_df, insert_row, esc

# ── Load .env ────────────────────────────────────────────────────────
load_dotenv()
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY", "")

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("JSearch")

# ── Config ───────────────────────────────────────────────────────────
TODAY      = date.today()
CSV_FILE   = f"daily_jobs_{TODAY.strftime('%Y%m%d')}.csv"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search-v2"

# Search keywords — same roles as web scraper
SEARCH_KEYWORDS = [
    "Data Engineer in USA",
    "Senior Data Engineer in USA",
    "PySpark Engineer in USA",
    "ETL Developer in USA",
    "Analytics Engineer in USA",
    "Machine Learning Engineer in USA",
    "Databricks Engineer in USA",
    "Spark Developer in USA",
    "Azure Data Engineer in USA",
    "AWS Data Engineer in USA",
]

# Number of pages per keyword (10 results/page × 5 pages = 50 jobs/keyword)
NUM_PAGES = "5"

# Delay between API calls (avoid rate limit)
DELAY_BETWEEN_CALLS = 2  # seconds

# Exact CSV headers matching jobs_harvested_bronze schema
CSV_HEADERS = [
    "id", "job_hash", "fetch_date", "portal", "search_keyword",
    "job_title", "company_name", "location", "remote_type",
    "salary_range", "experience_years", "tech_stack",
    "posted_date", "job_description", "description_length",
    "roles_responsibilities", "requirements_section", "roles_summary",
    "apply_link", "easy_apply_link", "company_career_url",
    "company_website", "hr_email", "job_id",
    "visa_sponsorship", "validation_score", "validation_status",
    "ai_summary", "detail_fetched",
]


# ── Helpers ──────────────────────────────────────────────────────────

def make_job_hash(company: str, title: str) -> str:
    """MD5 hash of lowercase(company + title) — same logic as Databricks."""
    unique_str = f"{company}_{title}".lower().replace(" ", "").strip()
    return hashlib.md5(unique_str.encode("utf-8")).hexdigest()


def parse_salary(job: dict) -> str:
    """Build salary_range string from JSearch min/max salary fields."""
    sal_min = job.get("job_min_salary")
    sal_max = job.get("job_max_salary")
    period  = (job.get("job_salary_period") or "").lower()

    if sal_min and sal_max:
        period_label = {"year": "/yr", "month": "/mo", "hour": "/hr"}.get(period, "")
        return f"${int(sal_min):,} - ${int(sal_max):,}{period_label}"
    elif sal_min:
        return f"${int(sal_min):,}+"
    return ""


def parse_experience(job: dict) -> str:
    """Extract experience requirement from JSearch fields."""
    req_exp = job.get("job_required_experience") or {}
    if isinstance(req_exp, dict):
        months = req_exp.get("required_experience_in_months")
        if months:
            years = round(months / 12, 1)
            return f"{years}+ years"
    # Try to extract from description
    desc = job.get("job_description") or ""
    m = re.search(r"(\d+\+?\s*(?:to|-)?\s*\d*)\s*years?\s+(?:of\s+)?experience", desc, re.I)
    if m:
        return m.group().strip()[:60]
    return ""


def parse_remote_type(job: dict) -> str:
    """Determine remote type from JSearch fields."""
    is_remote = job.get("job_is_remote", False)
    emp_type  = (job.get("job_employment_type") or "").upper()
    desc      = (job.get("job_description") or "").lower()

    if is_remote:
        return "Remote"
    if "hybrid" in desc or "hybrid" in emp_type.lower():
        return "Hybrid"
    if "on-site" in desc or "onsite" in desc or "in-office" in desc:
        return "Onsite"
    if "remote" in desc:
        return "Remote"
    return "Not specified"


def parse_location(job: dict) -> str:
    """Build location string from JSearch city/state fields."""
    city    = job.get("job_city") or ""
    state   = job.get("job_state") or ""
    country = job.get("job_country") or "US"

    if city and state:
        return f"{city}, {state}"
    elif city:
        return f"{city}, {country}"
    elif state:
        return f"{state}, {country}"
    return "USA"


def parse_tech_stack(job: dict) -> str:
    """Extract tech stack from required_skills or description."""
    # JSearch sometimes returns required_skills as list
    skills = job.get("job_required_skills") or []
    if isinstance(skills, list) and skills:
        return ", ".join(skills[:15])

    # Fallback: keyword scan on description
    desc = (job.get("job_description") or "").lower()
    known_techs = [
        "python", "pyspark", "spark", "sql", "databricks", "azure", "aws",
        "gcp", "kafka", "airflow", "dbt", "scala", "java", "delta lake",
        "snowflake", "redshift", "bigquery", "pandas", "numpy", "tensorflow",
        "pytorch", "docker", "kubernetes", "git", "tableau", "power bi",
        "hadoop", "hive", "hdfs", "terraform", "jenkins", "ci/cd",
        "rest api", "fastapi", "flask", "django", "react", "typescript",
        "postgresql", "mysql", "mongodb", "elasticsearch", "redis",
        "azure data factory", "azure synapse", "aws glue", "emr", "s3",
    ]
    found = [t for t in known_techs if t in desc]
    return ", ".join(found[:12])


def parse_highlights(job: dict, section: str) -> str:
    """Extract Responsibilities or Qualifications from job_highlights."""
    highlights = job.get("job_highlights") or {}
    if not isinstance(highlights, dict):
        return ""
    items = highlights.get(section) or []
    if isinstance(items, list) and items:
        return "\n".join(f"• {item}" for item in items[:20])
    return ""


def fetch_keyword_jobs(keyword: str) -> list[dict]:
    """Fetch all pages of jobs for one keyword from JSearch API."""
    all_jobs = []
    headers = {
        "x-rapidapi-key":  JSEARCH_API_KEY,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query":     keyword,
        "page":      "1",
        "num_pages": NUM_PAGES,
        "date_posted": "today",      # Filter to recent jobs
    }

    log.info(f"🌐 Fetching: '{keyword}' ...")
    try:
        resp = requests.get(JSEARCH_URL, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            # Handle different JSearch response structures
            if isinstance(data, dict):
                inner = data.get("data", [])
                if isinstance(inner, list):
                    all_jobs = inner
                elif isinstance(inner, dict):
                    all_jobs = inner.get("jobs", [])
            elif isinstance(data, list):
                all_jobs = data
            log.info(f"  ✅ {len(all_jobs)} jobs fetched for '{keyword}'")
        elif resp.status_code == 429:
            log.warning(f"  ⚠️ Rate limited! Waiting 30s...")
            time.sleep(30)
            return fetch_keyword_jobs(keyword)
        else:
            log.error(f"  ❌ API Error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.error(f"  ❌ Request failed: {e}")

    return all_jobs


def build_record(job: dict, keyword: str) -> dict:
    """Map a raw JSearch job dict → bronze schema dict."""
    company   = (job.get("employer_name") or "Unknown Company").strip()
    title     = (job.get("job_title")     or "Unknown Title").strip()
    desc      = (job.get("job_description") or "").strip()
    apply_lnk = (job.get("job_apply_link") or "").strip()

    # Core identifiers
    job_hash = make_job_hash(company, title)
    job_id   = str(job.get("job_id") or "")

    # Easy apply: JSearch has job_apply_is_direct flag
    easy_apply = apply_lnk if job.get("job_apply_is_direct") else ""

    # Posted date
    posted_raw = job.get("job_posted_at_datetime_utc") or ""
    if posted_raw:
        try:
            posted_date = datetime.fromisoformat(posted_raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            posted_date = posted_raw[:10]
    else:
        posted_date = ""

    # Visa sponsorship
    desc_lower = desc.lower()
    visa_no_terms = ["no sponsorship", "not sponsor", "cannot sponsor",
                     "will not sponsor", "authorization required"]
    visa_yes_terms = ["visa sponsorship", "will sponsor", "h1b", "h-1b", "tn visa"]
    visa = None
    if any(t in desc_lower for t in visa_yes_terms):
        visa = True
    elif any(t in desc_lower for t in visa_no_terms):
        visa = False

    return {
        "id":                  str(uuid.uuid4()),
        "job_hash":            job_hash,
        "fetch_date":          str(TODAY),
        "portal":              "JSearch",
        "search_keyword":      keyword,
        "job_title":           title,
        "company_name":        company,
        "location":            parse_location(job),
        "remote_type":         parse_remote_type(job),
        "salary_range":        parse_salary(job),
        "experience_years":    parse_experience(job),
        "tech_stack":          parse_tech_stack(job),
        "posted_date":         posted_date,
        "job_description":     desc[:8000],
        "description_length":  len(desc.split()),
        "roles_responsibilities": parse_highlights(job, "Responsibilities"),
        "requirements_section":   parse_highlights(job, "Qualifications"),
        "roles_summary":       "",          # Filled by silver pipeline AI
        "apply_link":          apply_lnk,
        "easy_apply_link":     easy_apply,
        "company_career_url":  "",
        "company_website":     job.get("employer_website") or "",
        "hr_email":            "",
        "job_id":              job_id,
        "visa_sponsorship":    visa,
        "validation_score":    0,           # Filled by silver pipeline
        "validation_status":   "Pending",
        "ai_summary":          "",          # Filled by silver pipeline
        "detail_fetched":      False,
    }


def write_to_db(records: list) -> int:
    """Write records to SQLite jobs_harvested_bronze, skip if file already has that job_hash."""
    existing_df = query_df("SELECT job_hash FROM jobs_harvested_bronze")
    existing_hashes = set(existing_df["job_hash"]) if not existing_df.empty else set()

    new_records = [r for r in records if r["job_hash"] not in existing_hashes]
    if not new_records:
        log.info("  ℹ️  No new records to write (all already in DB).")
        return 0

    inserted = 0
    for r in new_records:
        # Match EXACTLY with bronze schema
        bronze_row = {
            "id": r["id"],
            "job_hash": r["job_hash"],
            "fetch_date": r["fetch_date"],
            "portal": r["portal"],
            "search_keyword": r["search_keyword"],
            "job_title": r["job_title"],
            "company_name": r["company_name"],
            "location": r["location"],
            "remote_type": r["remote_type"],
            "salary_range": r["salary_range"],
            "experience_years": r["experience_years"],
            "tech_stack": r["tech_stack"],
            "posted_date": r["posted_date"],
            "job_description": r["job_description"],
            "description_length": r["description_length"],
            "roles_responsibilities": r["roles_responsibilities"],
            "requirements_section": r["requirements_section"],
            "roles_summary": r["roles_summary"],
            "apply_link": r["apply_link"],
            "easy_apply_link": r["easy_apply_link"],
            "company_career_url": r["company_career_url"],
            "company_website": r["company_website"],
            "hr_email": r["hr_email"],
            "job_id": r["job_id"],
            "visa_sponsorship": r["visa_sponsorship"],
            "validation_score": r["validation_score"],
            "validation_status": r["validation_status"],
            "ai_summary": r["ai_summary"],
            "detail_fetched": r["detail_fetched"]
        }
        ok, err = insert_row("jobs_harvested_bronze", bronze_row)
        if ok:
            inserted += 1
        else:
            log.error(f"DB Insert Error: {err}")

    return inserted


# ── Main ─────────────────────────────────────────────────────────────

def main():
    if not JSEARCH_API_KEY:
        log.error("❌ JSEARCH_API_KEY not set in .env! Exiting.")
        return

    log.info("=" * 65)
    log.info(f"🚀 JSEARCH LOCAL RUNNER — {TODAY}")
    log.info(f"📋 Keywords: {len(SEARCH_KEYWORDS)} | Output: SQLite (jobs_harvested_bronze)")
    log.info("=" * 65)

    all_records    = []
    seen_hashes:   set = set()
    total_fetched  = 0

    for keyword in SEARCH_KEYWORDS:
        raw_jobs = fetch_keyword_jobs(keyword)
        total_fetched += len(raw_jobs)

        for job in raw_jobs:
            if not isinstance(job, dict):
                continue
            try:
                record = build_record(job, keyword)
                # Deduplicate within this run
                if record["job_hash"] not in seen_hashes:
                    seen_hashes.add(record["job_hash"])
                    all_records.append(record)
            except Exception as e:
                log.debug(f"Record build error: {e}")

        log.info(f"  📊 Running total: {len(all_records)} unique jobs so far")
        time.sleep(DELAY_BETWEEN_CALLS)

    # Write to SQLite DB
    written = write_to_db(all_records)

    log.info("=" * 65)
    log.info(f"✅ DONE!")
    log.info(f"   Total API results : {total_fetched}")
    log.info(f"   Unique jobs (dedup): {len(all_records)}")
    log.info(f"   Written to DB      : {written}")
    log.info("=" * 65)


if __name__ == "__main__":
    main()
