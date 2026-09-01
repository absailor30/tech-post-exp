"""Telegram bot: answers owner questions AND applies owner instructions.

Polled by a cron workflow. Reads new messages via getUpdates, answers from
log.jsonl / metrics.jsonl / reports/ using the NIM model, replies in chat.
Only the owner's chat id is served. Offset state in tg_offset.json.

Crucially it now WRITES. Until today this bot could only talk: on 2026-08-06
the owner said "lets push the focus to only ai... nothing else", got a
friendly reply, and the account posted about terminal tools for another
25 days because nothing could change the planner's instructions. Directives
are now classified and persisted to strategy.json, which autonomous_run.py
re-reads on every run — so a steer takes effect on the very next post.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from agent import BASE, call_llm, log

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}"
OFFSET_F = BASE / "tg_offset.json"


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{method}", data=data)) as r:
        return json.loads(r.read())


STRATEGY_F = BASE / "strategy.json"

CLASSIFY = """The owner of an automated Instagram account sent this message:
"{text}"

Is it (a) a QUESTION about how the account is doing, or (b) an INSTRUCTION
that should permanently change what the account posts?

If INSTRUCTION, express it as a change to this strategy file:
{current}

Reply with ONLY JSON:
{{"type": "question"}}
or
{{"type": "instruction",
  "changes": {{"mandate": "...", "audience": "...", "format": "reel",
               "add_banned": ["..."], "add_directives": ["..."]}},
  "confirm": "one plain sentence telling the owner what will change"}}
Include only the keys that actually change. Never invent an instruction from
a question."""


def load_strategy():
    if STRATEGY_F.exists():
        return json.loads(STRATEGY_F.read_text(encoding="utf-8"))
    return {"mandate": "", "audience": "", "format": "reel",
            "banned_topics": [], "directives": []}


def apply_changes(changes):
    """Persist an owner instruction. Lists are added to, not replaced, so an
    earlier steer is never silently dropped by a later one."""
    st = load_strategy()
    for key in ("mandate", "audience", "format"):
        if changes.get(key):
            st[key] = changes[key]
    for src, dst in (("add_banned", "banned_topics"), ("add_directives", "directives")):
        for v in changes.get(src) or []:
            if v and v not in st.setdefault(dst, []):
                st[dst].append(v)
    st["updated"] = datetime.datetime.now().date().isoformat()
    st["updated_by"] = "telegram"
    STRATEGY_F.write_text(json.dumps(st, indent=2), encoding="utf-8")
    return st


def parse_json(raw):
    for start in (i for i, ch in enumerate(raw) if ch == "{"):
        depth = 0
        for end in range(start, len(raw)):
            if raw[end] == "{":
                depth += 1
            elif raw[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        d = json.loads(raw[start:end + 1], strict=False)
                    except json.JSONDecodeError:
                        break
                    if d.get("type"):
                        return d
                    break
    return None


def handle_instruction(text):
    """Returns a reply string if this was an instruction, else None."""
    st = load_strategy()
    verdict = parse_json(call_llm(
        CLASSIFY.format(text=text, current=json.dumps(st, indent=2)),
        max_tokens=800))
    if not verdict or verdict.get("type") != "instruction":
        return None
    changes = verdict.get("changes") or {}
    if not changes:
        return None
    apply_changes(changes)
    log("strategy_updated", instruction=text[:200], changes=changes)
    return ("Applied to strategy.json — this takes effect on the next post.\n\n"
            + (verdict.get("confirm") or "")
            + "\n\nchanged: " + ", ".join(sorted(changes)))


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
        instruction_reply = handle_instruction(text)
        if instruction_reply:
            tg("sendMessage", chat_id=CHAT, text=instruction_reply[:4000],
               disable_web_page_preview="true")
            print(f"applied instruction: {text[:60]}")
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
