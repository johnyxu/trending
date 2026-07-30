# GitHub Trending Scraper

Scrapes [github.com/trending](https://github.com/trending) (daily / weekly / monthly) and saves each as a Markdown report under a date-stamped folder.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Scrape today's date, all languages
python scrape_trending.py

# Filter by spoken language (GitHub's spoken_language_code param, e.g. "en", "zh")
python scrape_trending.py --lang en

# Write into a specific date folder instead of today
python scrape_trending.py --date 2026-08-01

# Re-scrape even if that date's files already exist
python scrape_trending.py --force
```

Each run writes three files under `<YYYY-MM-DD>/`:

```
2026-07-30/
├── trending-today.md
├── trending-week.md
└── trending-month.md
```

The default date is today's date **in Melbourne local time** (`Australia/Melbourne`, via `zoneinfo`), not the machine's system timezone — this matters on GitHub Actions runners, which default to UTC and would otherwise be up to a day behind Melbourne.

If that date's three files already exist, the script skips scraping (pass `--force` to override) and instead appends a `status=skipped` line to `logs/run.log`. Every run — scraped or skipped — appends one line to `logs/run.log` with a UTC timestamp:

```
2026-07-30T22:32:33+00:00 | date=2026-07-30 | status=scraped | today=14, week=21, month=21
2026-07-30T23:01:12+00:00 | date=2026-07-30 | status=skipped | already generated today; use --force to re-run
```

## Automation

[`.github/workflows/daily-trending.yml`](.github/workflows/daily-trending.yml) runs the scraper daily (cron, UTC time — see the workflow file for the current Melbourne-local offset) and on manual `workflow_dispatch`, then commits any new/changed files back to `main`. The job only runs on `main`; triggering it from another branch is a no-op.

To test manually: GitHub repo → Actions tab → "Daily GitHub Trending Scrape" → **Run workflow**.
