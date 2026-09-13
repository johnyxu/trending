#!/usr/bin/env python3
"""Scrape github.com/trending and save today/week/month reports into archives,
update project profiles under projects/, and refresh README.md index.

Usage:
    python scrape_trending.py [--lang SPOKEN_LANGUAGE_CODE] [--date YYYY-MM-DD] [--force] [--refresh-readme]

Output:
    archives/<YYYY>/<MM>/<YYYY-MM-DD>-trending-{today,week,month}.md
    projects/<owner>__<repo>.md
    README.md
"""

import argparse
import datetime
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trending-scraper/1.0)"}
LOCAL_TZ = ZoneInfo("Australia/Melbourne")

RANGES = {
    "today": ("daily", "trending-today.md"),
    "week": ("weekly", "trending-week.md"),
    "month": ("monthly", "trending-month.md"),
}

OUTPUT_ROOT = Path(__file__).resolve().parent
ARCHIVES_ROOT = OUTPUT_ROOT / "archives"
PROJECTS_ROOT = OUTPUT_ROOT / "projects"
README_PATH = OUTPUT_ROOT / "README.md"
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


def sanitize_filename(repo_name: str) -> str:
    """Convert 'owner/repo' into 'owner__repo.md'."""
    safe_name = repo_name.replace("/", "__").replace("\\", "__")
    return f"{safe_name}.md"


def parse_project_markdown(file_path: Path) -> dict:
    """Parse an existing project profile markdown file."""
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    data = {
        "name": "",
        "url": "",
        "description": "",
        "language": "",
        "first_seen": "",
        "last_seen": "",
        "latest_stars": "0",
        "latest_forks": "0",
        "history": [],
    }

    in_history_table = False
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        if line_str.startswith("# ["):
            m = re.match(r"^#\s+\[([^\]]+)\]\((https://github\.com/[^\)]+)\)", line_str)
            if m:
                data["name"] = m.group(1).strip()
                data["url"] = m.group(2).strip()
        elif line_str.startswith("> "):
            desc = line_str[2:].strip()
            if desc != "_No description provided._":
                data["description"] = desc
        elif line_str.startswith("- **Primary Language:**"):
            m = re.search(r"`([^`]+)`", line_str)
            if m:
                data["language"] = m.group(1).strip()
        elif line_str.startswith("- **First Seen on Trending:**"):
            data["first_seen"] = line_str.replace("- **First Seen on Trending:**", "").strip()
        elif line_str.startswith("- **Last Seen on Trending:**"):
            data["last_seen"] = line_str.replace("- **Last Seen on Trending:**", "").strip()
        elif line_str.startswith("- **Latest Stars:**"):
            parts = [p.strip() for p in line_str.split("|")]
            for part in parts:
                if "Latest Stars:" in part:
                    data["latest_stars"] = part.replace("- **Latest Stars:**", "").strip()
                elif "Latest Forks:" in part:
                    data["latest_forks"] = part.replace("**Latest Forks:**", "").strip()
        elif line_str.startswith("## 📈 Trending History"):
            in_history_table = True
        elif in_history_table and line_str.startswith("|") and not line_str.startswith("| Date") and not line_str.startswith("| :---"):
            cols = [c.strip() for c in line_str.split("|")[1:-1]]
            if len(cols) >= 6:
                h_date, h_range, h_rank, h_period, h_stars, h_forks = cols[:6]
                rank_num = int(h_rank.replace("#", "")) if h_rank.replace("#", "").isdigit() else None
                data["history"].append({
                    "date": h_date,
                    "range": h_range,
                    "rank": rank_num,
                    "period_stars": h_period if h_period != "-" else "",
                    "total_stars": h_stars if h_stars != "-" else "",
                    "total_forks": h_forks if h_forks != "-" else "",
                })

    return data


