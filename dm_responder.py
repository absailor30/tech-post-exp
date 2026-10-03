"""Comment-to-DM responder (ToS-safe: official private-replies API).

Polls comments on our own recent posts; when a comment contains the trigger
keyword, sends ONE private reply DM with the resource link. State file keeps
us from ever replying to the same comment twice. Never DMs anyone who didn't
comment first — that is the API's own boundary (private replies only work on
comments on your own media, within 7 days).

Usage: python dm_responder.py            (intended for a scheduled task)
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from agent import BASE, IG_API, ig_token, log

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE = BASE / "dm_state.json"
KEYWORD = "EDGE"
# "REPO" -> the series list (every repo posted so far, as a PDF that updates daily).
SERIES_KEYWORD = "REPO"
SERIES_PDF_URL = os.environ.get(
    "SERIES_PDF_URL",
    "https://cdn.jsdelivr.net/gh/absailor30/tech-post-exp@main/docs/100-ai-repos.pdf")
SERIES_DM_TEXT = (
    "Hey! Thanks for commenting 🙌 Here's the list of every repo in the series so far "
    "(it updates every day): {link}\n\n"
    "Save it, send it to a friend, and follow so you don't miss tomorrow's repo."
)
DM_TEXT = (
    "Hey! Thanks for the comment 🙌 Here's the full guide: {link}\n\n"
    "It's free — save it, use it, share it. More every week if you're following."
)
LINK = os.environ.get("DM_LINK", "")


def call(url, params, method="GET"):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url, data = f"{url}?{data.decode()}", None
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"API error {e.code}: {e.read().decode()}")
        return None


def wants(text, word):
    """Whole-word, case-insensitive: 'repo' matches, 'report' does not."""
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", text or "", re.I)


def main():
    if not LINK and not SERIES_PDF_URL:
        sys.exit("no DM links configured — not running (nothing to send)")
    state = json.loads(STATE.read_text()) if STATE.exists() else {"replied": []}
    me = call(f"{IG_API}/me", {"fields": "username", "access_token": ig_token()}) or {}
    own = (me.get("username") or "").lower()
    media = call(f"{IG_API}/me/media", {"fields": "id,caption",
                                        "limit": "15", "access_token": ig_token()})
    if not media:
        return
    sent = 0
    for m in media.get("data", []):
        comments = call(f"{IG_API}/{m['id']}/comments",
                        {"fields": "id,text,username", "access_token": ig_token()})
        if not comments:
            continue
        for c in comments.get("data", []):
            if c["id"] in state["replied"]:
                continue
            if own and (c.get("username") or "").lower() == own:
                continue                      # never answer our own seed comment
            text = c.get("text", "")
            if wants(text, SERIES_KEYWORD):
                msg = SERIES_DM_TEXT.format(link=SERIES_PDF_URL)
            elif LINK and KEYWORD.lower() in text.lower():
                msg = DM_TEXT.format(link=LINK)
            else:
                continue
            r = call(f"{IG_API}/me/messages",
                     {"recipient": json.dumps({"comment_id": c["id"]}),
                      "message": json.dumps({"text": msg})},
                     "POST")
            state["replied"].append(c["id"])
            if r:
                sent += 1
                log("dm_sent", comment_id=c["id"], user=c.get("username", "?"))
    STATE.write_text(json.dumps(state))
    print(f"done, {sent} DMs sent")


if __name__ == "__main__":
    main()
