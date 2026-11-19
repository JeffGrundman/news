"""Builds the briefing input: the last day's stories from every feed listed in
osmosfeed.yaml. The result is split into as many parts as it takes for each part
to stay under the size one read can handle: briefing-input.json,
briefing-input-2.json, briefing-input-3.json and so on. Every part lists all the
part names, so the reader always knows how many there are."""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape

import feedparser

HOURS = 24          # must match rule 1 in the briefing instructions
MAX_PER_FEED = 25   # newest items per feed
SUMMARY_CHARS = 180 # keeps the files small enough to read in one go

NAMES = {           # tidy up the names some feeds give themselves
    "Politics": "Politico",
    "POLITICO": "Politico Europe",
    "Straight Arrow": "Straight Arrow News",
    "Rest of World -": "Rest of World",
    "Reason Magazine": "Reason",
    "JPost.com - The Jerusalem Post - All News from the Middle East, Israel, and the Jewish World": "The Jerusalem Post",
    "The Moscow Times - Independent News From Russia": "The Moscow Times",
    "Daily Maverick - Latest News": "Daily Maverick",
    "Ars Technica - All content": "Ars Technica",
    "The Christian Science Monitor | World": "Christian Science Monitor",
    "The Conversation – Articles (US)": "The Conversation",
    "World news | The Guardian": "The Guardian",
    "Environment | The Guardian": "The Guardian",
    "NPR Topics: World": "NPR",
    "NPR Topics: Science": "NPR",
    "NPR Topics: Business": "NPR",
    "PBS News Hour - The Latest": "PBS NewsHour",
    "ABC News: International": "Associated Press, via ABC News",
    "ABC News: Business": "Associated Press, via ABC News",
    "Deutsche Welle": "DW News",
    "Business News": "CNBC",
    "Fortune | FORTUNE": "Fortune",
    "CBC | World News": "CBC",
    "CBC News": "CBC",
    "PolitiFact - Social Feed": "PolitiFact",
    "PolitiFact": "PolitiFact",
}

# Many news sites turn away requests that announce themselves as a script
# (feedparser's default), answering with an error page that has no items.
# Ask the way a browser does instead.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 30
ATTEMPTS = 3

# Outlet names exactly as the briefing instructions list them. A feed whose name
# comes out differently is flagged so the NAMES table can be fixed.
APPROVED = {
    "BBC News", "PBS NewsHour", "BNO News", "ProPublica", "Haaretz", "DW News",
    "Science News", "The Conversation", "Christian Science Monitor",
    "Foreign Policy", "The Dispatch", "Semafor", "NPR", "The Star (Malaysia)",
    "Carbon Brief", "Inside Climate News", "Positive News", "Ars Technica", "CBC",
    "Reason", "National Review", "Straight Arrow News", "The Kyiv Independent",
    "The Moscow Times", "The Diplomat", "Daily Maverick", "Rest of World",
    "The Guardian", "Associated Press, via ABC News", "Politico", "Politico Europe",
    "PolitiFact", "FactCheck.org", "Good News Network", "Good Good Good",
    "The Times of Israel", "The Jerusalem Post", "The Intercept", "STAT",
    "KFF Health News", "Fortune", "CNBC",
}

cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)


