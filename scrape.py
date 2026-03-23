#!/usr/bin/env python3
"""
News scraper for US/Iran coverage.
Fetches from trusted RSS feeds + YouTube news channels.
Runs via GitHub Actions every 5 minutes.
"""

import feedparser
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

# ── Keywords filter ──────────────────────────────────────────────────────────
KEYWORDS = [
    "iran", "iranian", "tehran", "irgc", "persian gulf",
    "strait of hormuz", "khamenei", "nuclear deal", "jcpoa",
    "sanctions on iran", "us iran", "usa iran", "islamic republic",
    "raisi", "pezeshkian", "natanz", "fordow", "uranium enrichment",
    "middle east war", "israel iran", "iran war", "iran attack",
    "iran nuclear", "iran missile", "iran drone", "iran proxy",
    "hezbollah", "houthi", "iran-backed",
]

# ── Trusted RSS feeds ────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://feeds.reuters.com/reuters/worldNews",       "source": "Reuters"},
    {"url": "http://feeds.bbci.co.uk/news/world/rss.xml",        "source": "BBC News"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",         "source": "Al Jazeera"},
    {"url": "https://feeds.npr.org/1001/rss.xml",                "source": "NPR"},
    {"url": "https://www.theguardian.com/world/rss",             "source": "The Guardian"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "source": "NY Times"},
    {"url": "https://feeds.washingtonpost.com/rss/world",        "source": "Washington Post"},
    {"url": "https://www.voanews.com/api/zmgqrkermq",            "source": "Voice of America"},
    {"url": "https://foreignpolicy.com/feed/",                   "source": "Foreign Policy"},
    {"url": "https://www.atlanticcouncil.org/feed/",             "source": "Atlantic Council"},
    {"url": "https://www.axios.com/feeds/feed.rss",              "source": "Axios"},
    {"url": "https://thehill.com/feed/",                         "source": "The Hill"},
    {"url": "https://apnews.com/rss/apf-topnews",                "source": "AP News"},
]

# ── YouTube channel RSS feeds (no API key needed) ────────────────────────────
YOUTUBE_CHANNELS = [
    {"channel_id": "UCNye-wNBqNL5ZzHSJdse68g", "name": "Al Jazeera English"},
    {"channel_id": "UCeY0bbntWzzVIaj2z3QigXg", "name": "NBC News"},
    {"channel_id": "UCBi2mrWuNuyYy4gbM6fU18Q", "name": "ABC News"},
    {"channel_id": "UCknLrEdhRCp1aegoMqRaCZg", "name": "DW News"},
    {"channel_id": "UCQfwfsi5VrQ8yKZ-UGuJ4sA", "name": "France 24"},
    {"channel_id": "UC16niRr50-MSBwiO3YDb3RA", "name": "BBC News"},
    {"channel_id": "UChqUTb7kYRX8-EiaN3XFrSQ", "name": "Reuters"},
]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def is_relevant(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in KEYWORDS)


def extract_image(entry) -> str | None:
    """Try several RSS media fields to find a thumbnail URL."""
    # media:thumbnail
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    # media:content
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            if m.get("medium") == "image" or (m.get("type", "").startswith("image")):
                return m.get("url")
    # enclosures
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href") or enc.get("url")
    # og:image in content
    for field in ["content", "summary", "description"]:
        raw = getattr(entry, field, None)
        if raw:
            raw_str = raw[0].get("value", "") if isinstance(raw, list) else str(raw)
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_str)
            if m:
                return m.group(1)
    return None


def parse_date(entry) -> str:
    for field in ["published", "updated"]:
        val = entry.get(field)
        if val:
            try:
                return parsedate_to_datetime(val).isoformat()
            except Exception:
                return val
    return datetime.now(timezone.utc).isoformat()


def scrape_news() -> list[dict]:
    articles = []
    seen = set()

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:25]:
                title   = strip_html(entry.get("title", ""))
                summary = strip_html(entry.get("summary", entry.get("description", "")))[:600]
                link    = entry.get("link", "")

                if not link or link in seen:
                    continue
                if not is_relevant(title + " " + summary):
                    continue

                seen.add(link)
                articles.append({
                    "type":      "article",
                    "title":     title,
                    "summary":   summary,
                    "link":      link,
                    "source":    feed_info["source"],
                    "published": parse_date(entry),
                    "image":     extract_image(entry),
                })
        except Exception as exc:
            print(f"[WARN] {feed_info['source']}: {exc}", file=sys.stderr)

    return articles


def scrape_videos() -> list[dict]:
    videos = []
    seen = set()

    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title   = strip_html(entry.get("title", ""))
                summary = strip_html(entry.get("summary", ""))[:400]
                link    = entry.get("link", "")

                if not link or link in seen:
                    continue
                if not is_relevant(title + " " + summary):
                    continue

                # Extract video ID
                vid_match = re.search(r"v=([A-Za-z0-9_-]{11})", link)
                if not vid_match:
                    # try yt:videoId tag
                    vid_id = entry.get("yt_videoid", "")
                else:
                    vid_id = vid_match.group(1)

                if not vid_id or vid_id in seen:
                    continue

                seen.add(vid_id)
                seen.add(link)

                thumb = f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                videos.append({
                    "type":      "video",
                    "title":     title,
                    "summary":   summary,
                    "video_id":  vid_id,
                    "link":      f"https://www.youtube.com/watch?v={vid_id}",
                    "embed_url": f"https://www.youtube-nocookie.com/embed/{vid_id}",
                    "source":    ch["name"],
                    "published": parse_date(entry),
                    "image":     thumb,
                })
        except Exception as exc:
            print(f"[WARN] YouTube/{ch['name']}: {exc}", file=sys.stderr)

    return videos


def main():
    Path("data").mkdir(exist_ok=True)
    news_file = Path("data/news.json")

    # Load existing data
    existing_articles, existing_videos = [], []
    if news_file.exists():
        try:
            old = json.loads(news_file.read_text())
            existing_articles = old.get("articles", [])
            existing_videos   = old.get("videos", [])
        except Exception:
            pass

    # Scrape fresh content
    new_articles = scrape_news()
    new_videos   = scrape_videos()

    # Merge — new content first, deduplicate by link / video_id
    def merge(existing, fresh, key="link"):
        seen = {item.get(key) for item in existing if item.get(key)}
        added = [i for i in fresh if i.get(key) and i.get(key) not in seen]
        return (added + existing)[:200]

    all_articles = merge(existing_articles, new_articles, key="link")
    all_videos   = merge(existing_videos,   new_videos,   key="video_id")

    payload = {
        "articles":     all_articles,
        "videos":       all_videos,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_articles": len(all_articles),
        "total_videos":   len(all_videos),
    }

    news_file.write_text(json.dumps(payload, indent=2, default=str))
    print(f"✓ {len(all_articles)} articles ({len(new_articles)} new) | "
          f"{len(all_videos)} videos ({len(new_videos)} new)")


if __name__ == "__main__":
    main()
