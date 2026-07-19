"""Telegram query bot: answers owner questions about the agent's activity.

Polled by a cron workflow. Reads new messages via getUpdates, answers from
log.jsonl / metrics.jsonl / reports/ using the NIM model, replies in chat.
Only the owner's chat id is served. Offset state in tg_offset.json.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from agent import BASE, call_llm

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}"
OFFSET_F = BASE / "tg_offset.json"


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{method}", data=data)) as r:
        return json.loads(r.read())


def context_blob():
    parts = []
    logf = BASE / "log.jsonl"
    if logf.exists():
        posts = [json.loads(l) for l in logf.read_text(encoding="utf-8").splitlines()
                 if '"autonomous_post"' in l or '"published"' in l or '"dm_sent"' in l]
        parts.append("POSTS AND DMS (oldest to newest):")
        for p in posts[-25:]:
            parts.append(json.dumps(p))
    mf = BASE / "metrics.jsonl"
    if mf.exists():
        parts.append("\nLATEST METRICS SNAPSHOTS:")
        parts += mf.read_text(encoding="utf-8").splitlines()[-16:]
    reports = sorted((BASE / "reports").glob("week-*.md")) if (BASE / "reports").exists() else []
    if reports:
        parts.append("\nLATEST WEEKLY REPORT:\n" + reports[-1].read_text(encoding="utf-8"))
    return "\n".join(parts)[-8000:]


def main():
    offset = json.loads(OFFSET_F.read_text())["offset"] if OFFSET_F.exists() else 0
    ups = tg("getUpdates", offset=offset, timeout=0).get("result", [])
    new_offset = offset
    for u in ups:
        new_offset = u["update_id"] + 1
        msg = u.get("message", {})
        text = msg.get("text", "")
        if str(msg.get("chat", {}).get("id")) != str(CHAT) or not text or text == "/start":
            continue
        answer = call_llm(
            "You are the reporting interface of an autonomous Instagram agent "
            "(account @thealgorithmzedge). The owner asked via Telegram:\n"
            f"\"{text}\"\n\nAnswer from this activity data (be concrete, use "
            "plain language, keep it under 150 words, no markdown):\n\n"
            + context_blob(), max_tokens=500)
        tg("sendMessage", chat_id=CHAT, text=answer[:4000],
           disable_web_page_preview="true")
        print(f"answered: {text[:60]}")
    if new_offset != offset:
        OFFSET_F.write_text(json.dumps({"offset": new_offset}))
    print(f"processed {len(ups)} update(s)")


if __name__ == "__main__":
    main()
