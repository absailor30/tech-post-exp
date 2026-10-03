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
from research import (content_tokens, forget, keywords, recent_story_keys,
                      record, research, significance, similarity)

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

SOURCE MATERIAL (article text; may be empty). This and the headlines above are
the ONLY facts you may state:
{article}

Already covered — do not repeat any of these stories:
{recent}

WHAT PERFORMED (saves and shares are the only numbers that matter; reach
without saves means people watched and felt nothing):
{performance}

LAST WEEK'S LESSON:
{lesson}

HOOK PATTERNS (pick the ONE that fits this story; the hook decides everything):
{hooks}

ACCURACY RULES (a fact-checker reads your output against the source material
above and rejects the post if any claim is unsupported):
- Every name, number, date, product feature and "who gets it" claim must appear
  in the headlines, EXTRA CONTEXT or SOURCE MATERIAL. If it is not there, do not
  write it — a shorter true post beats a detailed invented one.
- Copy numbers and units exactly. Do not restate a figure as a different
  quantity (e.g. an "output limit" is not a "context window"; a price per
  million tokens is not a monthly fee).
- Explaining what a term means is fine. Predicting what it means for the reader
  is fine ONLY if phrased as "could"/"may"/"might", never as established fact.
- Do not invent consequences, risks, quotes or reactions. Do not attribute
  claims to people or companies unless the source does.
- If the only evidence is a company's own claim, say "the company says".

WRITING RULES:
- The reader is not a programmer. Never assume they know what a model, a
  token, an API, or a repo is. If you must use such a word, define it in the
  same sentence in plain speech.
- Lead with what happened, then what it means for the reader's own life —
  their job, their money, their phone, their kids, their privacy.
- Be specific using ONLY facts from the source material. No "AI is changing everything".
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


def seed_comment(topic, caption):
    """Generate one engaging pinned-style first comment for a fresh post.
    Posting it ourselves immediately gives the post a non-zero comment count
    from the first second (removes the "empty post" hesitation) and, more
    importantly, is itself a strong hook for a reply -- an opinion or a
    direct question reads as an invitation in a way the caption alone
    doesn't, and replies/saves are what the algorithm actually weighs when
    deciding whether to push a reel past its first small batch of viewers."""
    # The model is a reasoning model: it thinks in the visible output before
    # answering. max_tokens=120 cut it off mid-thought every time, so the
    # "comment" was its truncated scratchpad (the restated constraint list).
    # Give it room, and take ONLY a line it explicitly marks as the answer.
    raw = call_llm(
        "You are the account owner commenting on your own just-published "
        f"Instagram Reel about: {topic}\n\nFull caption for context:\n{caption}\n\n"
        "Write ONE short comment (max 2 sentences, under 150 characters) that "
        "you post yourself as the first comment. It should do ONE of: "
        "(a) ask a genuine opinion question that's easy to answer in one word "
        "or (b) state a sharp, slightly opinionated take that invites people "
        "to agree/disagree, or (c) prompt people to tag someone who needs to "
        "see this. No hashtags, no emojis-as-decoration (one is fine if it "
        "fits naturally), no 'link in bio', nothing salesy. Sound like a real "
        "person, not a brand account. Keep any thinking very short. Finish "
        "with the final comment on its own last line, formatted exactly as:\n"
        "COMMENT: <the comment text>",
        max_tokens=3000,
    )
    return extract_comment(raw)


def extract_comment(raw):
    """The text after the LAST 'COMMENT:' marker, or '' if the model never
    produced one (truncated / rambling) -- better no comment than a bad one."""
    text = re.sub(r"(?is)<think>.*?</think>", "", raw or "")
    hits = re.findall(r"(?im)^\s*\**COMMENT:?\**\s*(.+)$", text)
    return hits[-1].strip().strip('"').strip("*").strip() if hits else ""


