#!/usr/bin/env python3
"""AI regulatory tracker.

Pulls official AI-policy feeds, keeps the AI-relevant items, merges them with
the previous run, and writes feed.json. Standard library only. Uploading is a
separate step (publish.sh) so this script never holds credentials.

Usage: tracker.py --out /var/lib/regtracker/feed.json
"""
import argparse
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 15 * 1024 * 1024
KEEP_DAYS = 120
MAX_ITEMS = 80
UA = os.environ.get("TRACKER_USER_AGENT", "ai-regulatory-tracker/1.0 (+https://github.com/Charitarth1/ai-regulatory-tracker)")

# "AI" is matched case-sensitively so words like "said" or "aid" don't count.
AI_EXACT = re.compile(r"\bA\.?I\b")
AI_TERMS = re.compile(
    r"artificial intelligence|machine learning|algorithm|automated decision|"
    r"frontier model|foundation model|general[- ]purpose (ai|model)|large language|\bLLMs?\b|"
    r"generative|deepfake|chatbot|agentic|neural network",
    re.I,
)
LAB_TERMS = re.compile(
    r"safety|safeguard|preparedness|\brisks?\b|governance|policy|alignment|misalign|"
    r"responsib|evaluat|red[- ]team|system card|model card|misuse|transparen|oversight",
    re.I,
)
# Media advisories ("Minister X to announce ...") say nothing until the real release.
ADVISORY = re.compile(r"\bto (announce|make an announcement|highlight|deliver remarks)\b", re.I)

# filter: "ai"   keep items that mention AI
#         "lab"  keep lab posts about safety, policy or risk
#         None   keep everything (source is already AI-specific)
SOURCES = [
    {"name": "European Commission (Digital)", "jur": "EU", "filter": "ai",
     "url": "https://digital-strategy.ec.europa.eu/en/rss.xml"},
    {"name": "European Data Protection Board", "jur": "EU", "filter": "ai",
     "url": "https://www.edpb.europa.eu/feed/news_en"},
    {"name": "UK AI Security Institute", "jur": "UK", "filter": None,
     "url": "https://www.gov.uk/government/organisations/ai-security-institute.atom"},
    {"name": "UK Government", "jur": "UK", "filter": "ai",
     "url": "https://www.gov.uk/search/news-and-communications.atom?keywords=artificial+intelligence"},
    {"name": "NIST", "jur": "US", "filter": "ai",
     "url": "https://www.nist.gov/news-events/news/rss.xml"},
    {"name": "CISA", "jur": "US", "filter": "ai",
     "url": "https://www.cisa.gov/news.xml"},
    {"name": "Innovation, Science and Economic Development Canada", "jur": "Canada", "filter": "ai",
     "url": "https://api.io.canada.ca/io-server/gc/news/en/v2?dept=departmentofindustry&sort=publishedDate&orderBy=desc&pick=50&format=atom"},
    {"name": "OpenAI", "jur": "Labs", "filter": "lab", "cap": 6,
     "url": "https://openai.com/news/rss.xml"},
    {"name": "Google DeepMind", "jur": "Labs", "filter": "lab", "cap": 6,
     "url": "https://deepmind.google/blog/rss.xml"},
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("feed larger than %d bytes" % MAX_BYTES)
    if b"<!ENTITY" in data[:4096]:
        raise ValueError("refusing feed with entity declarations")
    return data


def text(el, *tags):
    for t in tags:
        v = el.findtext(t)
        if v and v.strip():
            return v.strip()
    return ""


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def entries(root):
    for it in root.iter("item"):
        link = text(it, "link", "guid")
        yield (text(it, "title"), link, text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date"),
               text(it, "description"))
    for it in root.iter(ATOM + "entry"):
        link = ""
        for l in it.findall(ATOM + "link"):
            if l.get("rel", "alternate") == "alternate" and l.get("href"):
                link = l.get("href")
                break
        yield (text(it, ATOM + "title"), link, text(it, ATOM + "published", ATOM + "updated"),
               text(it, ATOM + "summary", ATOM + "content"))


def keep(src, title, summary):
    f = src["filter"]
    if ADVISORY.search(title):
        return False
    if f is None:
        return True
    hay = title + " " + summary
    is_ai = bool(AI_EXACT.search(hay) or AI_TERMS.search(hay))
    if f == "ai":
        return is_ai
    if f == "lab":
        return bool(LAB_TERMS.search(title))
    return False


def collect(now):
    items, report = [], []
    cutoff = now - dt.timedelta(days=KEEP_DAYS)
    for src in SOURCES:
        try:
            root = ET.fromstring(fetch(src["url"]))
        except Exception as e:  # one broken source must not stop the run
            report.append("%-48s FAILED %s" % (src["name"], e))
            continue
        n, cap = 0, src.get("cap", 15)
        for title, link, date_s, summary in entries(root):
            if n >= cap:
                break
            title = strip_html(title)[:240]
            summary = strip_html(summary)[:600]
            when = parse_date(date_s)
            if not title or not link.startswith("https://") or not when or when < cutoff:
                continue
            if not keep(src, title, summary):
                continue
            items.append({
                "id": hashlib.sha1(link.encode()).hexdigest()[:16],
                "title": title,
                "url": link[:500],
                "source": src["name"],
                "jurisdiction": src["jur"],
                "date": when.strftime("%Y-%m-%d"),
            })
            n += 1
        report.append("%-48s kept %d" % (src["name"], n))
    return items, report


def load_previous(path):
    try:
        with open(path) as f:
            return json.load(f).get("items", [])
    except (OSError, ValueError):
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="where to write feed.json")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    fresh, report = collect(now)
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")

    # Merge with the previous run so items survive after a source rotates them out.
    by_id = {i["id"]: i for i in load_previous(args.out) if i.get("date", "") >= cutoff}
    by_id.update({i["id"]: i for i in fresh})
    items = sorted(by_id.values(), key=lambda i: (i["date"], i["title"]), reverse=True)[:MAX_ITEMS]

    ok_sources = sum(1 for r in report if "FAILED" not in r)
    if ok_sources == 0:
        print("\n".join(report), file=sys.stderr)
        sys.exit("every source failed; keeping the previous feed.json")

    feed = {
        "version": 1,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [{"name": s["name"], "jurisdiction": s["jur"]} for s in SOURCES],
        "items": items,
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(feed, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print("\n".join(report))
    print("wrote %d items to %s" % (len(items), args.out))


if __name__ == "__main__":
    main()
