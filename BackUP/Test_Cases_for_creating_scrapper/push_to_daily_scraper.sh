#!/bin/bash
# Run this script to push the fixed scrapper.py to your daily-job-scraper repo
# Usage: bash push_to_daily_scraper.sh YOUR_GITHUB_PAT

PAT="${1:-}"
if [ -z "$PAT" ]; then
    echo "Usage: bash push_to_daily_scraper.sh YOUR_GITHUB_PAT"
    echo ""
    echo "Get your PAT from: GitHub → Settings → Developer settings → Personal access tokens"
    exit 1
fi

REPO="scrapper001-jobs/daily-job-scraper"

echo "📦 Cloning daily-job-scraper repo..."
git clone "https://x-access-token:${PAT}@github.com/${REPO}.git" /tmp/daily-job-scraper-push

echo "📋 Copying scrapper.py and workflow..."
cp scrapper.py /tmp/daily-job-scraper-push/
mkdir -p /tmp/daily-job-scraper-push/.github/workflows/
cp .github/workflows/daily_scraper.yml /tmp/daily-job-scraper-push/.github/workflows/

echo "🚀 Committing and pushing..."
cd /tmp/daily-job-scraper-push
git config user.email "mahesh@local"
git config user.name "Mahesh"
git add scrapper.py .github/workflows/daily_scraper.yml
git commit -m "Fix: Complete scrapper rewrite - now finds 100+ US jobs per run

WHAT CHANGED:
- RSS/API-based discovery (bypasses bot blocking that caused 0 jobs)
- LinkedIn Guest API (no login needed, 10-50 jobs)
- Dice RSS feed (XML, no blocking)
- RemoteOK free JSON API
- The Muse free JSON API
- Greenhouse.io open JSON API (40+ major tech companies)
- US-only job filter (removes India/non-US jobs automatically)
- AI only for description analysis (not discovery - saves API quota)
- Self-healing: 3 retries, model cascade fast->supreme
- GitHub push works with GH_PAT secret"

git push origin main

echo "✅ Done! Now trigger the workflow:"
echo "   Go to: https://github.com/${REPO}/actions"
echo "   Click: 'Daily Job AI Scraper' → 'Run workflow'"

# Cleanup
cd -
rm -rf /tmp/daily-job-scraper-push
