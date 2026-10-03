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
                    # (content and CTA slides only — see HOOK_REVEAL_SECS)

# Watch-time data (20 posts, once reach and reels.avg_watch_time started
# being tracked) showed a strong split: posts that stayed within the
# account's ~7 followers finished 31% of the video on average; posts that
# Instagram actually pushed to new people finished only 8% — and for 3 of
# the 4 highest-reach posts, average watch time was SHORTER than the hook
# slide's own reveal (3.8-4.1s at the old REVEAL_SECS). Cold viewers were
# leaving before the headline even finished animating in, which is exactly
# the signal that stops Reels from expanding distribution further.
#
# The hook is the one slide a stranger has to be caught by before anything
# else about the post matters, so it gets its own much faster reveal — the
# full headline is legible almost immediately instead of over ~1.2s.
# Content/CTA slides keep the slower reveal; that pacing wasn't implicated
# and is what's giving committed viewers time to actually read.
HOOK_REVEAL_SECS = 0.35

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
BG = "0xF5EEE0"   # fallback; the real value comes from the active theme


MUSIC_VOL = 0.9          # music alone (no voiceover)
# With a voiceover the mix is set by measured loudness, not guessed gains:
VOICE_LUFS = -15         # narration: loud and clear, with headroom for AAC
MUSIC_LUFS = -32         # music bed: ~17 LU under the voice, audible but never competing
DUCK_THRESHOLD = 0.02    # sidechain: music dips further whenever the narrator speaks


def audio_graph(voice, dur, music_idx=1, first_voice_idx=2):
    """ffmpeg filtergraph text producing [aud] from one music input and N voice clips."""
    g = (f"[{music_idx}:a]aloop=loop=-1:size=2e9,atrim=0:{dur},"
         f"afade=t=out:st={max(0.1, dur - 1.2)}:d=1.2")
    if not voice:
        return g + f",volume={MUSIC_VOL}[aud]"
    g += f",loudnorm=I={MUSIC_LUFS}:TP=-8:LRA=11[music]"
    labels = ""
    for i, (_clip, start) in enumerate(voice):
        ms = int(start * 1000)
        g += f";[{first_voice_idx + i}:a]adelay={ms}|{ms}[vo{i}]"
        labels += f"[vo{i}]"
    g += (f";{labels}amix=inputs={len(voice)}:normalize=0,highpass=f=80,"
          f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=7,asplit=2[vo][vosc]"
          f";[music][vosc]sidechaincompress=threshold={DUCK_THRESHOLD}:ratio=6:"
          f"attack=15:release=300[musicd]"
          f";[vo][musicd]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[aud]")
    return g


def _encode(frames_dir, n_frames, out, bg=BG, voice=None, pattern="f%05d.png"):
    """Frame sequence -> H.264 Reel, letterboxed onto a 1080x1920 canvas.

    voice: optional list of (audio_path, start_seconds) narration clips.
    """
    from music_maker import pick_track
    track = pick_track()
    dur = n_frames / FPS
    fc = (f"[0:v]pad={W}:{H}:0:(oh-ih)/2:color={bg},setsar=1[v];"
          + audio_graph(voice, dur))
    voice_inputs = []
    for clip, _start in (voice or []):
        voice_inputs += ["-i", str(clip)]
    cmd = [get_ffmpeg_exe(), "-y",
           "-framerate", str(FPS), "-i", str(Path(frames_dir) / pattern),
           "-i", str(track), *voice_inputs,
           "-filter_complex", fc, "-map", "[v]", "-map", "[aud]",
           "-c:v", "libx264", "-crf", "24", "-preset", "medium",
           "-c:a", "aac", "-b:a", "160k", "-shortest",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr.decode('utf-8', 'replace')[-2000:]}")
    return out


VOICE_LEAD = 0.08   # narration starts right as the scene appears
VOICE_PAD = 0.12    # tiny hold after the last word; the story keeps moving


def _narrate(specs, tmp):
    """[(clip_path, seconds)] per slide, or None if any slide fails."""
    from voiceover import duration, narration_text, synth
    clips = []
    for i, spec in enumerate(specs):
        path = synth(narration_text(spec), Path(tmp) / f"vo{i}")
        if not path:
            print("  [voiceover] unavailable, building music-only reel")
            return None
        clips.append((path, duration(path)))
    print(f"  [voiceover] {len(clips)} clips, "
          f"{sum(c[1] for c in clips):.1f}s of speech")
    return clips


def build_animated(specs, out="reel.mp4", workdir=None, theme=None,
                   narrate=True):
    """specs: list of slide dicts (kind/headline/body/idx/total) in order."""
    from make_image import THEMES, render_slide_frames, set_theme
    if theme:
        set_theme(theme)
    # Letterbox bars must match the page or the reel gets visible edges.
    bg = THEMES[__import__("make_image").THEME]["LETTERBOX"]

    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="reelframes"))
    tmp.mkdir(parents=True, exist_ok=True)
    # Narration first: slide length must cover the spoken audio. All-or-nothing
    # — if any slide's TTS fails the reel ships music-only, as before.
    clips = _narrate(specs, tmp) if narrate else None
    idx = 0
    voice = []
    for i, spec in enumerate(specs):
        secs = slide_seconds(spec)
        if clips:
            secs = max(secs, clips[i][1] + VOICE_PAD)
            voice.append((clips[i][0], idx / FPS + VOICE_LEAD))
        n = int(secs * FPS)
        reveal_secs = HOOK_REVEAL_SECS if spec["kind"] == "hook" else REVEAL_SECS
        # Letters always land in reveal_secs, so a longer slide simply holds
        # still for longer rather than animating more slowly.
        idx += render_slide_frames(spec, tmp, n, idx, reveal=reveal_secs / secs)
        print(f"  slide {spec['kind']:7} {secs:4.1f}s "
              f"(read {secs - reveal_secs:.1f}s, reveal {reveal_secs:.2f}s)")
    print(f"rendered {idx} animated frames ({len(specs)} slides, {idx / FPS:.1f}s)")
    try:
        _encode(tmp, idx, out, bg, voice or None)
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
        data = json.loads(meta.read_text(encoding="utf-8"))
        if isinstance(data, dict):          # newer form carries the theme
            return build_animated(data["slides"], out, theme=data.get("theme"))
        return build_animated(data, out)
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