def _looks_like_a_real_comment(text):
    """Guards against the model echoing its own instructions back instead of
    writing a comment -- happened live: it returned the constraint bullets
    ("- Max 2 sentences\\n- Under 150 characters...") and that got posted
    verbatim to Instagram. A real comment is one short line, not a list, and
    doesn't talk about its own rules."""
    if not text or len(text) > 220:
        return False
    if text.lstrip().startswith(("-", "*", "<")) or "<" in text:
        return False                       # bullet list / echoed placeholder
    if "\n" in text.strip():
        return False
    bad_markers = ("max ", "under ", "sentence", "hashtag", "character limit",
                   "link in bio", "sound like", "opinion question")
    low = text.lower()
    return not any(m in low for m in bad_markers)


def post_seed_comment(media_id, topic, caption, fixed=None):
    """Best-effort: a failed seed comment must never fail the whole run --
    the post already published successfully, so this is non-fatal by design.
    `fixed` (series posts) is a ready-made comment, so no model is involved."""
    try:
        text = fixed or seed_comment(topic, caption)
        if not text or not _looks_like_a_real_comment(text):
            print(f"seed comment skipped (didn't look like a real comment): {text!r}")
            return
        r = ig_call(f"{IG_API}/{media_id}/comments",
                    {"message": text, "access_token": ig_token()})
        log("seed_comment", media_id=media_id, text=text, comment_id=r.get("id"))
        print(f"seed comment posted: {text}")
    except SystemExit as e:
        print(f"seed comment failed (non-fatal): {e}")
    except Exception as e:
        print(f"seed comment failed (non-fatal): {e}")


def verify_ig_token():
    """Fail in under a second if the Instagram token is dead, before any
    research/LLM/render work happens.

    Previously a dead token was only discovered at the final publish call —
    after a full research pass, an LLM call, and a ~40s video render had
    already run. That's ~75s of wasted work per failed slot, and with two
    slots a day each retrying up to 3 times, a token that dies once was
    quietly costing that every single firing. A GET /me call costs nothing
    and fails identically, so this catches it immediately and tags the
    reason so notify.py can turn it into an actionable Telegram message
    instead of a bare "check the Actions tab" ping.
    """
    q = urllib.parse.urlencode({"fields": "id,username", "access_token": ig_token()})
    try:
        with urllib.request.urlopen(f"{IG_API}/me?{q}") as r:
            json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body).get("error", {})
        except json.JSONDecodeError:
            err = {}
        if err.get("code") == 190 or "OAuthException" in err.get("type", ""):
            sys.exit(f"INSTAGRAM_TOKEN_EXPIRED: {err.get('message', body)}")
        sys.exit(f"Instagram API error {e.code}: {body}")


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


# Weighted-overlap score above which two headlines are the same story.
# Tuned against the real repeats this account shipped: the two GPT-6 Astra
# reruns and the two German-wiki reruns must be caught, while genuinely
# different lawsuits against different companies must not be.
SAME_STORY = 0.42     # weighted overlap, checked against the whole history
RECENT_WINDOW = 16    # stories back over which ANY shared subject is a repeat


def same_story(a, b, weight, recent):
    """Compare two keyword sets. Returns (is_same, reason)."""
    score = similarity(a, b, weight)
    if score >= SAME_STORY:
        return True, f"overlap {score:.2f} on {sorted(a & b)}"
    if recent:
        shared = content_tokens(a) & content_tokens(b)
        if shared:
            return True, f"recent subject {sorted(shared)}"
    return False, ""


def already_covered(headline, explain=False):
    """True if this story is a rerun of one we already posted.

    Two rules, because one is not enough:

    1. Weighted overlap across the entire history, for headlines that are
       obviously the same wording.
    2. A recent-subject guard. Weighting by rarity alone is self-defeating
       here: the account posted "Astra" three times, which made "astra"
       look COMMON and downweighted the one word identifying the story. So
       within the last RECENT_WINDOW stories, sharing any subject word at
       all — anything outside the boilerplate in research.COMMON — counts as
       a repeat. Restricting it to a window means a genuinely new Mistral
       story months later is still allowed through.
    """
    kw = keywords(headline)
    if len(kw) < 2:
        return False
    history = posted_story_keys() + recent_story_keys()
    weight = significance(history)
    subject = content_tokens(kw)

    for prev in history:
        hit, reason = same_story(kw, prev, weight, recent=False)
        if hit:
            if explain:
                print(f"  repeat ({reason})")
            return True

    for prev in history[-RECENT_WINDOW:]:
        hit, reason = same_story(kw, prev, weight, recent=True)
        if hit:
            if explain:
                print(f"  repeat ({reason})")
            return True
    return False


