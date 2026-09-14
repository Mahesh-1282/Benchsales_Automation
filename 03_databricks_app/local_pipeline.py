import os
import sys
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path
import requests
import re

# Insert parent dir to load db_utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute_sql, query_df, insert_row, esc

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("LocalPipeline")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

def run_bronze_to_silver():
    """
    Deduplicates jobs_harvested_bronze into jobs_clean_silver.
    """
    log.info("== PHASE 1: BRONZE TO SILVER ==")
    bronze_df = query_df("SELECT * FROM jobs_harvested_bronze")
    if bronze_df.empty:
        log.info("No bronze jobs to process.")
        return 0

    silver_existing = query_df("SELECT job_hash FROM jobs_clean_silver")
    existing_hashes = set(silver_existing["job_hash"]) if not silver_existing.empty else set()

    new_jobs = 0
    now_date = datetime.now().date().isoformat()
    
    for _, row in bronze_df.iterrows():
        h = row.get("job_hash")
        if h in existing_hashes:
            continue
        
        # Clean requirements
        tech = row.get("tech_stack", "")
        exp = row.get("experience_years", "")
        exp_min = 0
        exp_max = 10
        if exp:
            nums = re.findall(r'\d+', str(exp))
            if nums:
                exp_min = int(nums[0])
                if len(nums) > 1:
                    exp_max = int(nums[1])
                else:
                    exp_max = exp_min + 5
                    
        silver_row = {
            "job_hash": h,
            "job_title": row.get("job_title"),
            "company_name": row.get("company_name"),
            "location": row.get("location"),
            "remote_type": row.get("remote_type"),
            "salary_range": row.get("salary_range"),
            "experience_min": exp_min,
            "experience_max": exp_max,
            "tech_stack": tech,
            "job_description": row.get("job_description"),
            "roles_responsibilities": row.get("roles_responsibilities"),
            "requirements_section": row.get("requirements_section"),
            "roles_summary": row.get("roles_summary"),
            "ai_summary": row.get("ai_summary"),
            "apply_link": row.get("apply_link"),
            "easy_apply_link": row.get("easy_apply_link"),
            "company_career_url": row.get("company_career_url"),
            "company_website": row.get("company_website"),
            "hr_email": row.get("hr_email"),
            "portal": row.get("portal"),
            "posted_date": row.get("posted_date"),
            "fetch_date": row.get("fetch_date"),
            "visa_sponsorship": row.get("visa_sponsorship"),
            "validation_score": row.get("validation_score"),
            "first_seen_date": now_date,
            "last_seen_date": now_date,
            "active": True
        }
        ok, err = insert_row("jobs_clean_silver", silver_row)
        if ok:
            new_jobs += 1
            existing_hashes.add(h)
            
    # Clear bronze to keep it lightweight if desired (optional)
    execute_sql("DELETE FROM jobs_harvested_bronze")
    log.info(f"Inserted {new_jobs} new jobs to Silver. Cleared Bronze.")
    return new_jobs


