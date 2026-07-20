"""Autonomous daily run: plan -> render -> host -> publish -> log.

Designed for a scheduled task (no human in the loop for content).
Money/ads still require human approval — this script never spends.

Usage:
  python autonomous_run.py           # full run (publishes!)
  python autonomous_run.py --dry     # plan + render only, no push/publish
"""

import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent import BASE, IG_API, call_llm, ig_token, log
from make_image import render_content, render_cta, render_hook

import os
# Locally we clone into ./repo; on GitHub Actions REPO_DIR=$GITHUB_WORKSPACE
# (the checkout itself) — no clone/pull needed there.
REPO_DIR = Path(os.environ.get("REPO_DIR", BASE / "repo"))
IN_REPO = REPO_DIR.resolve() == BASE.resolve()
GIT_NAME = os.environ.get("GIT_NAME", "absailor30")
GIT_EMAIL = os.environ.get("GIT_EMAIL", "abhi212b@gmail.com")
REPO_URL = "https://github.com/absailor30/tech-post-exp.git"
RAW_BASE = "https://raw.githubusercontent.com/absailor30/tech-post-exp/main"
# Meta rejects raw.githubusercontent for video (octet-stream + nosniff);
# jsDelivr fronts the same repo with proper video/mp4.
CDN_BASE = "https://cdn.jsdelivr.net/gh/absailor30/tech-post-exp@main"

PLAN_PROMPT = """You run the Instagram account @thealgorithmzedge (tech/dev niche, small account).
Algorithm facts: DM-shares rank highest; carousels drive saves; original, specific,
practical content wins; hooks decide everything.

Pillars (rotate, don't repeat recent topics): CLI tools, AI dev tools, Python tips,
dev productivity.

WRITING RULES: plain language a curious 15-year-old gets. No unexplained jargon —
if a technical word is unavoidable, explain it in the same sentence in everyday
words ("fuzzy finder — type a few letters, it finds the file"). Short sentences.
Talk about what the reader gains, not what the tech is.

Recent topics to avoid repeating: {recent}

PERFORMANCE of recent posts (saves and shares matter most — study what worked
and lean into those topics/styles; drop what flopped):
{performance}

HOOK PATTERNS for today (pick the ONE that fits the topic best; follow its
formula — hooks decide 80% of a post's fate):
{hooks}

Plan today's carousel post (6-8 slides total). Reply with ONLY this JSON:
{{"topic": "...",
  "hook": {{"kicker": "2-4 word category label", "headline": "hook following the chosen pattern, max 10 words — open a curiosity gap, don't close it"}},
  "slides": [{{"headline": "one point, max 7 words", "body": "max 20 words, concrete and specific"}}, ...],
  "cta": {{"headline": "max 6 words", "body": "why follow, max 15 words"}},
  "caption": "hook first line, then value summary, then CTA to save/share, then 8-12 niche hashtags"}}
"slides" is the 4-6 middle content slides only (hook and cta are separate).
If a free guide link is on offer, end the caption with: Comment "EDGE" and I'll DM
you the full guide free."""


def ig_call(url, params, method="POST"):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url, data = f"{url}?{data.decode()}", None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code}: {e.read().decode()}")


def recent_topics(n=14):
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return "none yet"
    topics = [json.loads(l).get("topic", "") for l in logf.read_text(encoding="utf-8").splitlines()
              if '"autonomous_post"' in l]
    return "; ".join(t for t in topics[-n:] if t) or "none yet"


def plan():
    import random
    from metrics import collect
    hooks = json.loads((BASE / "hooks.json").read_text(encoding="utf-8"))
    picked = random.sample(hooks, 4)
    hooks_txt = "\n".join(f"- {h['name']}: {h['formula']} (e.g. \"{h['example']}\")"
                          for h in picked)
    raw = call_llm(PLAN_PROMPT.format(recent=recent_topics(), hooks=hooks_txt,
                                      performance=collect()), max_tokens=1200)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        sys.exit(f"no JSON in plan:\n{raw}")
    p = json.loads(m.group())
    assert p["slides"] and p["caption"] and p["hook"] and p["cta"], "plan missing fields"
    return p


def git(*args):
    subprocess.run(["git", "-C", str(REPO_DIR), "-c", f"user.name={GIT_NAME}",
                    "-c", f"user.email={GIT_EMAIL}", *args],
                   check=True, capture_output=True)


def wait_finished(container_id, tries=25, delay=15):
    for _ in range(tries):
        s = ig_call(f"{IG_API}/{container_id}",
                    {"fields": "status_code", "access_token": ig_token()}, "GET")
        if s.get("status_code") == "FINISHED":
            return
        if s.get("status_code") == "ERROR":
            sys.exit(f"container failed: {s}")
        time.sleep(delay)
    sys.exit("container never finished")