def last_lesson():
    """Feed the newest weekly report back into planning. It used to be
    written, filed, and never read by anything."""
    reps = sorted((BASE / "reports").glob("week-*.md")) if (BASE / "reports").exists() else []
    if not reps:
        return "none yet"
    return reps[-1].read_text(encoding="utf-8").strip()[-1200:]


def _draft(prompt):
    """One plan from the LLM, with a retry if it returns too few content slides
    (cheaper than losing the day, and it usually complies on the second ask)."""
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
    return p


def plan_text(p):
    """Everything a viewer will read or hear, as one block."""
    parts = [p.get("hook", {}).get("headline", ""), p.get("hook", {}).get("usp", "")]
    parts += [f"{s.get('headline', '')}. {s.get('body', '')} {s.get('say', '')}" for s in p["slides"]]
    parts += [p.get("cta", {}).get("headline", ""), p.get("caption", "")]
    return "\n".join(x for x in parts if x)


def fact_check(p, material):
    """Claims in the finished post that the source material does not support.

    Independent second pass: a model grading a draft against evidence is far
    more reliable than the same model remembering to stay grounded while
    writing. Returns [] when clean, a list of claims when not, and None when
    the checker could not give a verdict (API error, truncated/rambling reply).
    None is NOT clean: the caller retries, then skips the post.
    """
    try:
        raw = call_llm(
            "You are a strict fact-checker. SOURCE MATERIAL is the only truth.\n\n"
            f"SOURCE MATERIAL:\n{material}\n\nPOST TEXT:\n{plan_text(p)}\n\n"
            "List every factual claim in the POST TEXT that the SOURCE MATERIAL "
            "does not support or that contradicts it: wrong or invented numbers, "
            "names, dates, features, who gets access, or a figure described as a "
            "different quantity than the source describes. Do NOT flag opinions, "
            "plain-language explanations of terms, or implications phrased with "
            "could/may/might. Also do NOT flag the account's own branding or call to "
            "action (e.g. 'Repo 3 of 100', 'Follow for more'); they are not claims "
            "about the world. Quote each unsupported claim briefly.\n"
            "Keep any thinking short. Finish with ONE last line, exactly:\n"
            'UNSUPPORTED: ["claim 1", "claim 2"]   (use [] if everything is supported)',
            max_tokens=4000)
    except Exception as e:
        print(f"[fact-check] checker unavailable ({e!r:.120})")
        return None
    hits = re.findall(r"(?im)^\s*\**UNSUPPORTED:?\**\s*(\[.*\])\s*$", raw or "")
    if not hits:
        print("[fact-check] no verdict returned")
        return None
    try:
        claims = json.loads(hits[-1])
    except json.JSONDecodeError:
        return None
    return [str(c) for c in claims if str(c).strip()][:8]