def run_job_matching():
    """
    Match active Silver jobs against active Users.
    """
    log.info("== PHASE 2: JOB MATCHING ==")
    users = query_df("SELECT u.*, r.skills_extracted FROM users u LEFT JOIN user_resumes r ON u.user_id = r.user_id AND r.is_primary = 1 WHERE u.is_active = 1 OR u.is_active = 'true' OR u.is_active = '1'")
    if users.empty:
        log.info("No active users found.")
        return
        
    jobs = query_df("SELECT * FROM jobs_clean_silver WHERE active = 1 OR active = 'true' OR active = '1'")
    if jobs.empty:
        log.info("No active jobs in Silver.")
        return
        
    matches_existing = query_df("SELECT user_id, job_hash FROM user_job_matches")
    existing_pairs = set()
    if not matches_existing.empty:
        for _, r in matches_existing.iterrows():
            existing_pairs.add(f"{r['user_id']}_{r['job_hash']}")
            
    new_matches = 0
    
    for _, u in users.iterrows():
        uid = u["user_id"]
        u_exp = float(u.get("total_experience_years") or 0)
        u_skills = str(u.get("skills_extracted", "")).lower()
        min_score = int(u.get("min_match_score") or 30)
        
        user_skill_set = set(s.strip() for s in u_skills.split(",")) if u_skills else set()
        
        for _, j in jobs.iterrows():
            jh = j["job_hash"]
            if f"{uid}_{jh}" in existing_pairs:
                continue
                
            # Quick score
            score = 0
            j_skills = str(j.get("tech_stack", "")).lower()
            j_req = str(j.get("requirements_section", "")).lower()
            j_desc = str(j.get("job_description", "")).lower()
            
            # Experience Fit
            exp_min = j.get("experience_min") or 0
            exp_max = j.get("experience_max") or 10
            
            if exp_min <= u_exp <= exp_max:
                exp_fit = "exact"
                score += 30
            elif u_exp < exp_min and exp_min - u_exp <= 2:
                exp_fit = "near"
                score += 15
            elif u_exp < exp_min:
                exp_fit = "under"
                score += 0
            else:
                exp_fit = "over"
                score += 25
                
            # Skills Match
            matched_skills = []
            if user_skill_set:
                for s in user_skill_set:
                    if len(s) > 2 and (s in j_skills or s in j_req or s in j_desc):
                        matched_skills.append(s)
                
                skill_pct = int((len(matched_skills) / len(user_skill_set)) * 100)
                score += int(skill_pct * 0.7) # Up to 70 pts from skills
            else:
                skill_pct = 0
                
            if score >= min_score:
                row = {
                    "match_id": str(uuid.uuid4()),
                    "user_id": uid,
                    "job_hash": jh,
                    "match_score": min(score, 99),
                    "skill_match_pct": skill_pct,
                    "experience_fit": exp_fit,
                    "skill_overlap": ", ".join(matched_skills),
                    "skill_gap": "",
                    "status": "matched",
                    "resume_generated": False,
                    "resume_id": None,
                    "matched_at": datetime.now()
                }
                ok, _ = insert_row("user_job_matches", row)
                if ok:
                    new_matches += 1
                    existing_pairs.add(f"{uid}_{jh}")
                    
    log.info(f"Created {new_matches} new matches.")

def run_resume_generation():
    """
    Find matches where status='resume_pending' and use AI to generate tailored resume.
    """
    log.info("== PHASE 3: RESUME GENERATION ==")
    pending = query_df("SELECT m.match_id, m.user_id, j.job_hash, j.job_title, j.company_name, j.job_description, j.tech_stack, u.full_name, r.work_history_json, r.skills_extracted FROM user_job_matches m JOIN jobs_clean_silver j ON m.job_hash = j.job_hash JOIN users u ON m.user_id = u.user_id LEFT JOIN user_resumes r ON u.user_id = r.user_id AND r.is_primary = 1 WHERE m.status = 'resume_pending'")
    
    if pending.empty:
        log.info("No pending resumes to generate.")
        return
        
    log.info(f"Generating {len(pending)} resumes...")
    
    for _, req in pending.iterrows():
        if not GEMINI_API_KEY:
            log.warning("No GEMINI_API_KEY found, skipping resume gen.")
            break
            
        mid = req["match_id"]
        
        prompt = f"""You are an Expert Resume Tailorer.
Given the candidate's work history and skills, tailor their resume to strictly match the Job Description. 
Do not lie, but emphasize relevant skills and achievements.

Candidate Name: {req.get('full_name')}
Candidate Skills: {req.get('skills_extracted')}
Candidate Work History (JSON):
{req.get('work_history_json')}

Target Job Title: {req.get('job_title')}
Target Company: {req.get('company_name')}
Target Job Description:
{req.get('job_description')}

Output ONLY a beautifully formatted Markdown resume. Include Name, Skills, and tailored Work History.
"""
        try:
            log.info(f"  Generating resume for match {mid}...")
            url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.5}
            }
            resp = requests.post(url, json=payload, timeout=90)
            
            if resp.status_code == 200:
                markdown_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                new_res_id = str(uuid.uuid4())
                
                res_row = {
                    "resume_id": new_res_id,
                    "user_id": req["user_id"],
                    "job_hash": req["job_hash"],
                    "match_id": mid,
                    "resume_content": markdown_text,
                    "generated_at": datetime.now(),
                    "is_latest": True
                }
                insert_row("generated_resumes", res_row)
                execute_sql(f"UPDATE user_job_matches SET status = 'resume_ready', resume_generated = 1, resume_id = '{new_res_id}' WHERE match_id = '{mid}'")
                log.info(f"  ✅ Generated for {mid}")
            else:
                log.warning(f"  ❌ Failed for {mid}: {resp.text}")
        except Exception as e:
            log.warning(f"  ❌ Error for {mid}: {e}")

if __name__ == "__main__":
    log.info("Starting Syntara Local Pipeline...")
    run_bronze_to_silver()
    run_job_matching()
    run_resume_generation()
    log.info("Pipeline Complete!")
