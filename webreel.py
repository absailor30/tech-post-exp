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


def overlay(frame, spec, alpha):
    """Caption layer for one scene. alpha 0..1 fades the whole layer in.

    Safe zone: Instagram covers roughly the bottom 20% (caption/audio row) and a
    ~130px strip on the right (like/comment/share), so captions stay clear of
    both. The hook sits low so the page header (name, description, stars) stays
    visible as the evidence.
    """
    img = frame.convert("RGBA")
    left, right, bottom = 48, W - 130, H - 380
    inner = right - left - 80          # text width inside a panel
    kind = spec["kind"]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))

    def chip(d, text, y):
        f = mi.font(40, "black")
        w = int(f.getlength(text)) + 56
        d.rounded_rectangle((left, y, left + w, y + 76), radius=38, fill=GOLD)
        d.text((left + 28, y + 14), text, font=f, fill=(20, 20, 20))

    def panel_with(lines_specs, top, bottom_, chip_text=None):
        nonlocal layer
        layer = _panel(layer, (left, top, right, bottom_))
        d = ImageDraw.Draw(layer)
        if chip_text:
            chip(d, chip_text, top - 92)
        y = top + 40
        for lines, f, lh, fill, gap in lines_specs:
            y = _draw_lines(d, lines, f, left + 40, y, fill, lh) + gap

    if kind == "hook":
        f, lines = mi.fit(spec["headline"], 104, "black", max_w=inner, max_lines=4, min_size=60)
        lh = int(f.size * 1.15)
        box_h = lh * len(lines) + 80
        specs_ = []
        if spec.get("repo"):
            fr = mi.font(40, "mono")
            specs_.append(([spec["repo"]], fr, 56, GOLD, 8))
            box_h += 64
        specs_.append((lines, f, lh, (255, 255, 255), 0))
        panel_with(specs_, bottom - box_h, bottom, spec.get("kicker", "").upper() or None)
    elif kind == "cta":
        f, lines = mi.fit(spec["headline"], 96, "black", max_w=inner, max_lines=3, min_size=60)
        fb, blines = mi.fit(spec.get("body", ""), 46, "regular", max_w=inner, max_lines=3, min_size=34)
        lh, blh = int(f.size * 1.15), int(fb.size * 1.3)
        box_h = lh * len(lines) + blh * len(blines) + 100
        panel_with([(lines, f, lh, GOLD, 14), (blines, fb, blh, (255, 255, 255), 0)],
                   bottom - box_h, bottom)
    else:
        f, lines = mi.fit(spec["headline"], 68, "black", max_w=inner, max_lines=3, min_size=44)
        fb, blines = mi.fit(spec.get("body", ""), 44, "regular", max_w=inner, max_lines=5, min_size=32)
        lh, blh = int(f.size * 1.15), int(fb.size * 1.3)
        box_h = lh * len(lines) + blh * len(blines) + 96
        chip_text = f"{spec['idx'] - 1} / {spec['total'] - 2}" if spec.get("idx") else None
        panel_with([(lines, f, lh, GOLD, 12), (blines, fb, blh, (255, 255, 255), 0)],
                   bottom - box_h, bottom, chip_text)

    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    return Image.alpha_composite(img, layer).convert("RGB")


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
        n = int(secs * rm.FPS)
        counts.append(n)
        idx += n
    total = idx

    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=2)
        resp = page.goto(url, wait_until="networkidle", timeout=45000)
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
                fa = min(1.0, (k / rm.FPS) / FADE_SECS)
                frame = overlay(shot, spec, fa)
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
