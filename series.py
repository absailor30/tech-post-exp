"""'100 AI repos worth knowing' series: one repo per post, in repos.json order.

Facts come from GitHub's API on the runner at post time (never from memory):
description, stars, language, licence, dates, README. The README excerpt is
passed to the writer as source material, so autonomous_run's fact-checker can
hold the post to it exactly like a news story.

State (which repos have gone out) lives in series_state.json, written by the
run and committed by the workflow's persist step.
"""

import base64
import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
REPOS_F = BASE / "repos.json"
STATE_F = BASE / "series_state.json"
API = "https://api.github.com"
MAX_TRIES = 5          # dead/archived repos skipped per run before giving up


def load_repos():
    return json.loads(REPOS_F.read_text(encoding="utf-8"))["repos"]


def load_state():
    if STATE_F.exists():
        return json.loads(STATE_F.read_text(encoding="utf-8"))
    return {"posted": [], "skipped": []}


def save_state(state):
    STATE_F.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def done_ids(state):
    return {e["repo"].lower() for e in state["posted"] + state["skipped"]}


def posted_today(state, today=None):
    today = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return any(e.get("date") == today for e in state["posted"])


def next_entries(repos, state):
    """Remaining repos, in list order."""
    done = done_ids(state)
    return [r for r in repos if r["repo"].lower() not in done]


def _get(path, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "thealgorithmzedge-series",
               "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def clean_readme(md, limit=6000):
    """Readable text from a README: no badges, images, HTML, code or tables.

    Keeps the section headings (as a one-line outline, they name the features)
    and every prose paragraph / bullet of reasonable length.
    """
    md = re.sub(r"(?s)<!--.*?-->", " ", md or "")
    md = re.sub(r"(?s)```.*?```", " ", md)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)          # images / badges
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)       # links -> text
    heads, body = [], []
    for l in md.splitlines():
        t = l.strip()
        if t.startswith("#"):
            h = t.lstrip("#").strip()
            if 2 < len(h) < 60:
                heads.append(h)
        elif not t.startswith("|"):                          # drop tables
            body.append(l)
    paras = []
    for block in re.split(r"\n\s*\n", "\n".join(body)):
        t = re.sub(r"\s+", " ", re.sub(r"^[>\-*\s]+", "", block)).strip()
        if len(t) >= 40:
            paras.append(t)
    out = ("README sections: " + "; ".join(heads[:25]) + "\n" if heads else "")
    return (out + "\n".join(paras))[:limit]


class RepoUnusable(Exception):
    """404 / archived / no description: skip it and move on."""


