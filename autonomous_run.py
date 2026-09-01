"""Autonomous daily run: research -> plan -> render -> host -> publish -> log.

Nothing is written until research.py has found the day's biggest AI story
across 10+ independent sources. The model may only write about what the
research returned — it is never allowed to pick a topic from memory, which
is how this account spent two months recycling the same terminal tools.

Standing strategy (mandate, audience, banned topics) lives in strategy.json
and is editable by the owner over Telegram, so a steer actually changes what
gets posted instead of being answered and forgotten.

Money/ads still require human approval — this script never spends.

Usage:
  python autonomous_run.py           # full run (publishes!)
  python autonomous_run.py --dry     # research + plan + render only
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
from make_image import render_content, render_cta, render_hook, set_theme
from research import forget, keywords, recent_story_keys, record, research

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
# Commit-pinned form: jsDelivr treats @<sha> as immutable, so every publish
# gets a URL it has never served before and cannot answer from cache.
CDN_SHA_BASE = "https://cdn.jsdelivr.net/gh/absailor30/tech-post-exp@"

# 6 slides total: hook + CONTENT_SLIDES + cta. At ~7.5s per content slide
# this lands the reel near 40s; more slides pushed it past 50s, which is
# long for Reels retention.
CONTENT_SLIDES = 4

# If the model omits or invents a theme, decide from the story itself rather
# than defaulting blindly — a lawsuit on cream paper reads wrong.
DARK_CUES = ("sue", "sued", "lawsuit", "court", "legal", "ban", "banned",
             "breach", "leak", "hack", "scam", "fraud", "fake", "deepfake",
             "layoff", "job cuts", "fired", "warn", "warning", "risk",
             "danger", "harm", "privacy", "surveillance", "steal", "stolen",
             "theft", "investigation", "probe", "fine", "penalty", "shut down")


def pick_theme(plan, story):
    choice = str(plan.get("theme", "")).strip().lower()
    if choice in ("light", "dark"):
        return choice
    blob = f"{plan.get('topic', '')} {story.get('headline', '')}".lower()
    return "dark" if any(c in blob for c in DARK_CUES) else "light"

STRATEGY_F = BASE / "strategy.json"


def strategy():
    """Owner-set standing orders. Read fresh every run so a Telegram steer
    takes effect on the very next post."""
    if STRATEGY_F.exists():
        return json.loads(STRATEGY_F.read_text(encoding="utf-8"))
    return {"mandate": "AI only.", "audience": "Curious non-developers.",
            "format": "reel", "banned_topics": [], "directives": []}


PLAN_PROMPT = """You write for the Instagram account @thealgorithmzedge.

MANDATE (non-negotiable, set by the owner):
{mandate}

AUDIENCE:
{audience}

BANNED — if the post drifts toward any of these, you have failed:
{banned}

OWNER DIRECTIVES:
{directives}

TODAY'S STORY. You did not choose this. It was found by scanning {source_count}
independent sources and picking the story the most outlets are covering right
now. Write about THIS and nothing else:

  HEADLINE: {headline}
  LINK: {url}
  COVERED BY {coverage} OUTLETS: {covering}
  HOW EACH OUTLET FRAMED IT:
{coverage_lines}
  EXTRA CONTEXT: {summary}

Already covered — do not repeat any of these stories:
{recent}

WHAT PERFORMED (saves and shares are the only numbers that matter; reach
without saves means people watched and felt nothing):
{performance}

LAST WEEK'S LESSON:
{lesson}

HOOK PATTERNS (pick the ONE that fits this story; the hook decides everything):
{hooks}

WRITING RULES:
- The reader is not a programmer. Never assume they know what a model, a
  token, an API, or a repo is. If you must use such a word, define it in the
  same sentence in plain speech.
- Lead with what happened, then what it means for the reader's own life —
  their job, their money, their phone, their kids, their privacy.
- Be specific: names, numbers, dates. No "AI is changing everything".
- Give an honest verdict, including what is bad or overhyped about it.
- Short sentences. No jargon, no hype words, no emoji in the slide text.

Plan a vertical Reel of EXACTLY 6 slides: 1 hook + 4 content + 1 CTA.
Reply with ONLY this JSON:
{{"topic": "the story in under 12 words",
  "hook": {{"kicker": "2-4 word category label", "headline": "hook following the chosen pattern, max 10 words — open a curiosity gap, don't close it"}},
  "slides": [{{"headline": "one point, max 7 words", "body": "max 20 words, concrete and specific"}}, ...],
  "cta": {{"headline": "max 6 words", "body": "why follow, max 15 words"}},
  "theme": "light or dark — dark for serious stories (lawsuits, privacy, layoffs, scams, security, warnings, anything with a victim); light for launches, new tools, reviews, explainers and anything useful or upbeat",
  "caption": "hook first line, then what happened, then why it matters to a normal person, then a question that invites a reply, then 8-12 hashtags mixing AI news and general tech"}}
