"""Research the day's biggest AI story across many independent sources.

Nothing gets written until this runs. The planner is never allowed to invent
a topic from its own memory — it may only write about what came back here.

"Most famous" is measured, not guessed: every source is fetched, items are
clustered by shared keywords, and the winning cluster is the story the most
INDEPENDENT outlets are covering right now. Cross-source coverage outranks
raw engagement, because ten outlets covering one launch is a bigger story
than one Reddit thread with a lot of upvotes.

Sources are deliberately mixed so no single publisher can steer the account:
  aggregators with real popularity signal  - Hacker News, 3x Reddit
  mainstream tech press                    - TechCrunch, Verge, Ars, Wired,
                                             VentureBeat, MIT Tech Review,
                                             ZDNet, Engadget, AI News
  neutral aggregator                       - Google News
  model releases                           - Hugging Face trending

Usage:
  python research.py            # print the winning story + runners-up
  python research.py --json     # machine-readable
"""

import concurrent.futures as futures
import datetime
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
CACHE = BASE / "research.jsonl"

UA = {"User-Agent": "Mozilla/5.0 (compatible; algorithmzedge-research/1.0)"}
TIMEOUT = 25

# A story must clear this many DISTINCT sources fetched successfully or we do
# not post at all. Ten is the target; five is the floor the owner set.
WANT_SOURCES = 10
MIN_SOURCES = 5

RSS = {
    "TechCrunch":       "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge":        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica":     "https://arstechnica.com/ai/feed/",
    "VentureBeat":      "https://venturebeat.com/category/ai/feed/",
    "MIT Tech Review":  "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Wired":            "https://www.wired.com/feed/tag/ai/latest/rss",
    "ZDNet":            "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "Engadget":         "https://www.engadget.com/rss.xml",
    "AI News":          "https://www.artificialintelligence-news.com/feed/",
    "Google News":      ("https://news.google.com/rss/search?q=artificial+intelligence+OR"
                         "+%22AI+model%22+when:2d&hl=en-US&gl=US&ceid=US:en"),
}

REDDIT = {
    "r/artificial":     "https://www.reddit.com/r/artificial/top.json?t=day&limit=25",
    "r/LocalLLaMA":     "https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=25",
    "r/MachineLearning": "https://www.reddit.com/r/MachineLearning/top.json?t=day&limit=25",
}

HN = ("https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story"
      "&numericFilters=points%3E30&hitsPerPage=40")

HF = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=20"

# Words that make an item AI-relevant. An item must hit at least one.
AI_TERMS = {
    "ai", "a.i", "artificial intelligence", "llm", "llms", "gpt", "chatgpt",
    "openai", "anthropic", "claude", "gemini", "deepmind", "llama", "meta ai",
    "mistral", "deepseek", "qwen", "grok", "xai", "copilot", "midjourney",
    "stable diffusion", "hugging face", "nvidia", "transformer", "neural",
    "machine learning", "deep learning", "agent", "agents", "agentic",
    "model", "models", "chatbot", "diffusion", "inference", "fine-tune",
    "fine-tuning", "multimodal", "reasoning model", "benchmark", "sora",
    "perplexity", "cursor", "codex", "gemma", "phi-", "generative",
}

# Never worth a post even if it trends.
NOISE = {"deal", "deals", "discount", "coupon", "sale", "prime day", "gift guide",
         "best laptop", "horoscope", "sponsored", "advertisement"}

STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "is", "are", "was", "were", "be", "been", "being", "it",
    "its", "this", "that", "these", "those", "as", "how", "why", "what", "when",
    "who", "will", "can", "could", "would", "should", "may", "might", "has",
    "have", "had", "do", "does", "did", "not", "no", "you", "your", "we", "our",
    "they", "their", "he", "she", "his", "her", "i", "me", "my", "new", "now",
    "just", "more", "most", "than", "then", "over", "after", "before", "about",
    "into", "out", "up", "down", "off", "all", "some", "any", "s", "t", "says",
    "said", "get", "gets", "got", "make", "makes", "made", "use", "using", "used",
    "one", "two", "first", "last", "next", "here", "there", "via", "vs",
}