# Name each outlet by the web address of its feed, so a feed that renames
# itself (or a new feed added later) still lands under the right outlet.
DOMAINS = {
    "bbci.co.uk": "BBC News", "dw.com": "DW News", "theguardian.com": "The Guardian",
    "cbc.ca": "CBC", "arstechnica.com": "Ars Technica",
    "nationalreview.com": "National Review",
    "abcnews.go.com": "Associated Press, via ABC News",
    "pbs.org": "PBS NewsHour", "npr.org": "NPR", "sciencenews.org": "Science News",
    "propublica.org": "ProPublica", "csmonitor.com": "Christian Science Monitor",
    "theconversation.com": "The Conversation", "thedispatch.com": "The Dispatch",
    "semafor.com": "Semafor", "san.com": "Straight Arrow News", "reason.com": "Reason",
    "insideclimatenews.org": "Inside Climate News",
    "themoscowtimes.com": "The Moscow Times", "thediplomat.com": "The Diplomat",
    "restofworld.org": "Rest of World", "jpost.com": "The Jerusalem Post",
    "positive.news": "Positive News", "goodnewsnetwork.org": "Good News Network",
    "goodgoodgood.co": "Good Good Good", "bnonews.com": "BNO News",
    "dailymaverick.co.za": "Daily Maverick", "politico.com": "Politico",
    "politico.eu": "Politico Europe", "politifact.com": "PolitiFact",
    "factcheck.org": "FactCheck.org", "statnews.com": "STAT",
    "kffhealthnews.org": "KFF Health News", "fortune.com": "Fortune",
    "cnbc.com": "CNBC", "thestar.com.my": "The Star (Malaysia)",
    "kyivindependent.com": "The Kyiv Independent", "carbonbrief.org": "Carbon Brief",
    "theintercept.com": "The Intercept", "timesofisrael.com": "The Times of Israel",
    "foreignpolicy.com": "Foreign Policy", "haaretz.com": "Haaretz",
}


def outlet_for(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    for domain, name in DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def fetch(url):
    """Download a feed. Returns (bytes, None) or (None, reason)."""
    reason = "unknown error"
    for attempt in range(ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read(), None
        except urllib.error.HTTPError as exc:
            reason = f"HTTP {exc.code}"
            if exc.code in (401, 403, 404, 410):
                break                     # retrying will not help
        except Exception as exc:          # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
        time.sleep(3 * (attempt + 1))
    return None, reason


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
seen_links = set()

for url in feed_urls():
    body, reason = fetch(url)
    if body is None:
        problems.append(f"{url}: {reason}")
        continue
    try:
        parsed = feedparser.parse(body)
    except Exception as exc:                      # noqa: BLE001
        problems.append(f"{url}: could not read feed ({exc})")
        continue
    if not parsed.entries:
        start = body[:200].decode("utf-8", "replace").strip().replace("\n", " ")
        problems.append(f"{url}: no items (page began: {start[:80]})")
        continue
    raw_name = clean(parsed.feed.get("title", "")) or url
    outlet = outlet_for(url) or NAMES.get(raw_name, raw_name)
    if outlet not in APPROVED:
        problems.append(f"{url}: outlet name not recognised: {outlet!r}")
    kept = 0
    for entry in parsed.entries:
        when = published(entry)
        if when and when < cutoff:
            continue
        link = entry.get("link")
        title = clean(entry.get("title", ""))
        if not link or not title or link in seen_links:
            continue
        seen_links.add(link)
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

stories.sort(key=lambda s: (s["outlet"].lower(), s["published"]))

# split into parts small enough to read in one go; an outlet is never split
PART_BYTES = 60000

def part_name(i):
    return "briefing-input.json" if i == 0 else f"briefing-input-{i + 1}.json"

outlets = sorted({s["outlet"] for s in stories}, key=str.lower)
blocks, current, current_size = [], [], 0
for name in outlets:
    group = [s for s in stories if s["outlet"] == name]
    size = len(json.dumps(group, ensure_ascii=False))
    if current and current_size + size > PART_BYTES:
        blocks.append(current)
        current, current_size = [], 0
    current.extend(group)
    current_size += size
if current:
    blocks.append(current)

built = datetime.now(timezone.utc).isoformat()
names = [part_name(i) for i in range(len(blocks))]
for name, block in zip(names, blocks):
    with open(name, "w", encoding="utf-8") as handle:
        json.dump({
            "built": built,
            "window_hours": HOURS,
            "part": name,
            "all_parts": names,
            "outlets_here": sorted({s["outlet"] for s in block}, key=str.lower),
            "story_count": len(block),
            "feeds_with_problems": problems,
            "stories": block,
        }, handle, ensure_ascii=False, indent=1)

# remove parts left over from a bigger collection on an earlier day
import os
extra = 1
while True:
    stale = part_name(len(blocks) + extra - 1)
    if stale in names or not os.path.exists(stale):
        break
    os.remove(stale)
    extra += 1

print(f"{len(stories)} stories in {len(blocks)} parts, {len(problems)} feed problems")
if not stories:
    sys.exit("no stories collected")