"slides" must contain EXACTLY 4 content slides (hook and cta are separate,
making 6 in total). Not 3, not 5 — exactly 4. Pick the four points that
matter most and cut the rest."""


def ig_call(url, params, method="POST"):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url, data = f"{url}?{data.decode()}", None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code}: {e.read().decode()}")


def recent_topics(n=None):
    """EVERY topic ever posted, not a 14-item window.

    The old 14-post window was the direct cause of the fortnight repeat
    cycle: on day 15 a tool the account had already covered looked new
    again. Full history means a story can only ever be posted once.
    """
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return "none yet"
    topics = [json.loads(l).get("topic", "") for l in logf.read_text(encoding="utf-8").splitlines()
              if '"autonomous_post"' in l]
    if n:
        topics = topics[-n:]
    return "; ".join(t for t in topics if t) or "none yet"


def posted_story_keys():
    """Keyword sets for every topic ever posted.

    research.jsonl only starts today, so on its own it would happily let the
    account re-post a story it already covered before the rewrite. The real
    history lives in log.jsonl and has to be checked too.
    """
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return []
    lines = logf.read_text(encoding="utf-8").splitlines()
    gone = set()
    for line in lines:
        if '"post_deleted"' in line:
            try:
                gone.add(json.loads(line).get("media_id"))
            except json.JSONDecodeError:
                pass
    out = []
    for line in lines:
        if '"autonomous_post"' not in line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("media_id") in gone:
            continue
        for field in ("topic", "story_headline"):
            if d.get(field):
                out.append(keywords(d[field]))
    return out


def already_covered(headline):
    """True if this story is a rerun of one we already posted."""
    kw = keywords(headline)
    if len(kw) < 2:
        return False
    for prev in recent_story_keys() + posted_story_keys():
        shared = kw & prev
        if len(shared) >= 3 or (shared and len(shared) / max(1, min(len(kw), len(prev))) > 0.6):
            return True
    return False


def last_lesson():
    """Feed the newest weekly report back into planning. It used to be
    written, filed, and never read by anything."""
    reps = sorted((BASE / "reports").glob("week-*.md")) if (BASE / "reports").exists() else []
    if not reps:
        return "none yet"
    return reps[-1].read_text(encoding="utf-8").strip()[-1200:]


def plan():
    import random
    from metrics import collect

    story = research()
    print(f"[research] {story['source_count']} sources responded "
          f"-> {story['coverage_count']} outlets on: {story['headline']}")
    if story["degraded"]:
        print(f"[research] WARNING degraded: {', '.join(story['sources_failed'])}")
    if already_covered(story["headline"]):
        for alt in story["runners_up"]:
            if not already_covered(alt["headline"]):
                print(f"[research] top story already covered, using: {alt['headline']}")
                story["headline"] = alt["headline"]
                story["all_headlines"] = [alt["headline"]]
                story["sources_covering"] = alt["sources"]
                story["coverage_count"] = len(alt["sources"])
                break
        else:
            sys.exit("every candidate story already covered — skipping today "
                     "rather than posting a repeat")

    st = strategy()
    hooks = json.loads((BASE / "hooks.json").read_text(encoding="utf-8"))
    picked = random.sample(hooks, 4)
    hooks_txt = "\n".join(f"- {h['name']}: {h['formula']} (e.g. \"{h['example']}\")"
                           for h in picked)
    # Reasoning models (nemotron ultra) spend most of the budget thinking before
    # emitting the JSON — give them room or the plan comes back truncated.
    prompt = PLAN_PROMPT.format(
        mandate=st.get("mandate", ""), audience=st.get("audience", ""),
        banned=", ".join(st.get("banned_topics", [])) or "none",
        directives="\n".join(f"- {d}" for d in st.get("directives", [])) or "none",
        source_count=story["source_count"], headline=story["headline"],
        url=story.get("url", ""), coverage=story["coverage_count"],
        covering=", ".join(story["sources_covering"]),
        coverage_lines="\n".join(f"    {h}" for h in story["all_headlines"]),
        summary=story.get("summary", "") or "none",
        recent=recent_topics(), performance=collect(), lesson=last_lesson(),
        hooks=hooks_txt)

    # One retry if the model returns too few content slides — cheaper than
    # losing the day, and it usually complies on the second ask.
    p = None
    for attempt in range(2):
        raw = call_llm(prompt, max_tokens=6000)
        p = extract_plan(raw)
        if not p:
            if attempt:
                sys.exit(f"no usable JSON in plan:\n{raw[-1500:]}")
            continue
        if len(p["slides"]) >= CONTENT_SLIDES:
            break
        print(f"[plan] got {len(p['slides'])} content slides, want "
              f"{CONTENT_SLIDES} — retrying")
    if not p:
        sys.exit("no usable plan after retry")

    if len(p["slides"]) > CONTENT_SLIDES:
        print(f"[plan] trimming {len(p['slides'])} content slides to {CONTENT_SLIDES}")
        p["slides"] = p["slides"][:CONTENT_SLIDES]
    elif len(p["slides"]) < CONTENT_SLIDES:
        print(f"[plan] WARNING only {len(p['slides'])} content slides; posting anyway")

    banned = [b.lower() for b in st.get("banned_topics", [])]
    blob = f"{p['topic']} {p['hook'].get('headline','')}".lower()
    hit = [b for b in banned if b in blob]
    if hit:
        sys.exit(f"plan violates mandate (banned: {', '.join(hit)}): {p['topic']}")

    p["theme"] = pick_theme(p, story)
    p["_story"] = story
    return p


def extract_plan(raw):
    """Pull the plan object out of a reply that may contain reasoning prose.

    Scans every '{' and takes the first candidate that parses AND has the
    fields we need — a greedy regex would span braces in the reasoning text.
    """
    for start in (i for i, ch in enumerate(raw) if ch == "{"):
        depth = 0
        for end in range(start, len(raw)):
            if raw[end] == "{":
                depth += 1
            elif raw[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        # strict=False: the model writes multi-line captions
                        # with real newlines inside the JSON string, which is
                        # invalid JSON but perfectly readable intent. Rejecting
                        # it threw away an otherwise complete plan.
                        p = json.loads(raw[start:end + 1], strict=False)
                    except json.JSONDecodeError:
                        break
                    if all(p.get(k) for k in ("topic", "slides", "caption", "hook", "cta")):
                        return p
                    break
    return None


def strip_reasoning(text):
    """Reasoning models narrate before answering, and week-35.md shipped as
    raw scratchpad ("Let me analyze... Wait, the data has..."). Drop any
    leading thinking and keep the report itself."""
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#") or re.match(r"^\*\*[A-Z]", ln.strip()):
            return "\n".join(lines[i:]).strip()
    tell = re.compile(r"^\s*(let me|okay|ok,|first,? i|i need to|i should|wait|"
                      r"looking at|the user (wants|asked)|analyzing)", re.I)
    kept = [ln for ln in lines if not tell.match(ln)]
    return "\n".join(kept).strip() or text


def git_out(*args):
    return subprocess.run(["git", "-C", str(REPO_DIR), *args],
                          check=True, capture_output=True).stdout.decode().strip()


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


def cmd_forget(media_id):
    """Record that a published post was deleted from the account, so its
    story stops counting as covered."""
    headline = ""
    logf = BASE / "log.jsonl"
    if logf.exists():
        for line in logf.read_text(encoding="utf-8").splitlines():
            if '"autonomous_post"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("media_id") == media_id:
                headline = d.get("story_headline") or d.get("topic") or ""
    log("post_deleted", media_id=media_id, story_headline=headline)
    dropped = forget(media_id, headline)
    print(f"forgot {media_id} ({dropped} cache entr{'y' if dropped == 1 else 'ies'} "
          f"dropped); its story can be picked again")


def main(dry=False, force=False):
    if not dry and not force and already_posted_today():
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

    # Never reuse a directory. Two runs on the same story and day produced the
    # same slug, so the second silently overwrote the first's slides — and,
    # worse, republished the same CDN path (see below).
    outdir = REPO_DIR / "images" / f"{stamp}-{slug}"
    n = 2
    while outdir.exists():
        outdir = REPO_DIR / "images" / f"{stamp}-{slug}-{n}"
        n += 1
    outdir.mkdir(parents=True, exist_ok=True)
    theme = set_theme(p.get("theme", "light"))
    print(f"theme: {theme}")
    total = len(p["slides"]) + 2
    files = [outdir / f"slide{i}.png" for i in range(1, total + 1)]
    render_hook(p["hook"]["headline"], p["hook"].get("kicker", ""), str(files[0]))
    for i, s in enumerate(p["slides"], 1):
        render_content(s["headline"], s["body"], i + 1, total, str(files[i]))
    render_cta(p["cta"]["headline"], p["cta"]["body"], str(files[-1]))
    rel_paths = [f.relative_to(REPO_DIR).as_posix() for f in files]

    # Slide text is kept beside the PNGs so the Reel can animate it letter by
    # letter, and so a reel can be rebuilt later without re-asking the model.
    specs = [{"kind": "hook", "headline": p["hook"]["headline"],
              "kicker": p["hook"].get("kicker", "")}]
    specs += [{"kind": "content", "headline": s["headline"], "body": s["body"],
               "idx": i + 1, "total": total} for i, s in enumerate(p["slides"], 1)]
    specs.append({"kind": "cta", "headline": p["cta"]["headline"],
                  "body": p["cta"]["body"]})
    (outdir / "slides.json").write_text(
        json.dumps({"theme": theme, "slides": specs}, indent=2), encoding="utf-8")

    print(f"topic: {p['topic']}\nslides: {len(files)}\ncaption:\n{p['caption']}\n")
    if dry:
        from reel_maker import build_animated
        build_animated(specs, outdir / "reel.mp4", theme=theme)
        print(f"[dry run] rendered to {outdir}, nothing pushed or published")
        return

    # Reels only. Carousels reached 1-3 accounts each for the whole of August
    # and earned zero saves and zero shares — Instagram had stopped
    # distributing them entirely, so there is nothing to salvage there.
    from reel_maker import build_animated
    build_animated(specs, outdir / "reel.mp4", theme=theme)
    rel_paths.append((outdir / "reel.mp4").relative_to(REPO_DIR).as_posix())

    git("add", "images")
    git("commit", "-m", f"post {stamp}: {p['topic'][:60]}")
    git("push", "-q", "origin", "HEAD:main")

    # Pin the video URL to the commit we just pushed. jsDelivr caches @main
    # for hours, so re-publishing a path it has already served hands Instagram
    # the OLD video — which is exactly how a re-paced reel went out still
    # carrying the previous 21s cut. A commit URL is immutable and unique, so
    # it can never be answered from a stale cache entry.
    sha = git_out("rev-parse", "HEAD")
    video_url = f"{CDN_SHA_BASE}{sha}/{rel_paths[-1]}"
    print(f"publishing {video_url}")
    result = publish_reel(video_url, p["caption"])
    kind = "reel"
    story = p.get("_story", {})
    log("autonomous_post", media_id=result["id"], topic=p["topic"], format=kind,
        slides=len(p["slides"]) + 2, caption=p["caption"][:200], theme=theme,
        story_headline=story.get("headline", ""), story_url=story.get("url", ""),
        sources_covering=story.get("sources_covering", []),
        source_count=story.get("source_count", 0))
    story["media_id"] = result["id"]
    record(story)          # only now is the story genuinely "covered"
    print(f"published {kind}, media id {result['id']}")

    if datetime.date.today().weekday() == 6:   # Sunday: weekly digest
        hist = (BASE / "metrics.jsonl")
        recent = "\n".join(hist.read_text(encoding="utf-8").splitlines()[-40:]) if hist.exists() else ""
        digest = call_llm(
            "Write a plain-language weekly report for the human owner of this "
            "Instagram experiment. Data (JSON lines, newest snapshots last):\n"
            f"{recent}\n\nCover: what performed best and why (saves/shares first), "
            "what flopped, follower trajectory if inferable, and 2-3 concrete "
            "changes you will make next week. Under 250 words.\n\n"
            "Output the finished report ONLY. Do not show your working, do not "
            "narrate your analysis, do not write 'Let me' or 'Wait'. Start "
            "directly with the report's first heading.", max_tokens=800)
        digest = strip_reasoning(digest)
        rep = BASE / "reports"
        rep.mkdir(exist_ok=True)
        f = rep / f"week-{datetime.date.today().isocalendar()[1]}.md"
        f.write_text(digest, encoding="utf-8")
        print(f"weekly digest -> {f}")


if __name__ == "__main__":
    try:
        if "--forget" in sys.argv:
            cmd_forget(sys.argv[sys.argv.index("--forget") + 1])
        else:
            main(dry="--dry" in sys.argv, force="--force" in sys.argv)
    except Exception:
        import traceback
        with (BASE / "runlog.txt").open("a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
            f.write(traceback.format_exc())
        raise
