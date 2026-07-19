"""Read our own post performance via the Insights API.

collect() snapshots metrics for recent posts into metrics.jsonl and returns
a compact text summary for the planner prompt. Saves + shares are weighted
in the summary because they are the algorithm's strongest ranking signals.

Usage: python metrics.py     (prints the summary, ~9 API calls)
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from agent import BASE, IG_API, ig_token

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIST = BASE / "metrics.jsonl"
METRICS = "reach,likes,comments,saved,shares"


def get(url, params):
    q = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(q) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def insights(media_id):
    r = get(f"{IG_API}/{media_id}/insights",
            {"metric": METRICS, "access_token": ig_token()})
    if "error" in r:   # some metrics unsupported on some media types
        r = get(f"{IG_API}/{media_id}/insights",
                {"metric": "reach,likes,comments", "access_token": ig_token()})
    out = {}
    for m in r.get("data", []):
        v = m.get("total_value", {}).get("value")
        if v is None:
            vals = m.get("values", [])
            v = vals[0].get("value") if vals else None
        out[m["name"]] = v or 0
    return out


def topic_for(media_id):
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return ""
    for line in logf.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("media_id") == media_id:
            return d.get("topic", d.get("caption", ""))[:70]
    return ""


def collect(limit=8):
    media = get(f"{IG_API}/me/media",
                {"fields": "id,media_type,timestamp", "limit": str(limit),
                 "access_token": ig_token()})
    if "error" in media:
        return "no metrics available"
    import datetime
    rows = []
    for m in media.get("data", []):
        ins = insights(m["id"])
        row = {"media_id": m["id"], "type": m["media_type"],
               "posted": m.get("timestamp", ""), "topic": topic_for(m["id"]),
               "snapshot": datetime.datetime.now().isoformat(), **ins}
        rows.append(row)
    with HIST.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    lines = []
    for r in rows:
        lines.append(f"- {r['type']} \"{r['topic'] or '?'}\": reach {r.get('reach', 0)}, "
                     f"likes {r.get('likes', 0)}, comments {r.get('comments', 0)}, "
                     f"saves {r.get('saved', 0)}, shares {r.get('shares', 0)}")
    return "\n".join(lines) or "no posts yet"


if __name__ == "__main__":
    print(collect())