def plan(series_story=None):
    import random
    from metrics import collect

    # Env var (workflow input) or a one-shot story_override.txt committed to
    # the repo; the file is consumed (git rm) when the post is committed.
    override = os.environ.get("STORY_OVERRIDE", "").strip()
    _f = REPO_DIR / "story_override.txt"
    if not override and _f.exists():
        override = _f.read_text(encoding="utf-8").strip()
    if series_story:
        override = "series"            # skips news dedup and the banned-topic check
        story = series_story
    elif override:
        # Manual topic (workflow_dispatch `story` input): "headline | summary".
        # Skips research and dedup — the operator chose this story on purpose.
        head, _, summ = override.partition("|")
        story = {"headline": head.strip(), "url": "", "summary": summ.strip(),
                 "sources_covering": ["manual"], "coverage_count": 1,
                 "all_headlines": [head.strip()], "runners_up": [],
                 "sources_ok": ["manual"], "sources_failed": [],
                 "source_count": 1, "degraded": False, "score": 0}
    else:
        story = research()
    print(f"[research] {story['source_count']} sources responded "
          f"-> {story['coverage_count']} outlets on: {story['headline']}")
    if story["degraded"]:
        print(f"[research] WARNING degraded: {', '.join(story['sources_failed'])}")
    if not override and already_covered(story["headline"]):
        for alt in story["runners_up"]:
            if not already_covered(alt["headline"]):
                print(f"[research] top story already covered, using: {alt['headline']}")
                story["headline"] = alt["headline"]
                story["all_headlines"] = [alt["headline"]]
                story["sources_covering"] = alt["sources"]
                story["coverage_count"] = len(alt["sources"])
                break
        else:
            # Not a failure: the dedup floor correctly declined to repost,
            # it's just that every candidate happened to overlap something
            # recent today. This resolves itself as soon as new stories
            # break, exactly like already_posted_in_slot()'s no-op below --
            # it used to sys.exit(1) here, which failed the Actions run and
            # sent a scary "FAILED" Telegram ping for a day the system did
            # the right thing by posting nothing.
            return None

    st = strategy()
    hooks = json.loads((BASE / "hooks.json").read_text(encoding="utf-8"))
    picked = random.sample(hooks, 4)
    hooks_txt = "\n".join(f"- {h['name']}: {h['formula']} (e.g. \"{h['example']}\")"
                           for h in picked)
    if series_story:    # the dev-tips pattern list would invite unsupported hooks
        hooks_txt = ("- repo_usp: say what the repo does, in plain words, straight "
                     "from its GitHub description — nothing the description does not say")
    # Reasoning models (nemotron ultra) spend most of the budget thinking before
    # emitting the JSON — give them room or the plan comes back truncated.
    prompt = PLAN_PROMPT.format(
        mandate=st.get("mandate", ""), audience=st.get("audience", ""),
        banned=", ".join(st.get("banned_topics", [])) or "none",
        directives=("\n".join(f"- {d}" for d in st.get("directives", [])) or "none")
        + (("\n- " + __import__("series").series_note(
            story["series"]["day"], story["series"]["total"])) if series_story else ""),
        source_count=story["source_count"], headline=story["headline"],
        url=story.get("url", ""), coverage=story["coverage_count"],
        covering=", ".join(story["sources_covering"]),
        coverage_lines="\n".join(f"    {h}" for h in story["all_headlines"]),
        summary=story.get("summary", "") or "none",
        article=story.get("article", "") or "none available — write only from the headlines and say less",
        recent=recent_topics(), performance=collect(), lesson=last_lesson(),
        hooks=hooks_txt)

    material = "\n".join([story["headline"], *story.get("all_headlines", []),
                          story.get("summary", ""), story.get("article", "")])
    if series_story:
        material += (f"\nThis is post {story['series']['day']} of the account's "
                     f"{story['series']['total']}-repo series; the account asks viewers to "
                     "follow for the rest.")
    def checked(plan_):
        """Claims list, or None if the checker stayed unavailable after retries."""
        for i in range(3):
            r = fact_check(plan_, material)
            if r is not None:
                return r
            if i < 2:
                import time
                time.sleep(8)
        return None

    p = _draft(prompt)
    for attempt in range(2):
        bad = checked(p)
        if bad is None:
            print("[fact-check] could not verify this post (checker unavailable) — "
                  "skipping rather than publishing unverified claims")
            log("fact_check_unavailable", headline=story["headline"])
            return None
        if not bad:
            break
        print(f"[fact-check] {len(bad)} unsupported claim(s): {bad}")
        if attempt and series_story:
            # swap only the flagged parts for plain source-derived fallbacks, re-check
            p = __import__("series").repair(p, bad, story)
            bad = checked(p)
            if bad == []:
                break
            if bad is None:
                bad = ["(checker unavailable after repair)"]
        if attempt:
            print("[fact-check] still unsupported after a rewrite — skipping this "
                  "post rather than publishing unverified claims")
            print("[fact-check] blocked draft was:\n" + plan_text(p))
            log("fact_check_blocked", headline=story["headline"], claims=bad)
            return None
        p = _draft(prompt + "\n\nA FACT-CHECK of your previous draft found these "
                   "claims NOT supported by the source material. Rewrite the whole "
                   "plan without them (delete them, do not paraphrase them):\n"
                   + "\n".join(f"- {c}" for c in bad))

    if series_story:
        p = __import__("series").finalize(p, story)

    banned = [b.lower() for b in st.get("banned_topics", [])]
    blob = f"{p['topic']} {p['hook'].get('headline','')}".lower()
    hit = [b for b in banned if b in blob]
    if hit and not series_story:       # series is owner-approved; "git" would match "github"
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
    r = subprocess.run(["git", "-C", str(REPO_DIR), "-c", f"user.name={GIT_NAME}",
                        "-c", f"user.email={GIT_EMAIL}", *args],
                       capture_output=True)
    if r.returncode != 0:   # surface git's own reason, not just "exit status 1"
        print(f"git {' '.join(args)} failed:\n{r.stderr.decode(errors='replace')}")
        raise subprocess.CalledProcessError(r.returncode, args)


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


