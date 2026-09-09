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
# Reach is an OUTPUT, not a lever. For Reels the lever is watch time: how
# long people stay and whether they replay. The account has been optimising
# blind — we could see that reach was ~40 but not why, and "85% skip rate"
# was something the owner had to read off the app by hand.
METRICS = "reach,likes,comments,saved,shares,views,total_interactions"
REEL_METRICS = ("reach,likes,comments,saved,shares,views,total_interactions,"
                "ig_reels_avg_watch_time,ig_reels_video_view_total_time")
# Progressively simpler fallbacks: the API rejects the whole call if any one
# metric is unsupported for that media type or API version.
FALLBACKS = (REEL_METRICS, METRICS, "reach,likes,comments,saved,shares",
             "reach,likes,comments")


def get(url, params):
    q = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(q) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def insights(media_id):
    for metrics in FALLBACKS:
        r = get(f"{IG_API}/{media_id}/insights",
                {"metric": metrics, "access_token": ig_token()})
        if "error" not in r:
            break
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


def account():
    """Account-level snapshot. Without follower_count there is no way to tell
    a distribution problem from simply having few followers — 40 reach is a
    disaster for 5,000 followers and unremarkable for 60."""
    out = {}
    prof = get(f"{IG_API}/me",
               {"fields": "followers_count,media_count,username",
                "access_token": ig_token()})
    if "error" not in prof:
        out.update({k: prof.get(k) for k in
                    ("followers_count", "media_count", "username")})
    ins = get(f"{IG_API}/me/insights",
              {"metric": "reach,profile_views", "period": "day",
               "access_token": ig_token()})
    for m in ins.get("data", []):
        vals = m.get("values") or []
        if vals:
            out[f"account_{m['name']}"] = vals[-1].get("value")
    return out


def collect(limit=25):
    """25, not 8. With an 8-post window every row read "reach 2, saves 0" and
    the planner had no contrast to learn anything from — the feedback loop
    was present but carried no signal."""
    media = get(f"{IG_API}/me/media",
                {"fields": "id,media_type,timestamp", "limit": str(limit),
                 "access_token": ig_token()})
    if "error" in media:
        return "no metrics available"
    import datetime
    snap = account()
    if snap:
        snap.update(kind="account_snapshot",
                    snapshot=datetime.datetime.now().isoformat())
        with HIST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap) + "\n")
        print(f"account: {snap.get('followers_count')} followers, "
              f"{snap.get('media_count')} posts")
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
    # Best first, so the planner reads what worked before what didn't.
    rows.sort(key=lambda r: (r.get("saved", 0) * 3 + r.get("shares", 0) * 5
                             + r.get("comments", 0) * 2 + r.get("likes", 0)),
              reverse=True)
    lines = []
    for r in rows:
        watch = r.get("ig_reels_avg_watch_time")
        tail = f", avg watch {watch / 1000:.1f}s" if watch else ""
        lines.append(f"- {r['type']} \"{r['topic'] or '?'}\": reach {r.get('reach', 0)}, "
                     f"views {r.get('views', 0)}, likes {r.get('likes', 0)}, "
                     f"comments {r.get('comments', 0)}, saves {r.get('saved', 0)}, "
                     f"shares {r.get('shares', 0)}{tail}")
    return "\n".join(lines) or "no posts yet"


if __name__ == "__main__":
    print(collect())
