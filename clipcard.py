"""Clip reel: a real clip of someone speaking, in the format that is working for news-clip
accounts: headline on top (the speaker's name highlighted), the clip in the middle, big
burned-in captions, a source credit and a small watermark.

The clip is supplied by the operator (a public-domain, licensed or otherwise cleared video);
this module only edits it. It never downloads from social platforms.

    build(src, out, headline=..., highlight="Alex Karp", credit="Source: CNBC", ...)
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageDraw

import make_image as mi

W, H = 1080, 1920
FPS = 24
GOLD = (255, 196, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
ACCENT = (140, 130, 255)          # highlighted names in the headline
VIDEO_TOP = 560                   # where the clip window starts; headline lives above it
CLIP_H = 900                      # clip window height (any source is scaled to fill, centre-cropped)
WATERMARK = "@thealgorithmzedge"
FF = get_ffmpeg_exe()


def probe(path):
    """(width, height, seconds) of a video, via ffmpeg's own banner (no ffprobe shipped)."""
    r = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r)
    secs = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    s = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", r)
    return (int(s[1]), int(s[2]), secs) if s else (0, 0, secs)


def transcribe(audio_path):
    """[(word, start, end)] with Whisper (CPU, int8). [] if unavailable: the reel is then
    posted without captions rather than not at all."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True)
        return [(w.word.strip(), w.start, w.end) for s in segs for w in s.words if w.word.strip()]
    except Exception as e:
        print(f"  [clip] captions unavailable ({e!r:.120})")
        return []


def chunk_words(words, per=3, gap=0.6):
    """Group words into short caption chunks: [(text, start, end)]."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or w[1] - cur[-1][2] > gap):
            out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2]))
            cur = []
        cur.append(w)
    if cur:
        out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][2]))
    # hold each chunk until the next begins (no flicker between words)
    for i in range(len(out) - 1):
        out[i] = (out[i][0], out[i][1], max(out[i][2], min(out[i + 1][1], out[i][2] + 0.4)))
    return out


def _headline_layer(headline, highlight, credit, clip_box):
    """The static layer: headline (highlight words coloured), credit under the clip, watermark."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f, lines = mi.fit(headline, 64, "bold", max_w=W - 120, max_lines=3, min_size=38)
    lh = int(f.size * 1.22)
    hl = [x.lower() for x in (highlight or "").split()]
    y = max(250, VIDEO_TOP - 30 - lh * len(lines))
    for ln in lines:
        x = 60
        for tok in re.findall(r"\S+\s*", ln):
            col = ACCENT if tok.strip(" ,.:;").lower() in hl else WHITE
            d.text((x, y), tok, font=f, fill=col)
            x += f.getlength(tok)
        y += lh
    if credit:
        cf = mi.font(32, "regular")
        d.text((60, clip_box[3] + 24), credit, font=cf, fill=(190, 190, 190))
    wf = mi.font(30, "bold")
    d.text((W - 60 - wf.getlength(WATERMARK), clip_box[3] - 60), WATERMARK, font=wf,
           fill=(255, 255, 255, 150), stroke_width=2, stroke_fill=(0, 0, 0, 150))
    return layer


def _caption_layer(base, text, clip_box):
    layer = base.copy()
    if not text:
        return layer
    d = ImageDraw.Draw(layer)
    f, lines = mi.fit(text, 78, "black", max_w=W - 160, max_lines=2, min_size=50)
    lh = int(f.size * 1.15)
    y = clip_box[3] - 150 - lh * len(lines)
    for ln in lines:
        x = (W - f.getlength(ln)) / 2
        d.text((x, y), ln, font=f, fill=WHITE, stroke_width=8, stroke_fill=BLACK)
        y += lh
    return layer


def build(src, out, headline, highlight="", credit="", start=0.0, end=None, captions=True,
          words=None):
    """Edit `src` into a 1080x1920 reel at `out`. `words` overrides transcription (tests)."""
    src, out = Path(src), Path(out)
    vw, vh, total = probe(src)
    if not vw:
        raise RuntimeError(f"cannot read video: {src}")
    end = min(end or total, total)
    dur = max(1.0, end - start)
    if dur > 90:
        raise RuntimeError(f"clip is {dur:.0f}s; keep clips under 90s")
    box = (0, VIDEO_TOP, W, VIDEO_TOP + CLIP_H)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        wav = td / "a.wav"
        subprocess.run([FF, "-y", "-ss", str(start), "-t", str(dur), "-i", str(src), "-vn",
                        "-ac", "1", "-ar", "16000", str(wav)], capture_output=True, check=True)
        if words is None:
            words = transcribe(wav) if captions else []
        chunks = chunk_words(words)
        base = _headline_layer(headline, highlight, credit, box)
        # one overlay frame per caption state, shown for its duration via the concat demuxer
        lst, t, i = [], 0.0, 0
        timeline = []
        for text, a, b in chunks:
            if a > t + 0.02:
                timeline.append(("", a - t))
            timeline.append((text, max(0.1, b - a)))
            t = b
        if t < dur:
            timeline.append(("", dur - t))
        if not timeline:
            timeline = [("", dur)]
        for text, secs in timeline:
            p = td / f"o{i:04d}.png"
            _caption_layer(base, text, box).save(p)
            lst.append(f"file '{p}'\nduration {secs:.3f}")
            i += 1
        lst.append(f"file '{td / f'o{i - 1:04d}.png'}'")        # concat needs the last file repeated
        (td / "list.txt").write_text("\n".join(lst))
        fc = (f"[0:v]scale={W}:{CLIP_H}:force_original_aspect_ratio=increase,crop={W}:{CLIP_H},setsar=1[v];"
              f"color=c=black:s={W}x{H}:r={FPS}:d={dur}[bg];"
              f"[bg][v]overlay=0:{VIDEO_TOP}:shortest=1[c];"
              f"[1:v]fps={FPS},format=rgba[ov];[c][ov]overlay=0:0:shortest=1[vout];"
              f"[0:a]aresample=48000,loudnorm=I=-14:TP=-1.5:LRA=9[aout]")
        cmd = [FF, "-y", "-ss", str(start), "-t", str(dur), "-i", str(src),
               "-f", "concat", "-safe", "0", "-i", str(td / "list.txt"),
               "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
               "-t", str(dur), "-c:v", "libx264", "-crf", "23", "-preset", "medium",
               "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg failed:\n" + r.stderr[-1500:])
    print(f"  [clip] built {out} ({dur:.1f}s, {len(chunks)} caption chunks)")
    return out