# ---------------------------------------------------------------- fetching

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def age_hours(stamp):
    """Parse whatever date shape a feed hands us. Unknown -> treat as 24h old."""
    if not stamp:
        return 24.0
    if isinstance(stamp, (int, float)):
        dt = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc)
    else:
        dt = None
        for parse in (
            lambda s: datetime.datetime.strptime(s[:25].strip(), "%a, %d %b %Y %H:%M:%S"),
            lambda s: datetime.datetime.fromisoformat(s.replace("Z", "+00:00")),
        ):
            try:
                dt = parse(stamp)
                break
            except (ValueError, TypeError):
                continue
        if dt is None:
            return 24.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600)


def from_rss(name, url):
    root = ET.fromstring(fetch(url))
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for it in items[:30]:
        def pick(*tags):
            for t in tags:
                el = it.find(t)
                if el is not None:
                    return el.get("href") if el.get("href") else (el.text or "")
            return ""
        title = clean(pick("title", "{http://www.w3.org/2005/Atom}title"))
        link = clean(pick("link", "{http://www.w3.org/2005/Atom}link"))
        date = clean(pick("pubDate", "published",
                          "{http://www.w3.org/2005/Atom}published",
                          "{http://www.w3.org/2005/Atom}updated"))
        summary = clean(pick("description",
                             "{http://www.w3.org/2005/Atom}summary"))[:400]
        if title:
            out.append({"title": title, "url": link, "source": name,
                        "engagement": 0, "age_h": age_hours(date),
                        "summary": summary})
    return out


def from_reddit(name, url):
    data = json.loads(fetch(url))
    out = []
    for c in data.get("data", {}).get("children", []):
        d = c.get("data", {})
        if d.get("stickied"):
            continue
        out.append({"title": clean(d.get("title", "")), "source": name,
                    "url": "https://reddit.com" + d.get("permalink", ""),
                    "engagement": int(d.get("score", 0)),
                    "age_h": age_hours(d.get("created_utc")),
                    "summary": clean(d.get("selftext", ""))[:400]})
    return out


def from_hn(name, url):
    data = json.loads(fetch(url))
    return [{"title": clean(h.get("title") or h.get("story_title") or ""),
             "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "source": name, "engagement": int(h.get("points") or 0),
             "age_h": age_hours(h.get("created_at")), "summary": ""}
            for h in data.get("hits", []) if h.get("title") or h.get("story_title")]


def from_hf(name, url):
    """Trending model releases — the launch itself, before press picks it up."""
    out = []
    for m in json.loads(fetch(url)):
        mid = m.get("modelId") or m.get("id") or ""
        if not mid:
            continue
        out.append({"title": f"{mid} is trending on Hugging Face",
                    "url": f"https://huggingface.co/{mid}", "source": name,
                    "engagement": int(m.get("likes") or 0),
                    "age_h": age_hours(m.get("lastModified")),
                    "summary": f"pipeline: {m.get('pipeline_tag', 'n/a')}, "
                               f"downloads: {m.get('downloads', 0)}"})
    return out


def gather():
    """Fetch every source in parallel. One dead feed never blocks the run."""
    jobs = ([(n, u, from_rss) for n, u in RSS.items()]
            + [(n, u, from_reddit) for n, u in REDDIT.items()]
            + [("Hacker News", HN, from_hn), ("Hugging Face", HF, from_hf)])
    items, ok, failed = [], [], []
    with futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        running = {ex.submit(fn, n, u): n for n, u, fn in jobs}
        for fut in futures.as_completed(running):
            name = running[fut]
            try:
                got = fut.result()
            except Exception as e:
                failed.append(f"{name}: {type(e).__name__}")
                continue
            got = [i for i in got if i["title"]]
            if got:
                ok.append(name)
                items += got
            else:
                failed.append(f"{name}: empty")
    return items, sorted(ok), sorted(failed)


# ---------------------------------------------------------------- ranking

def is_ai(item):
    blob = f"{item['title']} {item.get('summary', '')}".lower()
    if any(n in blob for n in NOISE):
        return False
    words = set(re.findall(r"[a-z0-9.\-]+", blob))
    return bool(words & AI_TERMS) or any(t in blob for t in AI_TERMS if " " in t)


def keywords(title):
    words = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9'\-\.]+", title.lower())
    return {w for w in words if w not in STOP and len(w) > 2}


