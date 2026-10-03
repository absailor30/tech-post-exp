"""Which hook type works best? Joins series_state.json (hook type per post) with the
latest Instagram snapshot per post in metrics.jsonl.

Usage: python hook_report.py          (needs a few posts to mean anything; posts are
only comparable once they are all at least ~3 days old)
"""
import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent


def main():
    state = json.loads((BASE / "series_state.json").read_text(encoding="utf-8"))
    latest = {}
    for line in (BASE / "metrics.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("media_id") and "reach" in r:
            latest[r["media_id"]] = r          # file is chronological: last wins
    by = defaultdict(list)
    for e in state["posted"]:
        m = latest.get(e.get("media_id"))
        if m:
            by[e.get("opening") or "?"].append(m)
    print(f"{'hook type':16} {'posts':>5} {'reach':>7} {'views':>7} {'saves':>6} {'shares':>6} {'watch s':>8}")
    for t, ms in sorted(by.items(), key=lambda kv: -sum(m.get('reach', 0) for m in kv[1]) / len(kv[1])):
        n = len(ms)
        avg = lambda k: sum(m.get(k, 0) or 0 for m in ms) / n
        print(f"{t:16} {n:5d} {avg('reach'):7.0f} {avg('views'):7.0f} {avg('saved'):6.1f} "
              f"{avg('shares'):6.1f} {avg('ig_reels_avg_watch_time') / 1000:8.1f}")
    if not by:
        print("(no series posts with metrics yet)")


if __name__ == "__main__":
    main()
