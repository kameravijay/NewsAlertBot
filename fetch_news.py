# fetch_news.py
"""
Fetch top headlines from RSS feeds and post to Telegram channel(s).

Usage (locally/test):
    python fetch_news.py --test

Environment variables (required):
    TELEGRAM_BOT_TOKEN  - Telegram bot token (from BotFather)
    TELEGRAM_CHAT_IDS   - Comma-separated Telegram chat IDs or channel IDs (e.g. -1001234567890)

How it works:
 - Fetches items from the RSS FEEDS list
 - Keeps a simple seen-title dedupe per run
 - Builds a compact message (time + top N headlines)
 - Posts to each chat id with Telegram sendMessage API (HTML mode)

Designed to be run hourly (we will add a GitHub Actions schedule).
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Set

import requests
import feedparser

# --------------- CONFIG ---------------

# RSS feeds to aggregate (feel free to edit)
FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.reuters.com/Reuters/worldNews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://news.google.com/rss/search?q=world+news&hl=en-US&gl=US&ceid=US:en",
    # add or remove feeds as you like
]

# Maximum number of headlines to include in a single message
MAX_HEADLINES = 8

# Timeout for HTTP requests
REQUEST_TIMEOUT = 10  # seconds

# Telegram API base
TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/{method}"

# Optional: a short signature appended to each message
SIGNATURE = "\n\n— NewsAlertBot"

# --------------- LOGGING ---------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fetch_news")

# --------------- HELPERS ---------------


def read_env_secrets():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids = os.environ.get("TELEGRAM_CHAT_IDS")
    if not token or not chat_ids:
        logger.error("Missing required environment variables. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS.")
        raise SystemExit(1)
    # normalize chat ids into a list
    chat_list = [c.strip() for c in chat_ids.split(",") if c.strip()]
    return token, chat_list


def fetch_feed_entries(feed_url: str) -> List[Dict]:
    """
    Fetch the RSS/ATOM feed via requests (so we can use timeout and headers),
    then parse the returned bytes with feedparser.parse().
    """
    headers = {
        "User-Agent": "NewsAlertBot/1.0 (+https://github.com/kameravijay/NewsAlertBot)"
    }
    try:
        resp = requests.get(feed_url, timeout=REQUEST_TIMEOUT, headers=headers)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        entries = []
        for e in parsed.entries:
            title = e.get("title", "").strip()
            link = e.get("link", "").strip()
            published = e.get("published", e.get("updated", ""))
            entries.append({"title": title, "link": link, "published": published})
        return entries
    except requests.exceptions.RequestException as rex:
        logger.warning("HTTP error fetching feed %s : %s", feed_url, rex)
    except Exception as ex:
        logger.warning("Failed to parse feed %s : %s", feed_url, ex)
    return []


def collect_top_headlines(feeds: List[str], max_items: int = MAX_HEADLINES) -> List[Dict]:
    seen_titles: Set[str] = set()
    collected: List[Dict] = []

    for feed in feeds:
        entries = fetch_feed_entries(feed)
        for e in entries:
            title = e.get("title") or ""
            if not title:
                continue
            # Simple dedupe using normalized title
            tnorm = " ".join(title.lower().split())
            if tnorm in seen_titles:
                continue
            seen_titles.add(tnorm)
            collected.append(e)
            if len(collected) >= max_items:
                break
        if len(collected) >= max_items:
            break

    return collected


def escape_html(text: str) -> str:
    """Escape text for Telegram HTML formatting (basic)."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_message(headlines: List[Dict]) -> str:
    now = datetime.now(timezone.utc).astimezone()  # local tz
    dt_str = now.strftime("%b %d, %Y • %I:%M %p %Z")
    lines = [f"🌍 <b>Top World News — {escape_html(dt_str)}</b>\n"]
    for idx, h in enumerate(headlines, start=1):
        title = escape_html(h.get("title", ""))
        link = h.get("link", "")
        # Telegram auto-link makes links clickable; include short link in parentheses as fallback
        if link:
            lines.append(f"{idx}. {title}\n{link}")
        else:
            lines.append(f"{idx}. {title}")
        # add a small separator
        if idx != len(headlines):
            lines.append("")  # blank line between items
    lines.append(SIGNATURE)
    return "\n".join(lines)


def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    url = TELEGRAM_SEND_URL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            logger.error("Telegram API error for chat %s: %s - %s", chat_id, resp.status_code, resp.text)
            return False
        data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram response not ok for chat %s: %s", chat_id, data)
            return False
        logger.info("Message sent to %s (result_id=%s)", chat_id, data.get("result", {}).get("message_id"))
        return True
    except Exception as ex:
        logger.exception("Failed sending message to %s: %s", chat_id, ex)
        return False


# --------------- MAIN FLOW ---------------

def run_once(test_mode: bool = False):
    token, chat_ids = read_env_secrets()
    logger.info("Collecting headlines from %d feeds...", len(FEEDS))
    headlines = collect_top_headlines(FEEDS, MAX_HEADLINES)

    if not headlines:
        logger.warning("No headlines found. Exiting.")
        return

    message = build_message(headlines)
    logger.debug("Built message: %s", message[:300])

    if test_mode:
        # In test mode, print and do not send
        print("=== TEST MODE: message ===")
        print(message)
        return

    success_count = 0
    for cid in chat_ids:
        ok = send_telegram_message(token, cid, message)
        if ok:
            success_count += 1
        time.sleep(1)  # small pause between sends

    logger.info("Done. Sent to %d/%d chats.", success_count, len(chat_ids))


def parse_args():
    p = argparse.ArgumentParser(description="Fetch news and post to Telegram")
    p.add_argument("--test", action="store_true", help="Run in test mode (prints message, does not send)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run_once(test_mode=args.test)
    except SystemExit:
        raise
    except Exception as ex:
        logger.exception("Unhandled error: %s", ex)
        sys.exit(1)