def publish_reel(video_url, caption):
    c = ig_call(f"{IG_API}/me/media",
                {"media_type": "REELS", "video_url": video_url,
                 "caption": caption, "access_token": ig_token()})
    wait_finished(c["id"])
    return ig_call(f"{IG_API}/me/media_publish",
                   {"creation_id": c["id"], "access_token": ig_token()})


def publish_carousel(urls, caption):
    children = []
    for u in urls:
        c = ig_call(f"{IG_API}/me/media",
                    {"image_url": u, "is_carousel_item": "true",
                     "access_token": ig_token()})
        children.append(c["id"])
    carousel = ig_call(f"{IG_API}/me/media",
                       {"media_type": "CAROUSEL", "children": ",".join(children),
                        "caption": caption, "access_token": ig_token()})
    wait_finished(carousel["id"])
    return ig_call(f"{IG_API}/me/media_publish",
                   {"creation_id": carousel["id"], "access_token": ig_token()})


def already_posted_today():
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return False
    today = datetime.date.today().isoformat()
    return any(json.loads(l).get("ts", "").startswith(today)
               for l in logf.read_text(encoding="utf-8").splitlines()
               if '"autonomous_post"' in l)


def main(dry=False):
    if not dry and already_posted_today():
        print("already posted today — nothing to do")
        return
    p = plan()
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", p["topic"].lower())[:40].strip("-")

    if not IN_REPO:
        if not REPO_DIR.exists():
            subprocess.run(["git", "clone", "-q", REPO_URL, str(REPO_DIR)], check=True)
        else:
            git("pull", "-q", "--rebase")

    outdir = REPO_DIR / "images" / f"{stamp}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)
    total = len(p["slides"]) + 2
    files = [outdir / f"slide{i}.png" for i in range(1, total + 1)]
    render_hook(p["hook"]["headline"], p["hook"].get("kicker", ""), str(files[0]))
    for i, s in enumerate(p["slides"], 1):
        render_content(s["headline"], s["body"], i + 1, total, str(files[i]))
    render_cta(p["cta"]["headline"], p["cta"]["body"], str(files[-1]))
    rel_paths = [f.relative_to(REPO_DIR).as_posix() for f in files]

    print(f"topic: {p['topic']}\nslides: {len(files)}\ncaption:\n{p['caption']}\n")
    if dry:
        print(f"[dry run] rendered to {outdir}, nothing pushed or published")
        return

    as_reel = datetime.date.today().day % 2 == 0   # even days: Reel, odd: carousel
    if as_reel:
        from reel_maker import build
        build(outdir, outdir / "reel.mp4")
        rel_paths.append((outdir / "reel.mp4").relative_to(REPO_DIR).as_posix())

    git("add", "images")
    git("commit", "-m", f"post {stamp}: {p['topic'][:60]}")
    git("push", "-q", "origin", "HEAD:main")

    if as_reel:
        result = publish_reel(f"{CDN_BASE}/{rel_paths[-1]}", p["caption"])
        kind = "reel"
    else:
        urls = [f"{RAW_BASE}/{rp}" for rp in rel_paths]
        result = publish_carousel(urls, p["caption"])
        kind = "carousel"
    log("autonomous_post", media_id=result["id"], topic=p["topic"], format=kind,
        slides=len(p["slides"]) + 2, caption=p["caption"][:200])
    print(f"published {kind}, media id {result['id']}")

    if datetime.date.today().weekday() == 6:   # Sunday: weekly digest
        hist = (BASE / "metrics.jsonl")
        recent = "\n".join(hist.read_text(encoding="utf-8").splitlines()[-40:]) if hist.exists() else ""
        digest = call_llm(
            "Write a plain-language weekly report for the human owner of this "
            "Instagram experiment. Data (JSON lines, newest snapshots last):\n"
            f"{recent}\n\nCover: what performed best and why (saves/shares first), "
            "what flopped, follower trajectory if inferable, and 2-3 concrete "
            "changes you will make next week. Under 250 words.", max_tokens=800)
        rep = BASE / "reports"
        rep.mkdir(exist_ok=True)
        f = rep / f"week-{datetime.date.today().isocalendar()[1]}.md"
        f.write_text(digest, encoding="utf-8")
        print(f"weekly digest -> {f}")


if __name__ == "__main__":
    try:
        main(dry="--dry" in sys.argv)
    except Exception:
        import traceback
        with (BASE / "runlog.txt").open("a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
            f.write(traceback.format_exc())
        raise
