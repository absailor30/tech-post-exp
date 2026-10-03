"""Real-video reel: a headless-Chrome scroll through a live web page (the repo's
GitHub page) with captions on top, narrated by the same voiceover as before.

Why: slides-with-text reels were not holding cold viewers. This gives actual
motion that is also the evidence for the claim being made (the real page).

Frames are captured one by one at a controlled scroll position (frame-exact,
no recording artefacts) at 540x960 CSS px, device scale 2 => 1080x1920.
"""

import glob
import io
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import make_image as mi
import reel_maker as rm

W, H = 1080, 1920
VIEW_W, VIEW_H = 540, 960           # CSS px; mobile layout reads large on a phone
SCROLL_CAP = 2600                   # CSS px: never scroll deeper than the README top
FADE_SECS = 0.25
GOLD = (255, 196, 0)
PANEL = (10, 12, 16, 242)


def _launch(p):
    """System Chrome (preinstalled on GitHub runners), else Playwright's Chromium,
    downloading it if neither exists."""
    try:
        return p.chromium.launch(channel="chrome")
    except Exception as e:
        print(f"  [webreel] system Chrome unavailable ({str(e)[:80]!r}), trying Chromium")
    local = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    if local:
        return p.chromium.launch(executable_path=local[0])
    try:
        return p.chromium.launch()
    except Exception:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return p.chromium.launch()


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _panel(img, box, radius=36, fill=PANEL):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle(box, radius=radius, fill=fill)
    return Image.alpha_composite(img, ov)


def _draw_lines(d, lines, f, x, y, fill, line_h):
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill)
        y += line_h
    return y


BLACK = (0, 0, 0)


def chunk_words(text, max_words=5):
    """Split spoken text into short subtitle chunks at punctuation, <= max_words each."""
    import re
    out = []
    for part in re.split(r"(?<=[.,;:?!…])\s+|\.\.\.\s*", (text or "").strip()):
        words = part.split()
        for i in range(0, len(words), max_words):
            c = " ".join(words[i:i + max_words]).strip()
            if c:
                out.append(c)
    # merge a 1-word tail into the previous chunk so nothing flashes by
    merged = []
    for c in out:
        if merged and len(c.split()) == 1 and len(merged[-1].split()) < max_words + 1:
            merged[-1] += " " + c
        else:
            merged.append(c)
    return merged


def chunk_at(chunks, t, lead, dur):
    """Which chunk is on screen at scene-time t (seconds); time is shared by length."""
    if not chunks:
        return ""
    if t < lead:
        return chunks[0]
    weights = [max(3, len(c)) for c in chunks]
    x = (t - lead) / max(0.05, dur) * sum(weights)
    acc = 0
    for c, w in zip(chunks, weights):
        acc += w
        if x < acc:
            return c
    return chunks[-1]


def _outlined(d, xy, text, f, fill=GOLD, stroke=7):
    d.text(xy, text, font=f, fill=fill, stroke_width=stroke, stroke_fill=BLACK)


def subtitle(frame, text, label=""):
    """Gold text with a black outline, centred, max 2 lines, no background box.
    Sits above Instagram's bottom UI and clear of the right-hand buttons."""
    img = frame.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    left, right, bottom = 70, W - 140, H - 470
    inner = right - left
    if text:
        f, lines = mi.fit(text, 66, "black", max_w=inner, max_lines=2, min_size=46)
        lh = int(f.size * 1.18)
        y = bottom - lh * len(lines)
        for ln in lines:
            w = d.textlength(ln, font=f)
            _outlined(d, (left + (inner - w) / 2, y), ln, f)
            y += lh
    if label:
        fl = mi.font(34, "black")
        _outlined(d, (60, 150), label.upper(), fl, stroke=5)
    return Image.alpha_composite(img, layer).convert("RGB")


PRESENTER = Path(__file__).parent / "assets" / "presenter.jpg"
FACE_D = 270                        # px diameter of the presenter window
_face = None


def presenter(frame, t, speaking):
    """Small round presenter window, top-right, below Instagram's header.
    A still photo with gentle motion (breathing, sway, nods while speaking); no lip sync."""
    global _face
    import math
    if _face is None:
        if not PRESENTER.exists():
            return frame
        _face = Image.open(PRESENTER).convert("RGB")
    amp = 1.0 if speaking else 0.35
    sway = math.sin(t * 1.7) * 1.6 * amp                       # degrees
    nod = (math.sin(t * 5.2) * 0.5 + 0.5) ** 3 * 9 * amp if speaking else 0
    zoom = 1.06 + 0.015 * math.sin(t * 2.1) + (0.012 if speaking else 0)
    S = FACE_D * 3                                              # supersample for smooth edge
    src = _face.resize((int(S * zoom), int(S * zoom)))
    src = src.rotate(sway, resample=Image.BICUBIC)
    ox, oy = (src.width - S) // 2, (src.height - S) // 2 - int(nod * 3)
    tile = src.crop((ox, oy, ox + S, oy + S))
    ring = 24
    big = Image.new("RGBA", (S + 2 * ring, S + 2 * ring), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((0, 0, big.width - 1, big.height - 1), fill=(0, 0, 0, 255))
    d.ellipse((8, 8, big.width - 9, big.height - 9), fill=GOLD + (255,))
    d.ellipse((ring - 6, ring - 6, big.width - ring + 5, big.height - ring + 5), fill=(0, 0, 0, 255))
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, S - 1, S - 1), fill=255)
    big.paste(tile, (ring, ring), mask)
    out_d = FACE_D + 2 * ring // 3
    small = big.resize((out_d, out_d), Image.LANCZOS)
    bob = int(math.sin(t * 2.3) * 4 * amp)
    img = frame.convert("RGBA")
    img.alpha_composite(small, (W - out_d - 50, 210 + bob))
    return img.convert("RGB")


