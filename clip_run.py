"""Post a clip reel: python clip_run.py --url <video link> --headline "..." --highlight "Name" ...

The source clip is downloaded into a temp folder and is never committed; only the finished
reel (headline, captions, credit added) goes into the repo and to Instagram. The operator
supplies a clip they are cleared to use; this tool does not fetch from social platforms.
"""
import argparse
import datetime
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import autonomous_run as ar
import clipcard

BLOCKED = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com",
           "facebook.com", "fb.watch")


def download(url, dest):
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
    if any(host.endswith(b) for b in BLOCKED):
        sys.exit(f"{host} links are not accepted: supply a direct link to a video file you are "
                 "cleared to use (Drive, Dropbox, a .mp4 URL)")
    if "drive.google.com" in host:
        import gdown
        out = gdown.download(url, str(dest), quiet=True, fuzzy=True)
        if not out:
            sys.exit("could not download the Drive file (is the link shared as 'anyone with the link'?)")
        return Path(out)
    r = subprocess.run(["curl", "-L", "-sS", "--fail", "--max-filesize", str(200 * 1024 * 1024),
                        "-o", str(dest), url], capture_output=True, text=True)
    if r.returncode != 0 or not Path(dest).exists():
        sys.exit(f"download failed: {r.stderr[-300:]}")
    return Path(dest)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--url", required=True)
    a.add_argument("--headline", required=True)
    a.add_argument("--highlight", default="")
    a.add_argument("--source", default="", help="who owns the footage, e.g. 'CNBC' or 'White House'")
    a.add_argument("--source-url", default="")
    a.add_argument("--start", type=float, default=0.0)
    a.add_argument("--end", type=float, default=None)
    a.add_argument("--note", default="", help="one or two lines of context for the caption")
    a.add_argument("--dry", action="store_true")
    a.add_argument("--no-captions", action="store_true")
    args = a.parse_args()

    if not args.dry:
        ar.verify_ig_token()
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", args.headline.lower())[:40].strip("-")
    outdir = ar.REPO_DIR / "images" / f"{stamp}-clip-{slug}"
    n = 2
    while outdir.exists():
        outdir = ar.REPO_DIR / "images" / f"{stamp}-clip-{slug}-{n}"
        n += 1
    outdir.mkdir(parents=True, exist_ok=True)
    reel = outdir / "reel.mp4"

    credit = f"Source: {args.source}" if args.source else ""
    with tempfile.TemporaryDirectory() as td:
        src = download(args.url, Path(td) / "source.mp4")
        clipcard.build(src, reel, headline=args.headline, highlight=args.highlight,
                       credit=credit, start=args.start, end=args.end,
                       captions=not args.no_captions)

    caption = args.headline
    if args.note:
        caption += f"\n\n{args.note.strip()}"
    if args.source:
        caption += f"\n\nClip: {args.source}" + (f" ({args.source_url})" if args.source_url else "")
    caption += "\n\nWhat do you think? Tell me below.\n\n#AI #AINews #Tech #TechNews #ArtificialIntelligence"
    print(f"caption:\n{caption}\n")
    if args.dry:
        print(f"[dry run] rendered to {outdir}, nothing pushed or published")
        return

    rel = reel.relative_to(ar.REPO_DIR).as_posix()
    ar.git("fetch", "-q", "--depth=1", "origin", "main")
    ar.git("reset", "-q", "--soft", "FETCH_HEAD")
    ar.git("add", "images")
    ar.git("commit", "-m", f"post {stamp}: clip - {args.headline[:50]}")
    ar.git("push", "-q", "origin", "HEAD:main")
    sha = ar.git_out("rev-parse", "HEAD")
    video_url = f"{ar.CDN_SHA_BASE}{sha}/{rel}"
    print(f"publishing {video_url}")
    result = ar.publish_reel(video_url, caption)
    ar.log("autonomous_post", media_id=result["id"], topic=args.headline[:80], format="reel",
           slides=1, caption=caption, theme="dark", style="clip",
           story_headline=args.headline, story_url=args.source_url, sources_covering=[args.source],
           source_count=1)
    print(f"published, media id {result['id']}")
    ar.post_seed_comment(result["id"], args.headline, caption,
                         fixed="What's your take on this? 👇")


if __name__ == "__main__":
    main()
