#!/usr/bin/env python3
"""
newsbot_multi.py
- Multi-category RSS -> Telegram + Email + WhatsApp (Twilio) sender
- Single-run script (designed for GitHub Actions hourly or daily)
- Uses env vars for credentials and enabled channels
"""

import os
import requests
import feedparser
from datetime import datetime

# ---- CONFIG from env ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# TELEGRAM_CHAT_IDS: comma-separated map like "world:-100123,...,business:-100456"
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")  # optional
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")  # comma separated
TWILIO_SID = os.getenv("TWILIO_SID")  # optional
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM")  # whatsapp:+1415...
TWILIO_TO = os.getenv("TWILIO_TO")      # comma separated recipients

PAGE_SIZE = int(os.getenv("PAGE_SIZE", "6"))
CATEGORY = os.getenv("CATEGORY", "world").lower()  # which category this run sends

# ---- RSS FEEDS by category ----
FEEDS = {
    "world": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://feeds.reuters.com/reuters/worldNews",
        "https://www.aljazeera.com/xml/rss/all.xml"
    ],
    "business": [
        "http://feeds.reuters.com/news/wealth",
        "https://www.ft.com/?format=rss"
    ],
    "tech": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "https://www.theverge.com/rss/index.xml"
    ],
    "sports": [
        "http://feeds.bbci.co.uk/sport/rss.xml?edition=uk"
    ],
    "india": [
        "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        "https://www.hindustantimes.com/rss/topnews/rssfeed.xml"
    ]
}

def get_feeds_for_category(cat):
    return FEEDS.get(cat, FEEDS["world"])

def fetch_items(feeds, limit=10):
    items = []
    for url in feeds:
        try:
            d = feedparser.parse(url)
            for e in d.entries:
                items.append({
                    "title": e.get("title","").strip(),
                    "link": e.get("link","").strip(),
                    "source": d.feed.get("title","")
                })
        except Exception:
            continue
    # dedupe by link
    seen = set()
    uniq = []
    for it in items:
        if it["link"] and it["link"] not in seen:
            seen.add(it["link"])
            uniq.append(it)
    return uniq[:limit]

def format_text(items, cat):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    header = f"*NewsAlertBot — {cat.capitalize()} — {now}*"
    lines = [header, ""]
    for i, it in enumerate(items,1):
        lines.append(f"{i}. {it['title']}\n_{it['source']}_\n{it['link']}\n")
    lines.append("_Powered by public RSS feeds. Headlines & links only._")
    text = "\n".join(lines)
    if len(text) > 3900:
        return text[:3900] + "\n\n_Read more on the channel._"
    return text

def send_telegram(chat_id, text):
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

def send_email(subject, html):
    if not SENDGRID_API_KEY or not EMAIL_TO or not EMAIL_FROM:
        return
    url = "https://api.sendgrid.com/v3/mail/send"
    tos = [{"email": e.strip()} for e in EMAIL_TO.split(",") if e.strip()]
    payload = {
        "personalizations":[{"to": tos, "subject": subject}],
        "from":{"email": EMAIL_FROM},
        "content":[{"type":"text/html","value": html}]
    }
    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type":"application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    return r.status_code

def send_whatsapp(msg):
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and TWILIO_TO):
        return
    for num in [n.strip() for n in TWILIO_TO.split(",") if n.strip()]:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
        data = {"From": TWILIO_FROM, "To": num, "Body": msg}
        r = requests.post(url, data=data, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=15)
        # do not raise to avoid stopping other sends
    return

def main():
    cat = CATEGORY
    feeds = get_feeds_for_category(cat)
    items = fetch_items(feeds, limit=PAGE_SIZE)
    if not items:
        print("No items")
        return
    text = format_text(items, cat)
    # Telegram map
    mapping = {}
    if TELEGRAM_CHAT_IDS:
        for pair in TELEGRAM_CHAT_IDS.split(","):
            if ":" in pair:
                k,v = pair.split(":",1)
                mapping[k.strip().lower()] = v.strip()
    chat_id = mapping.get(cat) or os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        try:
            send_telegram(chat_id, text)
            print("Telegram sent to", chat_id)
        except Exception as e:
            print("Telegram error", e)
    # Email (send summary)
    if SENDGRID_API_KEY and EMAIL_TO:
        html = "<h3>NewsAlertBot — {}</h3>".format(cat.capitalize())
        for it in items:
            html += f"<p><b>{it['title']}</b><br><i>{it['source']}</i><br><a href='{it['link']}'>{it['link']}</a></p>"
        try:
            send_email(f"NewsAlertBot — {cat.capitalize()}", html)
            print("Email sent")
        except Exception as e:
            print("Email error", e)
    # WhatsApp via Twilio (optional)
    if TWILIO_SID and TWILIO_TO:
        try:
            send_whatsapp(text[:1500])  # shorten for SMS/WA
            print("WhatsApp/Twilio send attempted")
        except Exception as e:
            print("Twilio error", e)

if __name__ == "__main__":
    main()