def cluster(items):
    """Group items describing the same story.

    Two headlines belong together when they share enough distinctive words.
    Deliberately simple and dependency-free — the goal is only to notice that
    six outlets published about the same launch this morning.
    """
    groups = []
    for it in sorted(items, key=lambda i: -i["engagement"]):
        kw = keywords(it["title"])
        if len(kw) < 2:
            continue
        for g in groups:
            shared = kw & g["keywords"]
            if len(shared) >= 2 or (len(shared) == 1 and len(kw & g["keywords"]) / max(1, min(len(kw), len(g["keywords"]))) > 0.34):
                g["items"].append(it)
                g["keywords"] |= kw
                break
        else:
            groups.append({"keywords": set(kw), "items": [it]})
    return groups


def score(group):
    """Fame first, engagement second, freshness third."""
    sources = {i["source"] for i in group["items"]}
    engagement = sum(i["engagement"] for i in group["items"])
    youngest = min(i["age_h"] for i in group["items"])
    recency = max(0.0, 1.0 - youngest / 48.0)
    # Cross-source coverage dominates: each extra independent outlet is worth
    # more than any amount of upvotes on a single thread.
    return round(len(sources) * 100 + min(engagement, 3000) / 30 + recency * 25, 2)


def research():
    items, ok, failed = gather()
    if len(ok) < MIN_SOURCES:
        raise SystemExit(
            f"research failed: only {len(ok)} source(s) responded "
            f"({', '.join(ok) or 'none'}); need at least {MIN_SOURCES}. "
            f"failures: {'; '.join(failed)}")

    fresh = [i for i in items if is_ai(i) and i["age_h"] <= 72]
    if not fresh:
        raise SystemExit("research failed: no AI stories in the last 72h")

    groups = cluster(fresh)
    for g in groups:
        g["score"] = score(g)
        g["sources"] = sorted({i["source"] for i in g["items"]})
    groups.sort(key=lambda g: -g["score"])

    top = groups[0]
    lead = max(top["items"], key=lambda i: (i["engagement"], -i["age_h"]))
    result = {
        "headline": lead["title"],
        "url": lead["url"],
        "summary": lead.get("summary", ""),
        "sources_covering": top["sources"],
        "coverage_count": len(top["sources"]),
        "score": top["score"],
        "all_headlines": [f"[{i['source']}] {i['title']}" for i in top["items"][:12]],
        "runners_up": [{"headline": g["items"][0]["title"],
                        "sources": g["sources"], "score": g["score"]}
                       for g in groups[1:5]],
        "sources_ok": ok,
        "sources_failed": failed,
        "source_count": len(ok),
        "degraded": len(ok) < WANT_SOURCES,
        "researched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return result


def forget(media_id, headline=None):
    """Drop a story from the cache because its post no longer exists.

    The cache means "stories currently live on the account". If a post is
    deleted, the story was never really covered, and leaving it here would
    block the account from ever posting that story again.

    Matches on media_id, falling back to the headline — entries written
    before record() started storing media_id have no id to match on.
    """
    if not CACHE.exists():
        return 0
    kept, dropped = [], 0
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            if d.get("media_id") == media_id or (headline and d.get("headline") == headline):
                dropped += 1
                continue
        except json.JSONDecodeError:
            pass
        kept.append(line)
    CACHE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return dropped


def record(result):
    """Append a story to the cache ONCE IT HAS ACTUALLY BEEN PUBLISHED.

    research() used to write here itself, and the duplicate check then read
    the cache straight back — so every story matched itself and every run
    fell through to a runner-up. The cache must only ever describe posts
    that went out.
    """
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")


def recent_story_keys(n=60):
    """Keyword sets of stories already covered, so we never repeat one."""
    if not CACHE.exists():
        return []
    out = []
    for line in CACHE.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(keywords(json.loads(line)["headline"]))
        except (json.JSONDecodeError, KeyError):
            continue
    return out


if __name__ == "__main__":
    r = research()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2))
    else:
        print(f"sources responding : {r['source_count']} ({', '.join(r['sources_ok'])})")
        if r["sources_failed"]:
            print(f"sources failed     : {', '.join(r['sources_failed'])}")
        print(f"\nTOP STORY (covered by {r['coverage_count']} outlets, score {r['score']})")
        print(f"  {r['headline']}\n  {r['url']}")
        print("\ncoverage:")
        for h in r["all_headlines"]:
            print(f"  {h}")
        print("\nrunners-up:")
        for g in r["runners_up"]:
            print(f"  [{len(g['sources'])} outlets, {g['score']}] {g['headline'][:80]}")