def render_project_markdown(repo_data: dict) -> str:
    """Render a single project's Markdown profile."""
    name = repo_data["name"]
    url = repo_data["url"]
    description = repo_data.get("description", "")
    language = repo_data.get("language") or "Not Specified"
    first_seen = repo_data.get("first_seen", "")
    last_seen = repo_data.get("last_seen", "")
    history = repo_data.get("history", [])

    today_count = sum(1 for h in history if h.get("range") in ("today", "daily"))
    week_count = sum(1 for h in history if h.get("range") in ("week", "weekly"))
    month_count = sum(1 for h in history if h.get("range") in ("month", "monthly"))
    total_count = len(history)

    latest_stars = repo_data.get("latest_stars", "0")
    latest_forks = repo_data.get("latest_forks", "0")

    lines = [
        f"# [{name}]({url})",
        "",
        f"> {description}" if description else "> _No description provided._",
        "",
        "## 📊 Project Metadata",
        "",
        f"- **Repository:** [{name}]({url})",
        f"- **Primary Language:** `{language}`",
        f"- **First Seen on Trending:** {first_seen}",
        f"- **Last Seen on Trending:** {last_seen}",
        f"- **Total Appearances:** {total_count} (Daily: {today_count}, Weekly: {week_count}, Monthly: {month_count})",
        f"- **Latest Stars:** {latest_stars} | **Latest Forks:** {latest_forks}",
        "",
        "## 📈 Trending History",
        "",
        "| Date | Range | Rank | Period Stars | Total Stars | Forks |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    # Sort history chronologically descending
    sorted_history = sorted(
        history,
        key=lambda x: (x["date"], 0 if "today" in x.get("range", "") or "daily" in x.get("range", "") else (1 if "week" in x.get("range", "") or "weekly" in x.get("range", "") else 2)),
        reverse=True,
    )

    for h in sorted_history:
        rank_str = f"#{h['rank']}" if h.get("rank") else "-"
        range_label = h.get("range", "").replace("daily", "today").replace("weekly", "week").replace("monthly", "month")
        p_stars = h.get("period_stars") or "-"
        t_stars = h.get("total_stars") or "-"
        t_forks = h.get("total_forks") or "-"
        lines.append(f"| {h['date']} | {range_label} | {rank_str} | {p_stars} | {t_stars} | {t_forks} |")

    lines.append("")
    return "\n".join(lines)


def update_project_profile(repo_item: dict, date_str: str, range_label: str, rank: int) -> None:
    """Incrementally update or create a project Markdown file."""
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    repo_name = repo_item["name"]
    proj_filename = sanitize_filename(repo_name)
    proj_path = PROJECTS_ROOT / proj_filename

    if proj_path.exists():
        data = parse_project_markdown(proj_path)
    else:
        data = {
            "name": repo_name,
            "url": repo_item["url"],
            "description": repo_item.get("description", ""),
            "language": repo_item.get("language", ""),
            "first_seen": date_str,
            "last_seen": date_str,
            "latest_stars": repo_item.get("total_stars", "0"),
            "latest_forks": repo_item.get("total_forks", "0"),
            "history": [],
        }

    # Update metadata
    if repo_item.get("description"):
        data["description"] = repo_item["description"]
    if repo_item.get("language"):
        data["language"] = repo_item["language"]
    if not data.get("first_seen") or date_str < data["first_seen"]:
        data["first_seen"] = date_str
    if not data.get("last_seen") or date_str >= data["last_seen"]:
        data["last_seen"] = date_str
        if repo_item.get("total_stars"):
            data["latest_stars"] = repo_item["total_stars"]
        if repo_item.get("total_forks"):
            data["latest_forks"] = repo_item["total_forks"]

    # Avoid duplicate history entries for same date and range
    existing_keys = {(h["date"], h["range"].replace("daily", "today").replace("weekly", "week").replace("monthly", "month")) for h in data["history"]}
    normalized_range = range_label.replace("daily", "today").replace("weekly", "week").replace("monthly", "month")
    if (date_str, normalized_range) not in existing_keys:
        data["history"].append({
            "date": date_str,
            "range": normalized_range,
            "rank": rank,
            "period_stars": repo_item.get("period_stars", ""),
            "total_stars": repo_item.get("total_stars", ""),
            "total_forks": repo_item.get("total_forks", ""),
        })

    proj_path.write_text(render_project_markdown(data), encoding="utf-8")


def refresh_readme_dashboard() -> None:
    """Read all project markdown files and rebuild the README.md index."""
    if not PROJECTS_ROOT.exists():
        return

    projects = {}
    all_dates = set()

    for p_file in PROJECTS_ROOT.glob("*.md"):
        data = parse_project_markdown(p_file)
        if not data["name"]:
            continue
        projects[data["name"]] = data
        for h in data["history"]:
            if h.get("date"):
                all_dates.add(h["date"])

    def parse_star_count(s: str) -> int:
        clean = re.sub(r"[^\d]", "", str(s))
        return int(clean) if clean else 0

    sorted_by_freq = sorted(
        projects.values(),
        key=lambda x: (len(x["history"]), parse_star_count(x.get("latest_stars", 0))),
        reverse=True,
    )

    by_language = defaultdict(list)
    for p in projects.values():
        lang = p.get("language") or "Other / Markdown"
        by_language[lang].append(p)

    sorted_languages = sorted(by_language.keys(), key=lambda l: len(by_language[l]), reverse=True)

    sorted_by_recent = sorted(
        projects.values(),
        key=lambda x: (x.get("first_seen", ""), len(x["history"])),
        reverse=True,
    )

    total_repos = len(projects)
    total_records = sum(len(p["history"]) for p in projects.values())
    first_date = min(all_dates) if all_dates else "N/A"
    last_date = max(all_dates) if all_dates else "N/A"

    lines = [
        "# 🚀 GitHub Trending Archive & Project Index",
        "",
        "Automated daily tracker, aggregator, and curated index for [GitHub Trending](https://github.com/trending) repositories.",
        "",
        "## 📊 Overview Statistics",
        "",
        f"- **Unique Projects Tracked:** `{total_repos}`",
        f"- **Total Trending Snapshots:** `{total_records}`",
        f"- **Tracking Range:** `{first_date}` ~ `{last_date}`",
        f"- **Archives Directory:** [`archives/`](archives/)",
        f"- **Project Profiles Directory:** [`projects/`](projects/)",
        "",
        "---",
        "",
        "## 🏆 Top Trending Repositories (Most Frequent)",
        "",
        "Repositories with the highest number of appearances on GitHub Trending across daily, weekly, and monthly leaderboards.",
        "",
        "| Rank | Repository | Language | Total Appearances | Latest Stars | Description |",
        "| :---: | :--- | :--- | :---: | :---: | :--- |",
    ]

    for idx, p in enumerate(sorted_by_freq[:30], start=1):
        name = p["name"]
        file_name = sanitize_filename(name)
        lang = p.get("language") or "Other"
        appearances = len(p["history"])
        stars = p.get("latest_stars", "-")
        desc = p.get("description", "").replace("|", "\\|")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(
            f"| {idx} | [{name}](projects/{file_name}) | `{lang}` | **{appearances}** | {stars} | {desc} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🗂 Browse by Programming Language")
    lines.append("")

    lang_links = [
        f"[{lang} ({len(by_language[lang])})](#{lang.lower().replace(' ', '-').replace('/', '').replace('+', 'p').replace('#', 'sharp')})"
        for lang in sorted_languages[:15]
    ]
    lines.append(" | ".join(lang_links))
    lines.append("")

    for lang in sorted_languages[:12]:
        repos_in_lang = sorted(
            by_language[lang],
            key=lambda x: (len(x["history"]), parse_star_count(x.get("latest_stars", 0))),
            reverse=True,
        )
        lines.append(f"### {lang}")
        lines.append("")
        lines.append("| Repository | Appearances | Latest Stars | Description |")
        lines.append("| :--- | :---: | :---: | :--- |")
        for p in repos_in_lang[:10]:
            name = p["name"]
            file_name = sanitize_filename(name)
            appearances = len(p["history"])
            stars = p.get("latest_stars", "-")
            desc = p.get("description", "").replace("|", "\\|")
            if len(desc) > 75:
                desc = desc[:72] + "..."
            lines.append(f"| [{name}](projects/{file_name}) | **{appearances}** | {stars} | {desc} |")
        if len(repos_in_lang) > 10:
            lines.append(f"_...and {len(repos_in_lang) - 10} more `{lang}` repositories in [`projects/`](projects/)._")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 🆕 Recently Discovered Repositories")
    lines.append("")
    lines.append("| Repository | Language | First Seen | Latest Stars | Description |")
    lines.append("| :--- | :--- | :---: | :---: | :--- |")
    for p in sorted_by_recent[:15]:
        name = p["name"]
        file_name = sanitize_filename(name)
        lang = p.get("language") or "Other"
        first_seen = p.get("first_seen", "-")
        stars = p.get("latest_stars", "-")
        desc = p.get("description", "").replace("|", "\\|")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(f"| [{name}](projects/{file_name}) | `{lang}` | {first_seen} | {stars} | {desc} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ⚙️ Scraper Setup & Usage")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 -m venv .venv")
    lines.append("source .venv/bin/activate")
    lines.append("pip install -r requirements.txt")
    lines.append("```")
    lines.append("")
    lines.append("```bash")
    lines.append("# Scrape today's date, update archives, project profiles, and README")
    lines.append("python scrape_trending.py")
    lines.append("")
    lines.append("# Filter by spoken language (e.g. 'en', 'zh')")
    lines.append("python scrape_trending.py --lang en")
    lines.append("")
    lines.append("# Write into a specific date archive")
    lines.append("python scrape_trending.py --date 2026-08-01")
    lines.append("")
    lines.append("# Re-scrape and force update")
    lines.append("python scrape_trending.py --force")
    lines.append("```")
    lines.append("")
    lines.append("Daily updates are automated via [GitHub Actions](.github/workflows/daily-trending.yml).")
    lines.append("")

    README_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape GitHub Trending into Markdown files.")
    parser.add_argument("--lang", default="", help="spoken_language_code query param, e.g. 'en' (default: all languages)")
    parser.add_argument("--date", default=None, help="Override output date, format YYYY-MM-DD (default: today)")
    parser.add_argument("--force", action="store_true", help="Re-scrape even if today's files already exist")
    parser.add_argument("--refresh-readme", action="store_true", help="Only refresh README.md from current projects/ directory")
    args = parser.parse_args()

    if args.refresh_readme:
        refresh_readme_dashboard()
        print("[ok] Refreshed README.md")
        return 0

    date_str = args.date or datetime.datetime.now(LOCAL_TZ).date().isoformat()
    year, month, _ = date_str.split("-")
    month_dir = ARCHIVES_ROOT / year / month
    month_dir.mkdir(parents=True, exist_ok=True)

    expected_files = [month_dir / f"{date_str}-{filename}" for _, filename in RANGES.values()]
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
        out_path = month_dir / f"{date_str}-{filename}"
        out_path.write_text(markdown, encoding="utf-8")
        counts[label] = len(repos)
        print(f"[ok] {label}: {len(repos)} repos -> {out_path}")

        # Incrementally update project profiles
        for rank, repo_item in enumerate(repos, start=1):
            update_project_profile(repo_item, date_str, label, rank)

    # Refresh README index
    refresh_readme_dashboard()

    log_run(date_str, status="scraped", detail=", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

