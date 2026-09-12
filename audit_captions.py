"""Recover full captions/hashtags directly from Instagram for every post.

log.jsonl truncated captions to 200 chars at write time, so the hashtag
history for ~54 of the 57 logged posts was lost from our own records. This
never touched Instagram's copy — the platform still has the real caption on
every live post. This script pulls it back so the hashtag strategy can
actually be audited.

Needs INSTAGRAM_ACCESS_TOKEN — run wherever that's available (GitHub
Actions via workflow_dispatch, or locally with .env loaded).

Usage:
  python audit_captions.py                  # print every post + caption
  python audit_captions.py --hashtags        # just the hashtag frequency table
  python audit_captions.py --out posts.json  # dump full data to a file
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from agent import BASE, IG_API, ig_token

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get(url, params):
    q = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(q) as r:
        return json.loads(r.read())


def fetch_all():
    """Every media object this account has, walking the paginated edge."""
    out = []
    params = {"fields": "id,caption,media_type,timestamp,permalink",
              "limit": "50", "access_token": ig_token()}
    url = f"{IG_API}/me/media"
    while url:
        r = get(url, params)
        if "error" in r:
            sys.exit(f"API error: {r['error']}")
        out.extend(r.get("data", []))
        nxt = r.get("paging", {}).get("next")
        url, params = (nxt, {}) if nxt else (None, None)
    return out


def hashtags_of(caption):
    return re.findall(r"#\w+", caption or "")


def main():
    posts = fetch_all()
    posts.sort(key=lambda p: p.get("timestamp", ""))

    if "--hashtags" in sys.argv:
        c = Counter()
        for p in posts:
            c.update(h.lower() for h in hashtags_of(p.get("caption", "")))
        print(f"{len(posts)} posts, {len(c)} distinct hashtags\n")
        for tag, n in c.most_common(40):
            print(f"  {n:3}  {tag}")
        return

    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(json.dumps(posts, indent=2), encoding="utf-8")
        print(f"wrote {len(posts)} posts to {out}")
        return

    for p in posts:
        cap = p.get("caption", "") or ""
        tags = hashtags_of(cap)
        print(f"--- {p.get('timestamp', '')[:10]}  {p.get('media_type', '?')}  {p['id']}")
        print(cap)
        print(f"[{len(tags)} hashtags: {' '.join(tags)}]" if tags else "[no hashtags]")
        print()


if __name__ == "__main__":
    main()
