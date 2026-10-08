"""Quote cards: a short reel built around ONE real, verifiable quote from a named person
in today's news story (a CEO, an official, a researcher), credited on screen and in the caption.

Why not clips: the footage belongs to whoever filmed it, and Instagram stopped recommending
re-uploaded video unless it is transformed. A card made of the exact words, a credit, our own
narration and context is original work, and every word of the quote is checked against the
article text before anything is posted (fail closed: no verified quote, no quote card).
"""
import json
import re
import urllib.parse

QUOTE_MIN_WORDS, QUOTE_MAX_WORDS = 8, 32


def _norm(s):
    """Compare quotes ignoring curly vs straight quotes, dashes, case and spacing."""
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"') \
                 .replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"[^a-z0-9']+", " ", s.lower()).strip()


def verify(quote, speaker, article):
    """True only if the quote appears verbatim in the article and the speaker is named in it."""
    nq, na = _norm(quote), _norm(article)
    n = len(nq.split())
    if not (QUOTE_MIN_WORDS <= n <= QUOTE_MAX_WORDS) or nq not in na:
        return False
    parts = [w for w in _norm(speaker).split() if len(w) > 2]
    return bool(parts) and parts[-1] in na


def outlet(story):
    host = urllib.parse.urlsplit(story.get("url", "")).netloc.lower().removeprefix("www.")
    names = {"theguardian.com": "The Guardian", "techcrunch.com": "TechCrunch",
             "theverge.com": "The Verge", "arstechnica.com": "Ars Technica",
             "wired.com": "WIRED", "reuters.com": "Reuters", "bbc.co.uk": "BBC",
             "bbc.com": "BBC", "nytimes.com": "The New York Times",
             "technologyreview.com": "MIT Technology Review", "the-decoder.com": "The Decoder",
             "theregister.com": "The Register", "engadget.com": "Engadget",
             "venturebeat.com": "VentureBeat", "zdnet.com": "ZDNET"}
    return names.get(host, host or "the original report")


def find_quote(story, call_llm):
    """Ask the model for ONE quote; accept it only if verify() passes. Returns dict or None."""
    article = story.get("article", "")
    if len(article) < 400:
        return None
    raw = call_llm(
        "From the ARTICLE below, pick the single most striking DIRECT QUOTE spoken or written "
        "by a NAMED person (an executive, official, researcher or well-known figure). Copy it "
        f"EXACTLY, character for character, {QUOTE_MIN_WORDS}-{QUOTE_MAX_WORDS} words, with no "
        "edits, no merged sentences and no ellipses. Skip quotes from anonymous sources, and "
        "skip quotes that only make sense with missing context. If there is no such quote, say none.\n\n"
        f"ARTICLE:\n{article}\n\n"
        "Keep any thinking short. Finish with ONE last line, exactly:\n"
        'QUOTE_JSON: {"quote": "...", "speaker": "full name", "role": "title and company as the '
        'article gives them", "context": "ONE plain sentence, max 22 words, saying where/when it '
        'was said, using only facts in the article"}   (or QUOTE_JSON: {"none": true})',
        max_tokens=4000)
    hits = re.findall(r"(?im)^\s*\**QUOTE_JSON:?\**\s*(\{.*\})\s*$", raw or "")
    if not hits:
        return None
    try:
        q = json.loads(hits[-1])
    except json.JSONDecodeError:
        return None
    if q.get("none") or not all(q.get(k) for k in ("quote", "speaker", "context")):
        return None
    q["quote"] = q["quote"].strip().strip('"“”')
    if not verify(q["quote"], q["speaker"], article):
        print(f"[quote] rejected, not verbatim in the article: {q['quote'][:80]!r}")
        return None
    q.setdefault("role", "")
    return q


def build_plan(story, q):
    """A plan dict shaped like the news plan, so the normal render/publish path takes it."""
    who = q["speaker"]
    src = outlet(story)
    role = (q.get("role") or "").strip().rstrip(".")
    who_line = f"{who}, {role}" if role else who
    short = " ".join(q["quote"].split()[:8])
    return {
        "topic": f"{who}: {short}"[:80],
        "style": "quote",
        "theme": "dark",
        "hook": {"kicker": "In their words",
                 "headline": f"{who} just said this",
                 "say": f"{who_line}, just said this."},
        "slides": [
            {"kind": "quote", "headline": who_line, "body": q["quote"],
             "say": f"In their words: {q['quote']}"},
            {"headline": "The context", "body": f"{q['context'].rstrip('.')}. Source: {src}",
             "say": f"{q['context'].rstrip('.')}. Source: {src}."},
        ],
        "cta": {"headline": "Follow for more", "body": "Real quotes, with the source, daily",
                "say": "What do you think? Comment below, and follow for more."},
        "caption": (f"“{q['quote']}”\n\n— {who_line}\n\n{q['context'].rstrip('.')}.\n\n"
                    f"Source: {src} ({story.get('url', '')})\n\nDo you agree? Tell me below.\n\n"
                    "#AI #AINews #ArtificialIntelligence #Tech #TechNews #OpenAI #Quote #AIEthics"),
    }
