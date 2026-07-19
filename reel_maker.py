"""Build an animated 9:16 Reel (MP4) from a directory of slide PNGs.

Each slide gets ~2.6s with a slow Ken Burns zoom; slides are letterboxed
onto a 1080x1920 dark canvas. H.264 + yuv420p per Reels specs. Silent track
(trending audio can't be licensed via API anyway).

Usage: python reel_maker.py <slides_dir> [out.mp4]
"""

import subprocess
import sys
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

SECS = 2.6
FPS = 30
W, H = 1080, 1920
BG = "0x0E1117"


def build(slides_dir, out="reel.mp4"):
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
            f":y='ih/2-(ih/zoom/2)':d={frames}:s={W}x1350:fps={FPS},"
            f"pad={W}:{H}:0:(oh-ih)/2:color={BG},setsar=1[v{i}]")
    concat = "".join(f"[v{i}]" for i in range(len(slides)))
    fc = ";".join(chains) + f";{concat}concat=n={len(slides)}:v=1:a=0[out]"
    n_aud = len(slides)
    from music_maker import pick_track
    track = pick_track()
    dur = len(slides) * SECS
    fc += (f";[{n_aud}:a]aloop=loop=-1:size=2e9,atrim=0:{dur},"
           f"afade=t=out:st={dur - 1.2}:d=1.2,volume=0.9[aud]")
    cmd = [get_ffmpeg_exe(), "-y", *inputs, "-i", str(track),
           "-filter_complex", fc,
           "-map", "[out]", "-map", "[aud]",
           "-c:v", "libx264", "-crf", "26", "-preset", "fast",
           "-c:a", "aac", "-shortest",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"built {out} ({len(slides)} slides, {len(slides) * SECS:.0f}s)")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    build(a[0], a[1] if len(a) > 1 else "reel.mp4")