def fetch_facts(entry):
    """Live facts for one entry. Raises RepoUnusable to skip, other errors to
    abort the run (API down / rate limited: better no post than a made-up one)."""
    name = entry["repo"]
    org_only = "/" not in name
    try:
        if org_only:
            d = json.loads(_get(f"/orgs/{urllib.parse.quote(name)}"))
            return {"full_name": name, "description": d.get("description") or "",
                    "stars": None, "language": "", "license": "", "created": "",
                    "pushed": "", "topics": [], "readme": "",
                    "extra": f"GitHub organisation with {d.get('public_repos')} public repositories."}
        d = json.loads(_get(f"/repos/{name}"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410, 451):
            raise RepoUnusable(f"HTTP {e.code}")
        raise
    if d.get("archived") or d.get("disabled"):
        raise RepoUnusable("archived")
    if not d.get("description"):
        raise RepoUnusable("no description")
    try:
        readme = clean_readme(_get(f"/repos/{name}/readme",
                                   accept="application/vnd.github.raw"))
    except Exception:
        readme = ""
    home = d.get("homepage") or ""
    if home.startswith("http") and "github.com" not in home:
        try:                                  # project website text, best effort
            import research
            site = research.fetch_article([{"url": home}], limit=2500)
            if site:
                readme += "\n\nProject website text:\n" + site
        except Exception:
            pass
    return {"full_name": d["full_name"], "description": d["description"],
            "stars": d["stargazers_count"], "language": d.get("language") or "",
            "license": (d.get("license") or {}).get("spdx_id") or "",
            "created": (d.get("created_at") or "")[:10],
            "pushed": (d.get("pushed_at") or "")[:10],
            "topics": d.get("topics") or [], "readme": readme, "extra": ""}


# Hook library. Which opening sounds better is an A/B test across days: the type
# is chosen by day, recorded in series_state.json, and joined to Instagram metrics
# by hook_report.py. Every template is fact-safe: the slots come from the repo's
# own description / stats / licence, never from memory, and templates that need a
# fact are skipped (the rotation moves to the next one) when that fact is missing.
HOOK_TEMPLATES = {
    # --- curiosity / question ---
    "did_you_know":   "Did you know you can now {usp}?",
    "quick_question": "Quick question... would you like to {usp}?",
    "what_if":        "What if I told you... you could {usp}?",
    "bet_you_didnt":  "Bet you didn't know you could {usp}.",
    # --- pattern interrupt ---
    "stop_scrolling": "Stop scrolling... you can {usp}.",
    "wait_what":      "Wait... you can {usp}? Yes. You really can.",
    "imagine":        "Imagine if you could {usp}. Well... you can.",
    "something_cool": "Okay, here's something cool. You can {usp}.",
    # --- story / discovery ---
    "found_this":     "I found a GitHub project that lets you {usp}.",
    "one_project":    "One GitHub project, and it lets you {usp}.",
    "real_quick":     "Real quick. Want to {usp}? Here's the project.",
    "under_a_minute": "In under a minute, I'll show you a GitHub project that lets you {usp}.",
    # --- share / save drivers ---
    "save_this":      "Save this one. It lets you {usp}.",
    "send_friend":    "Send this to a friend who'd love to {usp}.",
    # --- fact-backed (need a stat from the repo's own page) ---
    "proof_stars":    "{stars} people starred this GitHub project. It lets you {usp}.",
    "since_year":     "This GitHub project has been around since {year}, and it lets you {usp}.",
    "fresh_update":   "Updated {fresh}... this GitHub project lets you {usp}.",
    "free_open":      "A free, open-source GitHub project that lets you {usp}.",
    # --- competitor framing (need a named alternative in the repo's own words) ---
    "stop_using":     "Stop using {alt}... this GitHub developer {just}made {feature} free.",
    "might_not_need": "You might not need {alt}... this GitHub project lets you {usp}.",
}
# Rotation order: question / pattern-interrupt / story / share / fact / competitor mixed
# so neighbouring days differ in style. Day 1 is the owner's example opening.
HOOK_CYCLE = ["did_you_know", "stop_using", "found_this", "proof_stars", "stop_scrolling",
              "send_friend", "what_if", "free_open", "wait_what", "might_not_need",
              "one_project", "since_year", "imagine", "save_this", "quick_question",
              "fresh_update", "bet_you_didnt", "real_quick", "something_cool",
              "under_a_minute"]
_OSI = {"MIT", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "ISC", "MPL-2.0", "GPL-2.0",
        "GPL-3.0", "AGPL-3.0", "LGPL-3.0", "LGPL-2.1", "UNLICENSE", "0BSD", "CC0-1.0"}


def stars_phrase(n):
    """182086 -> 'Over 180 thousand' (always rounded down, so always true)."""
    if n >= 1_000_000:
        return f"Over {int(n // 100_000) / 10:g} million"
    if n >= 10_000:
        return f"Over {int(n // 10_000) * 10} thousand"
    return f"Over {int(n // 1000)} thousand"


def _eligible(t, ctx):
    if t == "stop_using":
        return bool(ctx.get("alt") and ctx.get("feature_ok") and ctx.get("license"))
    if t == "might_not_need":
        return bool(ctx.get("alt"))
    if t == "proof_stars":
        return (ctx.get("stars") or 0) >= 1000
    if t == "since_year":
        return bool(ctx.get("year"))
    if t == "fresh_update":
        return ctx.get("pushed_days") is not None and ctx["pushed_days"] <= 30
    if t == "free_open":
        return (ctx.get("license") or "").upper() in _OSI
    return True


def pick_hook(day, ctx):
    """(type_id, template): the cycle entry for this day, or the next eligible one."""
    i = (day - 1) % len(HOOK_CYCLE)
    for step in range(len(HOOK_CYCLE)):
        t = HOOK_CYCLE[(i + step) % len(HOOK_CYCLE)]
        if _eligible(t, ctx):
            return t, HOOK_TEMPLATES[t]
    return "did_you_know", HOOK_TEMPLATES["did_you_know"]


def opening_for(day):                       # kept for older callers/tests
    t = HOOK_CYCLE[(day - 1) % len(HOOK_CYCLE)]
    return t, HOOK_TEMPLATES[t]


_GENERIC = {"open", "source", "self", "free", "local", "privacy", "private", "the", "a",
            "an", "this", "that", "best", "new", "better", "simple", "powerful", "modern",
            "fast", "lightweight", "official", "ai", "llm", "python", "javascript"}


def detect_alternative(text):
    """The product this repo says it is an alternative to, only if its own text says
    so ('Perplexity alternative', 'alternative to OpusClip'). Never guessed."""
    t = text or ""
    pats = (r"\b(?:alternative|replacement)s? (?:to|for) ([A-Z][A-Za-z0-9.+]*(?: [A-Z][A-Za-z0-9.+]*)?)",
            r"\b([A-Z][A-Za-z0-9.+]*) alternative\b",
            r"\b([A-Z][A-Za-z0-9.+]*)-style\b")
    for pat in pats:
        for m in re.finditer(pat, t):
            name = m.group(1).strip()
            if name.lower() not in _GENERIC and len(name) > 2:
                return name
    return None


def series_line(day, total):
    return (f"This is Day {day} of our exclusive {total}-day series, "
            "finding the best GitHub repo for you.")


def cta_say(day, total):
    left = total - day
    follow = (f"Follow for the next {left} repos" if left > 1 else
              "Follow for the last repo" if left == 1 else "Follow for what comes next")
    return ("Loved it? Save this, and send it to a friend. "
            f"{follow}... and comment REPO. I'll send you the full list.")


def series_note(day, total):
    return (
        f"SERIES MODE — Day {day} of {total} of the owner's '{total} AI repos worth "
        "knowing' series. Today's story is a GitHub repository, not news. Use ONLY "
        "facts that appear under EXTRA CONTEXT and SOURCE MATERIAL. If something is "
        "not stated there (hardware needs, privacy, offline use, speed, number of "
        "models, who uses it), leave it out — never add it from memory.\n"
        "  NEVER write the repository's name (or its owner's) anywhere — not in the "
        "headline, body, spoken lines or caption. Say 'this tool' or 'this repo'.\n"
        "  The reel is spoken aloud by a warm, playful voice, like a clever friend "
        "sharing a find. Short sentences, '...' for a beat. Keep the WHOLE reel "
        "under 60 seconds: about 20 words for hook.usp's sentence and at most 18 "
        "spoken words per content slide.\n"
        "  JSON additions (required):\n"
        "    hook.usp = ONE verb phrase, max 14 words, no leading 'to', saying what "
        "the repo lets a person do, restated in plain words from the 'Description:' "
        "line (e.g. 'run AI models like DeepSeek and Gemma on your own computer'). "
        "Only ideas that are in the description or README.\n"
        "    hook.feature = a short noun phrase, max 8 words, naming the capability "
        "the repo gives people, from the description or README (e.g. 'AI answers with "
        "cited sources'). Used only for the 'stop using' hook.\n"
        "    hook.headline = the on-screen version, max 8 words.\n"
        "    every content slide gets a \"say\" string: what is spoken for that slide.\n"
        "  The 4 content slides, in this order:\n"
        "    1. What it does (description/README). 2. What is inside or how it is "
        "used (README). 3. The facts: round the star count in speech ('over 180 "
        "thousand stars'), plus licence, language, how long it has existed. 4. What "
        "to know before using it (only a caveat the README or licence supports; if "
        "none, say to read the README and licence first).\n"
        "  The caption: max 60 words, warm, no hashtags beyond the usual 8-10.\n"
        "  For trading or finance repos, say it is for research and not financial "
        "advice. Do not explain how to bypass paywalls, bot detection or terms of "
        "service. The opening line, the series line and the call to action are added "
        "by the system — do not write them.")


_STOP = set("a an the and or of to in on for with from by is are be it its this that "
            "your you our we as at into over any all more can will get up out how "
            "what why who one two use used using lets let make makes made".split())


def _words(text):
    ws = (w.rstrip(".'+-") for w in re.findall(r"[a-z0-9][a-z0-9'+.-]*", (text or "").lower()))
    return [w for w in ws if w and w not in _STOP and len(w) > 1]


def hook_grounded(headline, source_text, min_overlap=0.5):
    """True if the hook only leans on the source: most of its content words occur
    in the description/README, and any number in it occurs there too."""
    src = set(_words(source_text))
    ws = _words(headline)
    if not ws:
        return False
    nums = [w for w in ws if any(c.isdigit() for c in w)]
    if any(n not in src for n in nums):
        return False
    return sum(1 for w in ws if w in src) / len(ws) >= min_overlap


def fallback_hook(story):
    """No imagination: the repo name plus its own description, trimmed."""
    facts = story["summary"]
    m = re.search(r"Description: (.*?)(?: \| |$)", facts)
    desc = (m.group(1) if m else story["headline"]).strip()
    words = desc.split()
    return " ".join(words[:11]).rstrip(",;:- ") + ("…" if len(words) > 11 else "")


def _description(story):
    m = re.search(r"Description: (.*?)(?: \| |$)", story["summary"])
    return (m.group(1) if m else story["headline"]).strip().rstrip(".")


def scrub_name(text, repo):
    """Remove the repo's name from any text: 'Ollama lets...' -> 'This tool lets...'.
    The recording shows the name; the words and captions must not give it away."""
    if not text:
        return text
    name = repo.split("/")[-1]
    variants = {name, name.replace("-", " "), name.replace("-", ""), name.replace("_", " ")}
    squashed = re.sub(r"[^a-z0-9]", "", name.lower())
    text = re.sub(r"#\w*" + re.escape(squashed) + r"\w*", "", text, flags=re.I)   # hashtags first
    for v in sorted((x for x in variants if len(x) > 2), key=len, reverse=True):
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![A-Za-z0-9])", re.I)

        def repl(m, t=text):
            before = t[:m.start()].rstrip()
            return "This tool" if (not before or before[-1] in ".!?\n") else "this tool"
        text = pat.sub(repl, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def finalize(p, story):
    """Everything fixed about the series flow is added here, in code, so every
    reel follows the same flow regardless of what the model wrote:
    kicker -> grounded hook -> rotating opening + series line (spoken) ->
    4 content slides -> fixed save/share/follow/comment call to action."""
    s = story["series"]
    repo, day, total = s["repo"], s["day"], s["total"]
    src = story["summary"] + "\n" + story.get("article", "") + "\n" + repo

    hook = p.setdefault("hook", {})
    hook["kicker"] = f"Repo {day} of {total}"
    if not hook_grounded(hook.get("headline", ""), src):
        print(f"[series] hook headline not grounded, using fallback: {hook.get('headline')!r}")
        hook["headline"] = fallback_hook(story)
    usp = (hook.get("usp") or "").strip().rstrip(".?!")
    usp = re.sub(r"^(to|you can)\s+", "", usp, flags=re.I)
    lic = (s.get("license") or "").strip()
    if lic.upper() in ("NOASSERTION", "OTHER"):
        lic = ""
    alt = s.get("alt")
    feature = (hook.get("feature") or "").strip().rstrip(".?!")
    feature_ok = bool(feature) and hook_grounded(feature, src, min_overlap=0.4)
    today = datetime.date.today()

    def _days(iso):
        try:
            return (today - datetime.date.fromisoformat(iso)).days
        except Exception:
            return None
    age_days, pushed_days = _days(s.get("created", "")), _days(s.get("pushed", ""))
    ctx = {"alt": alt, "feature_ok": feature_ok, "license": lic, "stars": s.get("stars"),
           "year": (s.get("created") or "")[:4] or None, "pushed_days": pushed_days}
    htype, tmpl = pick_hook(day, ctx)
    s["opening"] = htype
    slots = {"usp": usp, "alt": alt or "", "feature": feature,
             "just": "just " if (age_days is not None and age_days <= 180) else "",
             "stars": stars_phrase(s.get("stars") or 0), "year": ctx["year"] or "",
             "fresh": ("this week" if (pushed_days is not None and pushed_days <= 7) else "this month")}
    needs_usp = "{usp}" in tmpl
    if needs_usp and not (usp and hook_grounded(usp, src, min_overlap=0.4)):
        print(f"[series] usp not grounded ({usp!r}), using the description")
        d = _description(story).split()
        hook["say"] = "Here's one worth knowing... " + " ".join(d[:18]).rstrip(",;:- ") + "."
    else:
        hook["say"] = tmpl.format(**slots)
    hook["say"] += " " + series_line(day, total)

    for sl in p.get("slides", []):
        if not sl.get("say"):
            sl["say"] = f"{sl.get('headline', '')}. {sl.get('body', '')}".strip(". ")

    p["cta"] = {"headline": "Save · Share · Follow", "body": "Comment REPO for the full list",
                "say": cta_say(day, total)}

    # the name stays out of every word and caption (the recording shows it)
    hook["headline"] = scrub_name(hook["headline"], repo)
    hook["say"] = scrub_name(hook["say"], repo)
    for sl in p.get("slides", []):
        for k in ("headline", "body", "say"):
            sl[k] = scrub_name(sl.get(k, ""), repo)

    cap = scrub_name(p.get("caption", ""), repo).rstrip()
    cap += "\n\nSave this and share it with a friend. Comment REPO and I'll DM you the full list.\n#100AIRepos"
    p["caption"] = cap
    return p


def build_story(entry, facts, day, total):
    bits = [f"Repository: {facts['full_name']}", f"Description: {facts['description']}"]
    if facts["stars"] is not None:
        bits.append(f"GitHub stars: {facts['stars']:,}")
    for label, key in (("Main language", "language"), ("Licence", "license"),
                       ("Created", "created"), ("Last pushed", "pushed")):
        if facts[key]:
            bits.append(f"{label}: {facts[key]}")
    if facts["topics"]:
        bits.append("Topics: " + ", ".join(facts["topics"][:10]))
    if facts["extra"]:
        bits.append(facts["extra"])
    if entry.get("note"):
        bits.append(f"Owner's note: {entry['note']}")
    headline = f"{facts['full_name'].split('/')[-1]}: {facts['description']}"[:140]
    return {"headline": headline, "url": f"https://github.com/{facts['full_name']}",
            "summary": " | ".join(bits), "article": facts["readme"],
            "sources_covering": ["GitHub"], "coverage_count": 1,
            "all_headlines": [headline], "runners_up": [],
            "sources_ok": ["GitHub"], "sources_failed": [], "source_count": 1,
            "degraded": False, "score": 0,
            "series": {"repo": entry["repo"], "day": day, "total": total,
                       "license": facts.get("license", ""), "created": facts.get("created", ""),
                       "pushed": facts.get("pushed", ""), "stars": facts.get("stars"),
                       "alt": detect_alternative(
                           f"{facts['description']} {entry.get('note', '')} "
                           f"{(facts.get('readme') or '')[:1200]}")}}


def pick_story(repos=None, state=None):
    """(story, state) for the next usable repo, or (None, state).

    Unusable repos are recorded as skipped so they are never retried.
    """
    repos = repos if repos is not None else load_repos()
    state = state if state is not None else load_state()
    total = len(repos)
    for _ in range(MAX_TRIES):
        remaining = next_entries(repos, state)
        if not remaining:
            print("[series] all repos done")
            return None, state
        entry = remaining[0]
        day = len(state["posted"]) + 1
        try:
            facts = fetch_facts(entry)
        except RepoUnusable as e:
            print(f"[series] skipping {entry['repo']}: {e}")
            state["skipped"].append({"repo": entry["repo"], "reason": str(e),
                                     "date": datetime.date.today().isoformat()})
            save_state(state)
            continue
        return build_story(entry, facts, day, total), state
    print("[series] too many unusable repos in a row; stopping this run")
    return None, state


def mark_posted(state, story, media_id):
    s = story["series"]
    state["posted"].append({"repo": s["repo"], "day": s["day"], "media_id": media_id,
                            "opening": s.get("opening"),
                            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat()})
    save_state(state)
