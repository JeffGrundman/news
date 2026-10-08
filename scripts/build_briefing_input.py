"""Builds briefing-input.json: the last day's stories from every feed listed
in osmosfeed.yaml, each with outlet, headline, summary, link and time."""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser

HOURS = 30          # window kept, a little over a day so nothing falls through
MAX_PER_FEED = 40   # newest items per feed
SUMMARY_CHARS = 400

cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)


def feed_urls():
    text = open("osmosfeed.yaml", encoding="utf-8").read()
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        m = re.match(r"-\s*href:\s*(\S+)", line)
        if m:
            urls.append(m.group(1).strip("'\""))
    return urls


def clean(html_text):
    text = re.sub(r"<[^>]+>", " ", html_text or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:SUMMARY_CHARS]


def published(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


stories = []
problems = []

for url in feed_urls():
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:                      # noqa: BLE001
        problems.append(f"{url}: {exc}")
        continue
    if not parsed.entries:
        problems.append(f"{url}: no items")
        continue
    outlet = clean(parsed.feed.get("title", "")) or url
    kept = 0
    for entry in parsed.entries:
        when = published(entry)
        if when and when < cutoff:
            continue
        link = entry.get("link")
        title = clean(entry.get("title", ""))
        if not link or not title:
            continue
        stories.append({
            "outlet": outlet,
            "headline": title,
            "summary": clean(entry.get("summary", "")),
            "link": link,
            "published": when.isoformat() if when else "",
        })
        kept += 1
        if kept >= MAX_PER_FEED:
            break

stories.sort(key=lambda s: (s["outlet"].lower(), s["published"]), reverse=False)

output = {
    "built": datetime.now(timezone.utc).isoformat(),
    "window_hours": HOURS,
    "story_count": len(stories),
    "feeds_with_problems": problems,
    "stories": stories,
}

with open("briefing-input.json", "w", encoding="utf-8") as handle:
    json.dump(output, handle, ensure_ascii=False, indent=1)

print(f"{len(stories)} stories, {len(problems)} feed problems")
if not stories:
    sys.exit("no stories collected")
