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


ALERT_STATE = BASE / "last_alert.json"
ACTIONS_URL = "https://github.com/absailor30/tech-post-exp/actions"


def already_alerted_today(key):
    """True if this exact failure was already pinged today.

    Two daily-post slots each retry up to 3 times, so one dead credential
    used to mean up to 6 identical "check the Actions tab" pings a day —
    which is what actually prompted this. One alert per distinct problem
    per day is enough to know about it without needing to know about it
    six times.
    """
    if not ALERT_STATE.exists():
        return False
    try:
        prev = json.loads(ALERT_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return prev.get("date") == str(datetime.date.today()) and prev.get("key") == key


def remember_alert(key):
    ALERT_STATE.write_text(json.dumps({"date": str(datetime.date.today()), "key": key}),
                           encoding="utf-8")


def failure(name):
    errf = BASE / "last_error.txt"
    detail = errf.read_text(encoding="utf-8").strip() if errf.exists() else ""
    # The dedup key is the failure's own identity, not the workflow name —
    # daily-post's morning and evening slots share one Instagram token, so
    # if it's dead, both are the SAME problem and should count as one.
    key = detail if detail else f"{name}:no-detail"

    if already_alerted_today(key):
        print(f"already alerted today for: {key[:80]} — suppressing duplicate")
        return

    if detail.startswith("INSTAGRAM_TOKEN_EXPIRED:"):
        reason = detail.split(":", 1)[1].strip()
        send(f"🔴 {name} FAILED — Instagram token expired.\n\n"
             f"Every slot will keep failing until this is fixed: generate a "
             f"new long-lived token in Meta's Graph API Explorer and update "
             f"the INSTAGRAM_ACCESS_TOKEN secret on GitHub.\n\n{reason[:300]}")
    elif detail:
        send(f"🔴 {name} FAILED\n\n{detail[:500]}\n\nActions: {ACTIONS_URL}")
    else:
        send(f"🔴 {name} FAILED on GitHub Actions — check the Actions tab: {ACTIONS_URL}")
    remember_alert(key)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--post-summary":
        post_summary()
    elif a and a[0] == "--failure":
        failure(a[1] if len(a) > 1 else "workflow")
    else:
        send(a[0] if a else "test")