# Two posts a day: a late-morning IST slot and the original evening one.
# Each slot is a UTC hour window [start, end) wide enough to cover its
# primary cron time plus its own backup/last-resort retries, so a failed
# primary still gets a same-slot second try without also unlocking the
# other slot's post. Slots are derived from wall-clock time rather than
# passed in from the workflow, so a manual/backfill run just works from
# whatever time it actually runs at, and adding a third slot later is a
# one-line change here with no workflow plumbing required.
SLOTS = (("morning", 5, 13), ("evening", 13, 23))


def current_slot():
    hour = datetime.datetime.utcnow().hour
    for name, start, end in SLOTS:
        if start <= hour < end:
            return name
    return "off-hours"   # 23:00-05:00 UTC — no cron fires here; a manual
                          # run in this window always posts (never "already
                          # posted off-hours today", since nothing else can
                          # collide with it)


def already_posted_in_slot(slot):
    """True if a post already went out THIS slot today — not just today."""
    if slot == "off-hours":
        return False
    logf = BASE / "log.jsonl"
    if not logf.exists():
        return False
    today = datetime.date.today().isoformat()
    for line in logf.read_text(encoding="utf-8").splitlines():
        if '"autonomous_post"' not in line:
            continue
        d = json.loads(line)
        ts = d.get("ts", "")
        if not ts.startswith(today):
            continue
        hour = int(ts[11:13])
        if any(name == slot and start <= hour < end for name, start, end in SLOTS):
            return True
    return False


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


