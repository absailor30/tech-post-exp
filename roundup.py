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
     "kicker": "Anthropic IPO",
     "lines": ["Anthropic's amended IPO filing is out, and the numbers are huge.",
               "It reports about seventeen billion dollars of revenue in the third quarter, "
               "and a net loss of twenty-three billion.",
               "It also lists about eight hundred ninety-five billion dollars in compute and "
               "infrastructure commitments."]},
    {"url": "https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits",
     "kicker": "OpenAI",
     "lines": ["OpenAI is changing its usage limits.",
               "From December, Plus, Pro and Business plans share one allowance across "
               "ChatGPT and Codex, counted in tokens.",
               "How fast it runs down depends on the model and the task you choose."]},
    {"url": "https://www.sec.gov/Archives/edgar/data/0001321655/000132165526000045/a2026q3ex991pressrelease.htm",
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


def segment(story, i, out, last):
    lines = story["lines"]
    specs = [{"kind": "hook", "headline": lines[0].rstrip("."), "kicker": story["kicker"], "say": lines[0]}]
    n = len(lines) - 1
    for j, t in enumerate(lines[1:], 1):
        specs.append({"kind": "content", "headline": t, "body": "", "say": t, "idx": j + 1, "total": n + 2})
    if last:
        specs.append({"kind": "cta", "headline": "Follow", "body": "", "say": OUTRO})
    webreel.build_web_reel(specs, story["url"], out, workdir=str(Path(out).with_suffix("")) + "_w")


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
