#!/usr/bin/env python3
"""
Citizen-journalism scraper for US/Iran coverage.
Sources: X.com (via Nitter), Telegram public channels, Reddit, YouTube OSINT channels.
No mainstream/controlled media.
"""

import feedparser
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Keywords filter ──────────────────────────────────────────────────────────
KEYWORDS = [
    "iran", "iranian", "tehran", "irgc", "persian gulf",
    "strait of hormuz", "khamenei", "nuclear deal", "jcpoa",
    "iran war", "iran attack", "iran nuclear", "iran missile",
    "iran drone", "iran proxy", "iran sanction", "iran us",
    "us iran", "natanz", "fordow", "uranium", "islamic republic",
    "hezbollah", "houthi", "iran-backed", "raisi", "pezeshkian",
    "trump iran", "israel iran", "iran bomb", "hormuz",
]

def is_relevant(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in KEYWORDS)

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()

def parse_date_str(s: str) -> str:
    if not s:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(s).isoformat()
    except Exception:
        try:
            # ISO format (Telegram uses this)
            return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
        except Exception:
            return s

# ════════════════════════════════════════════════════════
#  REDDIT
# ════════════════════════════════════════════════════════

REDDIT_FEEDS = [
    {"url": "https://www.reddit.com/r/worldnews/search.rss?q=iran+war+us&sort=new&limit=25", "source": "r/worldnews"},
    {"url": "https://www.reddit.com/r/geopolitics/search.rss?q=iran+us&sort=new&limit=25",  "source": "r/geopolitics"},
    {"url": "https://www.reddit.com/r/iran/new.rss?limit=25",                                "source": "r/iran"},
    {"url": "https://www.reddit.com/r/MiddleEast/search.rss?q=iran+us&sort=new&limit=25",   "source": "r/MiddleEast"},
    {"url": "https://www.reddit.com/r/OSINT/search.rss?q=iran&sort=new&limit=25",           "source": "r/OSINT"},
    {"url": "https://www.reddit.com/r/conspiracy/search.rss?q=iran+war&sort=new&limit=15",  "source": "r/conspiracy"},
    {"url": "https://www.reddit.com/r/collapse/search.rss?q=iran&sort=new&limit=15",        "source": "r/collapse"},
    {"url": "https://www.reddit.com/r/NeutralPolitics/search.rss?q=iran&sort=new&limit=15", "source": "r/NeutralPolitics"},
]

