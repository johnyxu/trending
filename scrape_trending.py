#!/usr/bin/env python3
"""Scrape github.com/trending and save today/week/month reports as Markdown.

Usage:
    python scrape_trending.py [--lang SPOKEN_LANGUAGE_CODE] [--date YYYY-MM-DD]

Output:
    ./<YYYY-MM-DD>/today.md
    ./<YYYY-MM-DD>/week.md
    ./<YYYY-MM-DD>/month.md
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trending-scraper/1.0)"}

RANGES = {
    "today": ("daily", "trending-today.md"),
    "week": ("weekly", "trending-week.md"),
    "month": ("monthly", "trending-month.md"),
}

OUTPUT_ROOT = Path(__file__).resolve().parent
LOG_PATH = OUTPUT_ROOT / "logs" / "run.log"


def log_run(date_str: str, status: str, detail: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    line = f"{now_utc.isoformat(timespec='seconds')} | date={date_str} | status={status} | {detail}\n"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def fetch_trending(since: str, spoken_language_code: str = "") -> list[dict]:
    params = {"since": since, "spoken_language_code": spoken_language_code}
    resp = requests.get(TRENDING_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_trending(resp.text)


def parse_trending(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    repos = []

    for article in soup.select("article.Box-row"):
        h2 = article.find("h2")
        if h2 is None or h2.a is None:
            continue

        repo_path = h2.a["href"].strip("/")

        desc_tag = article.find("p")
        description = re.sub(r"\s+", " ", desc_tag.get_text(" ", strip=True)).strip() if desc_tag else ""

        lang_tag = article.find("span", itemprop="programmingLanguage")
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        stars_tag = article.find("a", href=lambda h: h and h.endswith("/stargazers"))
        total_stars = stars_tag.get_text(strip=True) if stars_tag else "0"

        forks_tag = article.find("a", href=lambda h: h and h.endswith("/forks"))
        total_forks = forks_tag.get_text(strip=True) if forks_tag else "0"

        period_tag = article.find("span", class_="d-inline-block float-sm-right")
        period_stars = period_tag.get_text(strip=True) if period_tag else ""

        repos.append(
            {
                "name": repo_path,
                "url": f"https://github.com/{repo_path}",
                "description": description,
                "language": language,
                "total_stars": total_stars,
                "total_forks": total_forks,
                "period_stars": period_stars,
            }
        )

    return repos


def render_markdown(title: str, date_str: str, repos: list[dict]) -> str:
    lines = [f"# GitHub Trending — {title} ({date_str})", ""]

    if not repos:
        lines.append("_No data scraped._")
        return "\n".join(lines) + "\n"

    for i, repo in enumerate(repos, start=1):
        lines.append(f"## {i}. [{repo['name']}]({repo['url']})")
        if repo["description"]:
            lines.append(f"> {repo['description']}")
        meta = []
        if repo["language"]:
            meta.append(f"**Language:** {repo['language']}")
        meta.append(f"**Stars:** {repo['total_stars']}")
        meta.append(f"**Forks:** {repo['total_forks']}")
        if repo["period_stars"]:
            meta.append(f"**{repo['period_stars']}**")
        lines.append(" | ".join(meta))
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape GitHub Trending into Markdown files.")
    parser.add_argument("--lang", default="", help="spoken_language_code query param, e.g. 'en' (default: all languages)")
    parser.add_argument("--date", default=None, help="Override output date folder, format YYYY-MM-DD (default: today)")
    parser.add_argument("--force", action="store_true", help="Re-scrape even if today's files already exist")
    args = parser.parse_args()

    date_str = args.date or datetime.date.today().isoformat()
    out_dir = OUTPUT_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_files = [out_dir / filename for _, filename in RANGES.values()]
    if not args.force and all(f.exists() for f in expected_files):
        detail = "already generated today; use --force to re-run"
        log_run(date_str, status="skipped", detail=detail)
        print(f"[skip] {date_str} {detail}")
        return 0

    counts = {}
    for label, (since, filename) in RANGES.items():
        try:
            repos = fetch_trending(since, args.lang)
        except requests.RequestException as exc:
            print(f"[error] failed to fetch '{since}': {exc}", file=sys.stderr)
            continue

        markdown = render_markdown(label, date_str, repos)
        out_path = out_dir / filename
        out_path.write_text(markdown, encoding="utf-8")
        counts[label] = len(repos)
        print(f"[ok] {label}: {len(repos)} repos -> {out_path}")

    log_run(date_str, status="scraped", detail=", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
