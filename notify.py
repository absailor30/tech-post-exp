"""Telegram notifications for the autonomous agent.

send(text) posts to the owner's chat. Used by workflows for daily post
confirmations, Sunday digests, and failure alerts. No-ops silently if the
TELEGRAM_* env vars are absent (e.g. local dry runs).

Usage:
  python notify.py "message"          # send arbitrary text
  python notify.py --post-summary     # summarize latest autonomous_post + digest if Sunday
  python notify.py --failure <workflow-name>
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text):
    if not TOKEN or not CHAT:
        print("telegram not configured, skipping")
        return
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data))
    print("telegram sent")


def post_summary():
    logf = BASE / "log.jsonl"
    posts = [json.loads(l) for l in logf.read_text(encoding="utf-8").splitlines()
             if '"autonomous_post"' in l] if logf.exists() else []
    if not posts:
        send("⚠️ Daily run finished but no post was logged.")
        return
    p = posts[-1]
    msg = (f"✅ Posted today's {p.get('format', 'post')}\n"
           f"Topic: {p.get('topic', '?')}\n"
           f"Media ID: {p.get('media_id', '?')}")
    today = datetime.date.today()
    if today.weekday() == 6:
        rep = BASE / "reports" / f"week-{today.isocalendar()[1]}.md"
        if rep.exists():
            msg += "\n\n📊 WEEKLY REPORT\n" + rep.read_text(encoding="utf-8")
    send(msg)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--post-summary":
        post_summary()
    elif a and a[0] == "--failure":
        name = a[1] if len(a) > 1 else "workflow"
        send(f"🔴 {name} FAILED on GitHub Actions — check the Actions tab: "
             f"https://github.com/absailor30/tech-post-exp/actions")
    else:
        send(a[0] if a else "test")