def scrape_reddit() -> list[dict]:
    articles = []
    seen = set()

    for feed_info in REDDIT_FEEDS:
        try:
            resp = requests.get(feed_info["url"], headers=HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            for entry in feed.entries[:20]:
                title   = strip_html(entry.get("title", ""))
                summary = strip_html(entry.get("summary", ""))[:500]
                link    = entry.get("link", "")
                author  = entry.get("author", "").replace("/u/", "u/")

                if not link or link in seen:
                    continue
                if not is_relevant(title + " " + summary):
                    continue

                seen.add(link)

                # Try to get thumbnail from media content
                image = None
                if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                    image = entry.media_thumbnail[0].get("url")

                articles.append({
                    "platform": "reddit",
                    "source":   feed_info["source"],
                    "author":   author or "Reddit user",
                    "title":    title,
                    "summary":  summary,
                    "link":     link,
                    "published": parse_date_str(entry.get("published", "")),
                    "image":    image,
                })
        except Exception as exc:
            print(f"[WARN] Reddit/{feed_info['source']}: {exc}", file=sys.stderr)

    return articles


# ════════════════════════════════════════════════════════
#  TELEGRAM  (scrape public t.me/s/ pages)
# ════════════════════════════════════════════════════════

TELEGRAM_CHANNELS = [
    # OSINT & independent conflict trackers
    {"channel": "GeoConfirmed",       "name": "GeoConfirmed"},
    {"channel": "MilitaryMaps",       "name": "Military Maps"},
    {"channel": "Conflicts",          "name": "Conflicts"},
    {"channel": "war_monitor",        "name": "War Monitor"},
    {"channel": "Intel_Art",          "name": "Intel Art"},
    {"channel": "OSINTdefender",      "name": "OSINT Defender"},
    {"channel": "CaucasusWatch",      "name": "Caucasus Watch"},
    {"channel": "Rybar_eng",          "name": "Rybar (EN)"},
    {"channel": "MiddleEastSpectator","name": "ME Spectator"},
    {"channel": "IranOSINT",          "name": "Iran OSINT"},
    {"channel": "wartranslated",      "name": "War Translated"},
    {"channel": "FarsNews_EN",        "name": "Fars News (EN)"},
    {"channel": "IranWar",            "name": "Iran War Updates"},
]

def scrape_telegram() -> list[dict]:
    posts = []
    seen = set()

    for ch in TELEGRAM_CHANNELS:
        url = f"https://t.me/s/{ch['channel']}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.select(".tgme_widget_message_wrap")

            for msg in messages[-20:]:  # most recent 20
                # Text
                text_el = msg.select_one(".tgme_widget_message_text")
                text = text_el.get_text(" ", strip=True) if text_el else ""
                if not text or not is_relevant(text):
                    continue

                # Link to specific post
                link_el = msg.select_one(".tgme_widget_message_date a")
                link = link_el["href"] if link_el else url
                if link in seen:
                    continue
                seen.add(link)

                # Date
                time_el = msg.select_one("time")
                published = time_el.get("datetime", "") if time_el else ""

                # Image (photo post)
                image = None
                img_el = msg.select_one(".tgme_widget_message_photo_wrap")
                if img_el:
                    style = img_el.get("style", "")
                    m = re.search(r"url\(['\"]?(https?://[^'\")]+)['\"]?\)", style)
                    if m:
                        image = m.group(1)

                # Video thumbnail
                if not image:
                    vid_el = msg.select_one(".tgme_widget_message_video_player")
                    if vid_el:
                        style = vid_el.get("style", "")
                        m = re.search(r"url\(['\"]?(https?://[^'\")]+)['\"]?\)", style)
                        if m:
                            image = m.group(1)

                posts.append({
                    "platform": "telegram",
                    "source":   ch["name"],
                    "author":   f"@{ch['channel']}",
                    "title":    text[:120].rstrip() + ("…" if len(text) > 120 else ""),
                    "summary":  text[:500],
                    "link":     link,
                    "published": parse_date_str(published),
                    "image":    image,
                })

            time.sleep(0.5)  # be polite to t.me

        except Exception as exc:
            print(f"[WARN] Telegram/{ch['channel']}: {exc}", file=sys.stderr)

    return posts


# ════════════════════════════════════════════════════════
#  X / TWITTER  (via Nitter RSS — multiple instance fallback)
# ════════════════════════════════════════════════════════

NITTER_INSTANCES = [
    "nitter.poast.org",
    "nitter.net",
    "nitter.1d4.us",
    "nitter.fdn.fr",
    "nitter.it",
    "nitter.nl",
]

X_SEARCHES = [
    "iran war us",
    "#IranWar",
    "iran nuclear attack",
    "iran OSINT",
    "iran trump",
]

def fetch_nitter_rss(query: str, instance: str) -> list | None:
    """Returns feed entries or None on failure."""
    url = f"https://{instance}/search/rss?q={requests.utils.quote(query)}&f=tweets"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            return None
        return feed.entries
    except Exception:
        return None

def scrape_twitter() -> list[dict]:
    posts = []
    seen = set()

    for query in X_SEARCHES:
        entries = None
        for instance in NITTER_INSTANCES:
            entries = fetch_nitter_rss(query, instance)
            if entries:
                break

        if not entries:
            print(f"[WARN] X: all Nitter instances failed for '{query}'", file=sys.stderr)
            continue

        for entry in entries[:15]:
            title   = strip_html(entry.get("title", ""))
            link    = entry.get("link", "")
            author  = entry.get("author", "")

            if not link or link in seen:
                continue
            if not is_relevant(title):
                continue

            seen.add(link)

            # Normalize link from nitter back to x.com
            x_link = re.sub(r"https?://[^/]+/", "https://x.com/", link)

            # Thumbnail from media
            image = None
            if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image = entry.media_thumbnail[0].get("url")
            elif hasattr(entry, "media_content") and entry.media_content:
                for m in entry.media_content:
                    if m.get("url"):
                        image = m.get("url")
                        break

            posts.append({
                "platform": "twitter",
                "source":   "X.com",
                "author":   author or "X user",
                "title":    title[:200],
                "summary":  title,
                "link":     x_link,
                "published": parse_date_str(entry.get("published", "")),
                "image":    image,
            })

    return posts


# ════════════════════════════════════════════════════════
#  YOUTUBE  (independent OSINT / field channels)
# ════════════════════════════════════════════════════════

YOUTUBE_CHANNELS = [
    # OSINT / independent / conflict-focused
    {"channel_id": "UCNye-wNBqNL5ZzHSJdse68g", "name": "Al Jazeera English"},
    {"channel_id": "UCknLrEdhRCp1aegoMqRaCZg", "name": "DW News"},
    {"channel_id": "UCQfwfsi5VrQ8yKZ-UGuJ4sA", "name": "France 24 English"},
    {"channel_id": "UC7fWeaHhqgM4Ry-RMpM2YYw", "name": "TRT World"},
    {"channel_id": "UCW6Vz5MiyM3gM9Mxjbk6cZg", "name": "Bellingcat"},
    {"channel_id": "UCGezdX2FEl8FvGARfMUdS8w", "name": "The Grayzone"},
    {"channel_id": "UCBi2mrWuNuyYy4gbM6fU18Q", "name": "ABC News"},
    {"channel_id": "UC16niRr50-MSBwiO3YDb3RA", "name": "BBC News"},
]

def scrape_youtube() -> list[dict]:
    videos = []
    seen = set()

    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title   = strip_html(entry.get("title", ""))
                summary = strip_html(entry.get("summary", ""))[:400]
                link    = entry.get("link", "")

                if not link or link in seen:
                    continue
                if not is_relevant(title + " " + summary):
                    continue

                vid_match = re.search(r"v=([A-Za-z0-9_-]{11})", link)
                vid_id = vid_match.group(1) if vid_match else entry.get("yt_videoid", "")
                if not vid_id or vid_id in seen:
                    continue

                seen.add(vid_id)
                seen.add(link)

                videos.append({
                    "type":      "video",
                    "title":     title,
                    "summary":   summary,
                    "video_id":  vid_id,
                    "link":      f"https://www.youtube.com/watch?v={vid_id}",
                    "embed_url": f"https://www.youtube-nocookie.com/embed/{vid_id}",
                    "source":    ch["name"],
                    "platform":  "youtube",
                    "published": parse_date_str(entry.get("published", "")),
                    "image":     f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                })
        except Exception as exc:
            print(f"[WARN] YouTube/{ch['name']}: {exc}", file=sys.stderr)

    return videos


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

def main():
    Path("data").mkdir(exist_ok=True)
    news_file = Path("data/news.json")

    # Load existing
    existing_articles, existing_videos = [], []
    if news_file.exists():
        try:
            old = json.loads(news_file.read_text())
            existing_articles = old.get("articles", [])
            existing_videos   = old.get("videos", [])
        except Exception:
            pass

    # Scrape all sources
    print("Scraping Reddit…")
    reddit_posts = scrape_reddit()
    print(f"  {len(reddit_posts)} relevant posts")

    print("Scraping Telegram…")
    tg_posts = scrape_telegram()
    print(f"  {len(tg_posts)} relevant posts")

    print("Scraping X via Nitter…")
    x_posts = scrape_twitter()
    print(f"  {len(x_posts)} relevant posts")

    new_articles = reddit_posts + tg_posts + x_posts

    print("Scraping YouTube…")
    new_videos = scrape_youtube()
    print(f"  {len(new_videos)} relevant videos")

    # Merge (deduplicate by link)
    def merge(existing, fresh, key="link"):
        seen = {item.get(key) for item in existing if item.get(key)}
        added = [i for i in fresh if i.get(key) and i.get(key) not in seen]
        return (added + existing)[:300]

    all_articles = merge(existing_articles, new_articles, key="link")
    all_videos   = merge(existing_videos,   new_videos,   key="video_id")

    payload = {
        "articles":       all_articles,
        "videos":         all_videos,
        "last_updated":   datetime.now(timezone.utc).isoformat(),
        "total_articles": len(all_articles),
        "total_videos":   len(all_videos),
    }

    news_file.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n✓ Saved {len(all_articles)} articles ({len(new_articles)} new) "
          f"| {len(all_videos)} videos ({len(new_videos)} new)")


if __name__ == "__main__":
    main()