def main(dry=False, force=False, series=False):
    sstate = None
    if series:
        # The 100-day AI repos series: its own once-a-day guard, independent of
        # the news slots, and its own story source (series.py + GitHub API).
        import series as _series
        sstate = _series.load_state()
        if not dry and not force and _series.posted_today(sstate):
            print("series already posted today — nothing to do")
            return
        print("mode: series")
        if not dry:
            verify_ig_token()
        sstory, sstate = _series.pick_story(state=sstate)
        if sstory is None:
            print("series: no usable repo to post right now")
            return
        p = plan(series_story=sstory)
        if dry and p is not None:
            print("=== SERIES PREVIEW ===")
            print(json.dumps({k: p.get(k) for k in ("topic", "theme", "hook", "slides", "cta", "caption")},
                             indent=1, ensure_ascii=False))
            print("=== SOURCE FACTS ===")
            print(sstory["summary"])
        if p is None:
            repo = sstory["series"]["repo"]
            n = sstate.setdefault("blocked", {}).get(repo, 0) + 1
            sstate["blocked"][repo] = n
            if n >= 2:      # don't let one repo stall the series forever
                sstate["skipped"].append({"repo": repo, "reason": "fact-check blocked twice",
                                          "date": datetime.date.today().isoformat()})
            _series.save_state(sstate)
            print(f"series: {repo} blocked by the fact-check ({n}x)")
            return
    else:
        slot = current_slot()
        if not dry and not force and already_posted_in_slot(slot):
            print(f"already posted in the {slot} slot today — nothing to do")
            return
        print(f"slot: {slot}")
        if not dry:
            verify_ig_token()   # fail in <1s, not after research+LLM+render
        p = plan()
        if p is None:
            print("nothing fresh to post this slot — every candidate story was "
                  "already covered recently")
            return
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
              "kicker": p["hook"].get("kicker", ""), "say": p["hook"].get("say", "")}]
    web_url = None
    if series:      # real-video reel: a Chrome scroll through the repo's own page
        web_url = p["_story"]["url"]    # the recording shows the name; we never print or say it
    specs += [{"kind": "content", "headline": s["headline"], "body": s["body"],
               "say": s.get("say", ""), "idx": i + 1, "total": total}
              for i, s in enumerate(p["slides"], 1)]
    specs.append({"kind": "cta", "headline": p["cta"]["headline"],
                  "body": p["cta"]["body"], "say": p["cta"].get("say", "")})
    (outdir / "slides.json").write_text(
        json.dumps({"theme": theme, "slides": specs}, indent=2), encoding="utf-8")

    print(f"topic: {p['topic']}\nslides: {len(files)}\ncaption:\n{p['caption']}\n")
    if dry:
        if web_url:
            from webreel import build_web_reel
            build_web_reel(specs, web_url, outdir / "reel.mp4")
        else:
            from reel_maker import build_animated
            build_animated(specs, outdir / "reel.mp4", theme=theme)
        print(f"[dry run] rendered to {outdir}, nothing pushed or published")
        return

    # Reels only. Carousels reached 1-3 accounts each for the whole of August
    # and earned zero saves and zero shares — Instagram had stopped
    # distributing them entirely, so there is nothing to salvage there.
    if web_url:
        from webreel import build_web_reel
        build_web_reel(specs, web_url, outdir / "reel.mp4")
    else:
        from reel_maker import build_animated
        build_animated(specs, outdir / "reel.mp4", theme=theme)
    rel_paths.append((outdir / "reel.mp4").relative_to(REPO_DIR).as_posix())

    if (REPO_DIR / "story_override.txt").exists():
        git("rm", "-q", "-f", "story_override.txt")   # one-shot: never reused
    # A branch run is a shallow checkout that can't prove its commit descends
    # from main, so the push is rejected even when it should fast-forward.
    # Parent the post commit on main's tip (tree is unchanged); a no-op when
    # the run is already on main.
    git("fetch", "-q", "--depth=1", "origin", "main")
    git("reset", "-q", "--soft", "FETCH_HEAD")
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
        slides=len(p["slides"]) + 2, caption=p["caption"], theme=theme,
        story_headline=story.get("headline", ""), story_url=story.get("url", ""),
        sources_covering=story.get("sources_covering", []),
        source_count=story.get("source_count", 0))
    story["media_id"] = result["id"]
    # only now is the story genuinely "covered" (article text is too big to keep)
    record({k: v for k, v in story.items() if k != "article"})
    if series:
        _series.mark_posted(sstate, story, result["id"])
    print(f"published {kind}, media id {result['id']}")
    if series:
        try:                     # refresh the REPO list PDF with today's repo
            import series_doc
            series_doc.build(sstate)
        except Exception as e:
            print(f"[series] PDF build failed (non-fatal): {e!r}")
        post_seed_comment(result["id"], p["topic"], p["caption"],
                          fixed="Comment REPO and I'll DM you the full list of every repo in this series.")
    else:
        post_seed_comment(result["id"], p["topic"], p["caption"])

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
    # Cleared at the start of every run, so a success never leaves a stale
    # error sitting around for the next failure's Telegram alert to quote.
    ERROR_F = BASE / "last_error.txt"
    ERROR_F.unlink(missing_ok=True)
    try:
        if "--forget" in sys.argv:
            cmd_forget(sys.argv[sys.argv.index("--forget") + 1])
        else:
            main(dry="--dry" in sys.argv, force="--force" in sys.argv,
                 series="--series" in sys.argv)
    except SystemExit as e:
        # sys.exit(str) is how verify_ig_token/ig_call/research's safety
        # floor all report a *specific* reason. That reason is the one
        # thing notify.py needs to turn "daily-post FAILED" into something
        # the owner can act on without opening the Actions log.
        if e.code and str(e.code) != "0":
            ERROR_F.write_text(str(e.code), encoding="utf-8")
        raise
    except Exception:
        import traceback
        tb = traceback.format_exc()
        with (BASE / "runlog.txt").open("a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
            f.write(tb)
        last_line = next((l for l in reversed(tb.strip().splitlines()) if l.strip()),
                         "unknown error")
        ERROR_F.write_text(last_line, encoding="utf-8")
        raise
