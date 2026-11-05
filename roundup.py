"""Weekly AI roundup reel: one segment per story, each a Chrome scroll through the PRIMARY source
(filing, press release, company post), narrated, then joined. Every line below was checked
against the source page on 2026-11-04; a segment whose page cannot be captured is dropped.

    python roundup.py out.mp4
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

import webreel

STORIES = [
    {"url": "https://www.sec.gov/Archives/edgar/data/0002130357/000162828026068676/anthropicpbc-sx1ax1.htm",
     "alt": ["https://www.cnbc.com/2026/11/02/anthropic-ant-s-1-quarter-financials.html",
             "https://qz.com/anthropic-amended-ipo-filing-revenue-growth-110226"],
     "source": "Anthropic amended S-1, filed Nov 2 (SEC)",
     "facts": ["Q3 revenue: about $17 billion", "Q3 net loss: $23.29 billion",
               "Purchase commitments: about $895 billion"],
     "kicker": "Anthropic IPO",
     "lines": ["Anthropic's amended IPO filing is out, and the numbers are huge.",
               "It reports about seventeen billion dollars of revenue in the third quarter, "
               "and a net loss of twenty-three billion.",
               "It also lists about eight hundred ninety-five billion dollars in compute and "
               "infrastructure commitments."]},
    {"url": "https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits",
     "alt": ["https://openai.com/business/pricing/", "https://developers.openai.com/codex/pricing"],
     "source": "OpenAI Help Center",
     "facts": ["From December: one shared allowance for ChatGPT and Codex",
               "Applies to Plus, Pro and Business plans", "Counted in tokens"],
     "kicker": "OpenAI",
     "lines": ["OpenAI is changing its usage limits.",
               "From December, Plus, Pro and Business plans share one allowance across "
               "ChatGPT and Codex, counted in tokens.",
               "How fast it runs down depends on the model and the task you choose."]},
    {"url": "https://www.businesswire.com/news/home/20261101396214/en/Palantir-Reports-Q3-2026-U.S.-Comm-Revenue-Growth-of-148-YY-and-Revenue-Growth-of-96-YY-Raises-FY-2026-Revenue-Guidance-to-91-YY-Growth-and-U.S.-Comm-Revenue-Guidance-to-143-YY-Crushing-Consensus-Expectations",
     "alt": ["https://www.sec.gov/Archives/edgar/data/0001321655/000132165526000045/a2026q3ex991pressrelease.htm"],
     "source": "Palantir Q3 2026 results (press release, SEC 8-K)",
     "facts": ["Revenue: $2.313 billion, up 96%", "U.S. commercial revenue: $984 million, up 148%",
               "FY2026 revenue guidance: $8.530-8.534 billion"],
     "kicker": "Palantir",
     "lines": ["Palantir just reported its third quarter.",
               "Revenue was two point three billion dollars, up ninety-six percent. "
               "U.S. commercial revenue grew a hundred forty-eight percent.",
               "It raised its full-year revenue guidance to about eight point five three billion."]},
    {"url": "https://www.crowdstrike.com/en-us/press-releases/crowdstrike-to-acquire-fiddler-to-deliver-agent-observability/",
     "kicker": "CrowdStrike",
     "lines": ["CrowdStrike is buying two AI security companies.",
               "Fiddler, for watching what AI agents do, and Dreadnode, for testing AI "
               "models before they ship.",
               "The price was not disclosed. Both are expected to close in CrowdStrike's "
               "fiscal fourth quarter."]},
    {"url": "https://www.anthropic.com/research/provable-inference",
     "kicker": "Anthropic research",
     "lines": ["Anthropic released a way to prove which AI model answered you.",
               "It's called FlashProve, and it proves a reply came from committed model "
               "weights without revealing them.",
               "The cost is high, seventy to ninety-five times the compute, and it only "
               "handles short prompts for now."]},
]
OUTRO = "These were the five AI stories this week, checked against the original sources. Follow for more."


def card_url(story, tmp):
    """Last resort when every page for a story blocks the capture: a plain source card."""
    import html
    rows = "".join(f"<li>{html.escape(f)}</li>" for f in story.get("facts", []))
    p = Path(tmp) / f"card_{abs(hash(story['kicker']))}.html"
    p.write_text(f"""<html><body style="margin:0;background:#0A0C10;color:#fff;font-family:Arial,sans-serif;padding:150px 36px 0">
<ul style="font-size:30px;line-height:1.4;margin:0;padding-left:28px;font-weight:700">{rows}</ul>
<div style="margin-top:50px;font-size:19px;color:#aaa">Source: {html.escape(story.get('source', ''))}</div>
</body></html>""", encoding="utf-8")
    return p.as_uri()


def segment(story, i, out, last):
    lines = story["lines"]
    specs = [{"kind": "hook", "headline": lines[0].rstrip("."), "kicker": story["kicker"], "say": lines[0]}]
    n = len(lines) - 1
    for j, t in enumerate(lines[1:], 1):
        specs.append({"kind": "content", "headline": t, "body": "", "say": t, "idx": j + 1, "total": n + 2})
    if last:
        specs.append({"kind": "cta", "headline": "Follow", "body": "", "say": OUTRO})
    tmp = Path(out).parent
    for url in [story["url"], *story.get("alt", [])]:
        try:
            webreel.build_web_reel(specs, url, out, workdir=str(Path(out).with_suffix("")) + "_w")
            return
        except Exception as e:
            print(f"[roundup] {story['kicker']}: {url[:70]} failed ({e!r:.90})")
    if story.get("facts"):
        print(f"[roundup] {story['kicker']}: every page blocked, using a source card")
        webreel.build_web_reel(specs, card_url(story, tmp), out, workdir=str(Path(out).with_suffix("")) + "_w")
    else:
        raise RuntimeError("no page could be captured")


def main(out):
    ff = get_ffmpeg_exe()
    tmp = Path(tempfile.mkdtemp(prefix="roundup"))
    done = []
    for i, s in enumerate(STORIES):
        p = tmp / f"seg{i}.mp4"
        try:
            segment(s, i, str(p), last=(i == len(STORIES) - 1))
            done.append(p)
        except Exception as e:
            print(f"[roundup] dropped {s['kicker']}: {e!r:.200}")
    if not done:
        raise SystemExit("no segment could be captured")
    lst = tmp / "list.txt"
    lst.write_text("\n".join(f"file '{p}'" for p in done))
    subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out],
                   check=True, capture_output=True)
    print(f"[roundup] {len(done)}/{len(STORIES)} segments -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "roundup.mp4")