def overlay(frame, spec, alpha, t=0.0, scene_dur=1.0):
    """Subtitle layer for one frame of one scene (t = seconds into the scene)."""
    frame = _overlay_text(frame, spec, t, scene_dur)
    speaking = bool(spec.get("say")) and rm.VOICE_LEAD <= t <= rm.VOICE_LEAD + spec.get("_dur", scene_dur)
    return presenter(frame, spec.get("_clock", 0.0) + t, speaking)


def _overlay_text(frame, spec, t=0.0, scene_dur=1.0):
    label = spec.get("kicker", "") if spec["kind"] == "hook" else ""
    if spec.get("say"):
        chunks = spec.get("_chunks") or chunk_words(spec["say"])
        spec["_chunks"] = chunks
        text = chunk_at(chunks, t, rm.VOICE_LEAD, spec.get("_dur", scene_dur - rm.VOICE_LEAD))
        return subtitle(frame, text, label)
    # no spoken script (news-style specs): show the headline only, still outlined
    return subtitle(frame, spec.get("headline", ""), label)


def build_web_reel(specs, url, out="reel.mp4", workdir=None, narrate=True, scroll_cap=SCROLL_CAP):
    """specs: slide dicts (kind/headline/body/kicker/idx/total) in order."""
    from playwright.sync_api import sync_playwright
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="webreel"))
    tmp.mkdir(parents=True, exist_ok=True)

    clips = rm._narrate(specs, tmp) if narrate else None
    counts, voice, idx = [], [], 0
    for i, spec in enumerate(specs):
        secs = rm.slide_seconds(spec)
        if clips:
            if spec.get("say"):        # a spoken script drives the pace, not the on-screen words
                secs = max(2.5, clips[i][1] + rm.VOICE_PAD)
            else:
                secs = max(secs, clips[i][1] + rm.VOICE_PAD)
            voice.append((clips[i][0], idx / rm.FPS + rm.VOICE_LEAD))
            spec["_dur"] = clips[i][1]                 # subtitle timing follows the audio
        n = int(secs * rm.FPS)
        spec["_clock"] = idx / rm.FPS
        counts.append(n)
        idx += n
    total = idx

    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=2)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)   # GitHub sometimes never idles
        except Exception:
            pass
        if resp is None or resp.status >= 400:
            raise RuntimeError(f"web capture failed: {url} returned "
                               f"{getattr(resp, 'status', 'no response')}")
        title = (page.title() or "").lower()
        if any(bad in title for bad in ("page not found", "rate limit", "too many requests",
                                        "access denied", "just a moment")):
            raise RuntimeError(f"web capture hit an error page: {page.title()!r}")
        page.wait_for_timeout(1200)
        page_h = page.evaluate("document.documentElement.scrollHeight")
        # Open on the README (logo + description), not the file tree above it.
        readme_y = page.evaluate(
            "(()=>{const r=document.querySelector('#readme, article.markdown-body');"
            "return r ? r.getBoundingClientRect().top + window.scrollY : 0})()")
        start_y = max(0, int(readme_y) - 150)
        max_y = max(start_y, min(page_h - VIEW_H, start_y + scroll_cap))
        print(f"  [webreel] {url} height={page_h}px, readme at {readme_y:.0f}px, "
              f"scrolling {start_y}->{max_y}px over {total / rm.FPS:.1f}s")

        n_scenes = len(specs)
        frame_no = 0
        for si, (spec, n) in enumerate(zip(specs, counts)):
            # hook: hold on the page header; content scenes: ease down; CTA: hold
            span = max_y - start_y
            y0 = start_y if si == 0 else start_y + span * ((si - 1) / max(1, n_scenes - 2)) * 0.98
            y1 = start_y if si == 0 else start_y + span * (si / max(1, n_scenes - 2)) * 0.98
            if spec["kind"] == "cta":
                y0 = y1 = start_y + span * 0.98
            for k in range(n):
                t = k / max(1, n - 1)
                y = y0 + (y1 - y0) * _smooth(min(1.0, t * 1.15))
                page.evaluate(f"window.scrollTo(0,{y:.1f})")
                shot = Image.open(io.BytesIO(page.screenshot(type="jpeg", quality=92)))
                frame = overlay(shot, spec, 1.0, t=k / rm.FPS, scene_dur=n / rm.FPS)
                frame.save(tmp / f"f{frame_no + 1:05d}.jpg", quality=92)
                frame_no += 1
        browser.close()
    print(f"  [webreel] captured {frame_no} frames ({total / rm.FPS:.1f}s)")
    try:
        rm._encode(tmp, frame_no, out, "0x0A0C10", voice or None, pattern="f%05d.jpg")
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"built {out}")
    return out
