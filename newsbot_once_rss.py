#!/usr/bin/env python3
"""
newsbot_once_rss.py
- Single-run script: fetches global news from RSS feeds and sends summary to Telegram.
- Zero cost. Works with GitHub Actions.
"""

import os
import requests
from datetime import datetime
import feedparser

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://feeds.reuters.com/reuters/worldNews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"
]

PAGE_SIZE = 8


def fetch_rss_items(feeds, limit=10):
    items = []
    for url in feeds:
        try:
            d = feedparser.parse(url)
            for entry in d.entries:
                items.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", "").strip(),
                    "source": d.feed.get("title", "")
                })
        except Exception as e:
            print("Error:", e)

    # remove duplicates
    seen = set()
    unique = []
    for item in items:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)

    return unique[:limit]


def format_message(items):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"*🌍 NewsAlertBot — Global News ({now})*", ""]

    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it['title']}\n_{it['source']}_\n{it['link']}\n")

    return "\n".join(lines)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload)
    r.raise_for_status()


def main():
    items = fetch_rss_items(RSS_FEEDS, PAGE_SIZE)
    if not items:
        print("No news fetched.")
        return

    msg = format_message(items)
    send_telegram(msg)
    print("Sent:", len(items), "items")


if __name__ == "__main__":
    main()
