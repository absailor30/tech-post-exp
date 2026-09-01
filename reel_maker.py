"""Build an animated 9:16 Reel (MP4) with per-letter text animation.

Every slide's text types itself in — each character fades up and rises on its
own delayed timer (make_image.render_slide_frames) — over a slow Ken Burns
push on the background. Motion in the first second is what holds a viewer;
the previous build showed static cards and drew an 85%+ skip rate.

Frames are rendered with Pillow rather than ffmpeg drawtext so the animation
uses the same fonts and layout as the still slides.

Usage:
  python reel_maker.py <slides_dir> [out.mp4]     # legacy: animate stills
  build_animated(specs, workdir, out)             # used by autonomous_run
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

# Slide duration follows the text instead of being fixed.
#
# The first published reel gave every slide a flat 3.0s, of which 1.65s was
# spent animating the letters in — leaving 1.35s to read up to 20 words. That
# is roughly four times too fast, and an unreadable slide is a skipped slide.
#
# Now: letters land in a fixed ~1.2s regardless of length, then the slide HOLDS
# still while the viewer reads, at a measured reading speed.
FPS = 24            # 24 is plenty for text motion and keeps render time sane
SECS = 3.0          # fallback only (still slideshow path)

REVEAL_SECS = 1.2   # wall-clock time for the letters to finish landing
WPS = 3.2           # words per second a viewer reads on a phone
BUFFER = 1.0        # thinking time after the last word
MIN_SECS = 3.5      # even a 3-word slide needs a beat
MAX_SECS = 7.5      # cap so one dense slide can't stall the reel

# Text is readable as it lands, so the reveal is only about half dead time.
READ_DURING_REVEAL = 0.5


def slide_seconds(spec):
    """How long this slide stays on screen, from its own word count."""
    words = len(f"{spec.get('headline', '')} {spec.get('body', '')}".split())
    secs = REVEAL_SECS * READ_DURING_REVEAL + words / WPS + BUFFER
    return max(MIN_SECS, min(MAX_SECS, secs))
W, H = 1080, 1920
SLIDE_W, SLIDE_H = 1080, 1350
BG = "0x0E1117"


def _encode(frames_dir, n_frames, out):
    """Frame sequence -> H.264 Reel, letterboxed onto a 1080x1920 canvas."""
    from music_maker import pick_track
    track = pick_track()
    dur = n_frames / FPS
    fc = (f"[0:v]pad={W}:{H}:0:(oh-ih)/2:color={BG},setsar=1[v];"
          f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur},"
          f"afade=t=out:st={max(0.1, dur - 1.2)}:d=1.2,volume=0.9[aud]")
    cmd = [get_ffmpeg_exe(), "-y",
           "-framerate", str(FPS), "-i", str(Path(frames_dir) / "f%05d.png"),
           "-i", str(track),
           "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
           "-c:v", "libx264", "-crf", "24", "-preset", "medium",
           "-c:a", "aac", "-shortest",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr.decode('utf-8', 'replace')[-2000:]}")
    return out


def build_animated(specs, out="reel.mp4", workdir=None):
    """specs: list of slide dicts (kind/headline/body/idx/total) in order."""
    from make_image import render_slide_frames

    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="reelframes"))
    tmp.mkdir(parents=True, exist_ok=True)
    idx = 0
    for spec in specs:
        secs = slide_seconds(spec)
        n = int(secs * FPS)
        # Letters always land in REVEAL_SECS, so a longer slide simply holds
        # still for longer rather than animating more slowly.
        idx += render_slide_frames(spec, tmp, n, idx, reveal=REVEAL_SECS / secs)
        print(f"  slide {spec['kind']:7} {secs:4.1f}s "
              f"(read {secs - REVEAL_SECS:.1f}s)")
    print(f"rendered {idx} animated frames ({len(specs)} slides, {idx / FPS:.1f}s)")
    try:
        _encode(tmp, idx, out)
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"built {out}")
    return out


def build(slides_dir, out="reel.mp4"):
    """Legacy path: animate whatever still slides are on disk.

    Reads slides.json (written alongside the PNGs) so the text can be
    re-animated; falls back to a still slideshow if it is missing.
    """
    slides_dir = Path(slides_dir)
    meta = slides_dir / "slides.json"
    if meta.exists():
        return build_animated(json.loads(meta.read_text(encoding="utf-8")), out)
    return _still_slideshow(slides_dir, out)


def _still_slideshow(slides_dir, out):
    slides = sorted(Path(slides_dir).glob("slide*.png"),
                    key=lambda p: int("".join(filter(str.isdigit, p.stem))))
    if not slides:
        sys.exit(f"no slides in {slides_dir}")
    frames = int(SECS * FPS)
    inputs, chains = [], []
    for i, s in enumerate(slides):
        inputs += ["-loop", "1", "-t", str(SECS), "-i", str(s)]
        chains.append(
            f"[{i}:v]scale=2160:-1,zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)'"
            f":y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{SLIDE_H}:fps={FPS},"
            f"pad={W}:{H}:0:(oh-ih)/2:color={BG},setsar=1[v{i}]")
    concat = "".join(f"[v{i}]" for i in range(len(slides)))
    fc = ";".join(chains) + f";{concat}concat=n={len(slides)}:v=1:a=0[out]"
    from music_maker import pick_track
    track = pick_track()
    dur = len(slides) * SECS
    fc += (f";[{len(slides)}:a]aloop=loop=-1:size=2e9,atrim=0:{dur},"
           f"afade=t=out:st={dur - 1.2}:d=1.2,volume=0.9[aud]")
    cmd = [get_ffmpeg_exe(), "-y", *inputs, "-i", str(track),
           "-filter_complex", fc, "-map", "[out]", "-map", "[aud]",
           "-c:v", "libx264", "-crf", "26", "-preset", "fast",
           "-c:a", "aac", "-shortest",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"built {out} ({len(slides)} still slides)")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    build(a[0], a[1] if len(a) > 1 else "reel.mp4")
