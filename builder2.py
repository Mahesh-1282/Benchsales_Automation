def build_final():
    with open('final_version.py', 'r') as f:
        content = f.read()

    # 1. Update is_recent_job
    old_is_recent = """def is_recent_job(posted_text: str) -> bool:
    if not posted_text:
        return True
    pt = posted_text.lower().strip()
    for tag in DATE_TAGS:
        if tag.lower() in pt:
            return True
    m = re.search(r"(\d+)\s+hour", pt)
    if m and int(m.group(1)) <= 48:
        return True
    m = re.search(r"(\d+)\s+day", pt)
    if m and int(m.group(1)) <= 1:
        return True
    if any(x in pt for x in ["minute", "second", "just now"]):
        return True
    return False"""
    
    new_is_recent = """def is_recent_job(posted_text: str) -> bool:
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
    return False"""
    content = content.replace(old_is_recent, new_is_recent)

    # 2. Add AI Auto Healer function
    auto_healer = """
# ============================================================
# 🤖  AI AUTO-HEALER (Token Optimized)
# ============================================================
def ai_heal_selectors(page, portal_name, keyword):
    \"\"\"
    If a scraper returns 0 jobs, the site likely changed classes.
    This extracts a tiny 200-token summary of the DOM and asks AI for the new selector.
    Very strict token limit to save budget!
    \"\"\"
    log.warning(f"  🤖 Auto-Healer analyzing {portal_name} DOM for '{keyword}'...")
    try:
        dom_snippet = page.evaluate('''() => {
            let candidates = new Set();
            document.querySelectorAll('div, li, article').forEach(el => {
                let cls = el.className;
                if (typeof cls === 'string' && (cls.includes('job') || cls.includes('card') || cls.includes('result'))) {
                    candidates.add(el.tagName.toLowerCase() + '.' + cls.trim().replace(/\\\\s+/g, '.'));
                }
            });
            return Array.from(candidates).slice(0, 15).join('\\n');
        }''')
        
        if not dom_snippet:
            return None
            
        prompt = f"Portal {portal_name} job card HTML classes:\\n{dom_snippet}\\nRespond ONLY with the single best CSS selector for the job card. No markdown, no explanation."
        
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

"""
    # Insert before BaseScraper
    content = content.replace("# ============================================================\n# 🌐  BASE SCRAPER", auto_healer + "# ============================================================\n# 🌐  BASE SCRAPER")

    # 3. Add stealth to Phase 1
    phase1_setup = """        page = context.new_page()
        stealth(page)
        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda r: r.abort())"""
    
    content = content.replace('        page = context.new_page()\n        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}", lambda r: r.abort())', phase1_setup)

    # 4. Inject auto-healer into Indeed and Glassdoor
    # For Indeed
    indeed_old = """            cards = self.page.query_selector_all("div.job_seen_beacon")
            if not cards:
                cards = self.page.query_selector_all("[data-testid='slider_item']")
            log.info(f"  📦 Indeed: {len(cards)} cards")"""
            
    indeed_new = """            cards = self.page.query_selector_all("div.job_seen_beacon")
            if not cards:
                cards = self.page.query_selector_all("[data-testid='slider_item']")
            
            if not cards:
                new_sel = ai_heal_selectors(self.page, "Indeed", keyword)
                if new_sel: cards = self.page.query_selector_all(new_sel)
                
            log.info(f"  📦 Indeed: {len(cards)} cards")"""
    content = content.replace(indeed_old, indeed_new)
    
    # For Glassdoor
    glassdoor_old = """            cards = self.page.query_selector_all("li[class*='JobsList_jobListItem']")
            if not cards:
                cards = self.page.query_selector_all("[data-test='jobListing']")
            log.info(f"  📦 Glassdoor: {len(cards)} cards")"""
            
    glassdoor_new = """            cards = self.page.query_selector_all("li[class*='JobsList_jobListItem']")
            if not cards:
                cards = self.page.query_selector_all("[data-test='jobListing']")
            
            if not cards:
                new_sel = ai_heal_selectors(self.page, "Glassdoor", keyword)
                if new_sel: cards = self.page.query_selector_all(new_sel)
                
            log.info(f"  📦 Glassdoor: {len(cards)} cards")"""
    content = content.replace(glassdoor_old, glassdoor_new)

    with open('final_Version_1.py', 'w') as f:
        f.write(content)

if __name__ == '__main__':
    build_final()
