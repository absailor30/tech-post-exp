"""Render 1080x1350 (4:5) carousel slides for Instagram.

Three slide kinds, per 2026 carousel best practice:
  hook    - huge curiosity-gap headline, swipe cue, no body
  content - numbered point, big title, short body (<=20 words)
  cta     - follow/share close

Usage: python make_image.py "Headline" "body" [out.png]   (renders a content slide)
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
BG_TOP = (10, 13, 20)
BG_BOT = (16, 22, 34)
ACCENT = (0, 229, 160)
FG = (240, 243, 248)
MUTED = (148, 158, 175)
HANDLE = "@thealgorithmzedge"
BRAND = "THE ALGORITHMZ EDGE"


DEJAVU = "/usr/share/fonts/truetype/dejavu"


def font(size, weight="regular"):
    names = {"black": ["seguibl.ttf", "arialbd.ttf", f"{DEJAVU}/DejaVuSans-Bold.ttf"],
             "bold": ["segoeuib.ttf", "arialbd.ttf", f"{DEJAVU}/DejaVuSans-Bold.ttf"],
             "semibold": ["seguisb.ttf", "arialbd.ttf", f"{DEJAVU}/DejaVuSans-Bold.ttf"],
             "regular": ["segoeui.ttf", "arial.ttf", f"{DEJAVU}/DejaVuSans.ttf"],
             "mono": ["consolab.ttf", "consola.ttf", f"{DEJAVU}/DejaVuSansMono-Bold.ttf"]}[weight]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def base():
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):                      # vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(
            int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    for gx in range(60, W, 120):            # subtle dot grid
        for gy in range(60, H, 120):
            d.ellipse([gx - 2, gy - 2, gx + 2, gy + 2], fill=(28, 34, 48))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 420, -260, W + 260, 420], fill=(0, 60, 42))
    img = Image.blend(img, Image.composite(glow, img, Image.new("L", (W, H), 255)).filter(
        ImageFilter.GaussianBlur(160)), 0.55)
    d = ImageDraw.Draw(img)
    d.rectangle([(0, 0), (W, 10)], fill=ACCENT)
    d.text((72, 58), BRAND, font=font(30, "mono"), fill=ACCENT)
    d.text((72, H - 96), HANDLE, font=font(32, "semibold"), fill=MUTED)
    return img, d


MARGIN = 72
MAX_W = W - MARGIN * 2


def wrap_px(text, f, max_w=MAX_W):
    """Wrap on measured pixel width, not character count.

    Character-count wrapping silently overflowed the canvas whenever a line
    ran wide — "OpenAI just made" at 104px is 1116px on a 1080px slide, so
    the last letters were sliced off the edge. Product and model names are
    exactly the wide, capitalised words this account now has to render.
    """
    lines, cur = [], ""
    words = []
    for w in (text or "").split():
        # A single word wider than the canvas (a long URL or model id) can
        # never wrap on spaces — split it hard so it cannot run off the edge.
        while f.getlength(w) > max_w and len(w) > 1:
            cut = len(w)
            while cut > 1 and f.getlength(w[:cut]) > max_w:
                cut -= 1
            words.append(w[:cut])
            w = w[cut:]
        words.append(w)
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and f.getlength(trial) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def fit(text, size, weight, max_w=MAX_W, max_lines=4, min_size=44):
    """Largest font at which the text wraps into max_lines and stays in frame."""
    while size > min_size:
        f = font(size, weight)
        lines = wrap_px(text, f, max_w)
        if len(lines) <= max_lines and all(f.getlength(l) <= max_w for l in lines):
            return f, lines
        size -= 4
    f = font(min_size, weight)
    return f, wrap_px(text, f, max_w)


def wrap_text(d, text, f, y, fill, width_chars, line_h, x=MARGIN):
    """width_chars is kept for call-site compatibility; wrapping is by pixel."""
    for line in wrap_px(text, f):
        d.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y


def render_hook(headline, kicker="", out="slide.png"):
    img, d = base()
    if kicker:
        d.text((72, 300), kicker.upper(), font=font(34, "mono"), fill=ACCENT)
    f, lines = fit(headline, 104, "black", max_lines=4)
    y = 380
    for line in lines:
        d.text((MARGIN, y), line, font=f, fill=FG)
        y += int(f.size * 1.19)
    d.text((72, H - 250), "swipe", font=font(40, "semibold"), fill=ACCENT)
    d.text((196, H - 254), "———›", font=font(44, "bold"), fill=ACCENT)
    img.save(out)


def render_content(headline, body, idx, total, out="slide.png"):
    img, d = base()
    d.text((72, 240), f"{idx:02d}", font=font(140, "black"), fill=(34, 44, 62))
    d.text((W - 190, 64), f"{idx}/{total}", font=font(34, "mono"), fill=MUTED)
    hf, hlines = fit(headline, 76, "bold", max_lines=3)
    y = 430
    for line in hlines:
        d.text((MARGIN, y), line, font=hf, fill=FG)
        y += int(hf.size * 1.24)
    bf, blines = fit(body, 44, "regular", max_lines=6, min_size=32)
    y += 36
    for line in blines:
        d.text((MARGIN, y), line, font=bf, fill=MUTED)
        y += int(bf.size * 1.41)
    img.save(out)


def render_cta(headline, body, out="slide.png"):
    img, d = base()
    hf, hlines = fit(headline, 88, "black", max_lines=3)
    y = 420
    for line in hlines:
        d.text((MARGIN, y), line, font=hf, fill=FG)
        y += int(hf.size * 1.20)
    bf, blines = fit(body, 44, "regular", max_lines=5, min_size=32)
    y += 36
    for line in blines:
        d.text((MARGIN, y), line, font=bf, fill=MUTED)
        y += int(bf.size * 1.41)
    # Button is sized to its label — a fixed 640px pill clipped the handle.
    label, bf = f"Follow {HANDLE}", font(42, "bold")
    bw = bf.getlength(label)
    d.rounded_rectangle([MARGIN, y + 70, MARGIN + bw + 76, y + 190],
                        radius=24, fill=ACCENT)
    d.text((MARGIN + 38, y + 100), label, font=bf, fill=(8, 12, 18))
    img.save(out)


def render(headline, body, out="post.png"):
    """Back-compat single-card render (content style, unnumbered)."""
    img, d = base()
    y = 380
    y = wrap_text(d, headline, font(88, "black"), y, FG, 19, 106)
    wrap_text(d, body, font(44, "regular"), y + 40, MUTED, 40, 62)
    img.save(out)
    print(f"saved {Path(out).resolve()}")


if __name__ == "__main__":
    a = sys.argv[1:]
    render(a[0], a[1], a[2] if len(a) > 2 else "post.png")


# ---------------------------------------------------------------- animation
#
# Per-letter animation, as the owner asked for on 2026-08-31. Each character
# fades up and rises into place on its own slightly delayed timer, so the
# headline types itself in rather than appearing as a static block. Motion in
# the first second is what stops the thumb; a still slide is what produced the
# 85% skip rate.

_BASE_CACHE = None
REVEAL = 0.55        # fraction of a slide's time spent revealing letters
CHAR_WINDOW = 0.30   # each letter's own fade, as a fraction of the reveal


def base_cached():
    """The gradient/glow/grid background is expensive and identical on every
    frame — build it once per process."""
    global _BASE_CACHE
    if _BASE_CACHE is None:
        _BASE_CACHE = base()[0]
    return _BASE_CACHE.copy()


def _char_alpha(i, n, progress):
    """Alpha and vertical offset for character i at this point in the reveal."""
    if n <= 0:
        return 1.0, 0.0
    p = min(1.0, max(0.0, progress / REVEAL)) if REVEAL else 1.0
    start = (i / n) * (1.0 - CHAR_WINDOW)
    a = (p - start) / CHAR_WINDOW if CHAR_WINDOW else 1.0
    a = min(1.0, max(0.0, a))
    ease = a * a * (3 - 2 * a)              # smoothstep
    return ease, (1.0 - ease) * 22.0        # rise 22px into place


def draw_letters(img, lines, f, x, y, fill, line_h, progress,
                 offset=0, total=None):
    """Draw pre-wrapped text one character at a time onto an RGBA overlay.

    Returns (next_y, characters_drawn) so several blocks can share one
    animation timeline.
    """
    n = total if total is not None else sum(len(l) for l in lines)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    idx = offset
    for line in lines:
        cx = x
        for ch in line:
            a, dy = _char_alpha(idx, n, progress)
            if a > 0.01 and ch != " ":
                d.text((cx, y + dy), ch, font=f, fill=(*fill, int(255 * a)))
            cx += f.getlength(ch)
            idx += 1
        y += line_h
    img.alpha_composite(layer)
    return y, idx - offset


def frame_hook(headline, kicker, progress):
    img = base_cached().convert("RGBA")
    d = ImageDraw.Draw(img)
    if kicker:
        d.text((72, 300), kicker.upper(), font=font(34, "mono"), fill=ACCENT)
    f, lines = fit(headline, 104, "black", max_lines=4)
    draw_letters(img, lines, f, MARGIN, 380, FG, int(f.size * 1.19), progress)
    if progress > 0.75:                      # swipe cue only once the hook lands
        a = min(1.0, (progress - 0.75) / 0.2)
        cue = Image.new("RGBA", img.size, (0, 0, 0, 0))
        cd = ImageDraw.Draw(cue)
        cd.text((72, H - 250), "swipe", font=font(40, "semibold"),
                fill=(*ACCENT, int(255 * a)))
        cd.text((196, H - 254), "———›", font=font(44, "bold"),
                fill=(*ACCENT, int(255 * a)))
        img.alpha_composite(cue)
    return img.convert("RGB")


def frame_content(headline, body, idx, total, progress):
    img = base_cached().convert("RGBA")
    d = ImageDraw.Draw(img)
    d.text((72, 240), f"{idx:02d}", font=font(140, "black"), fill=(34, 44, 62))
    d.text((W - 190, 64), f"{idx}/{total}", font=font(34, "mono"), fill=MUTED)
    head_f, hlines = fit(headline, 76, "bold", max_lines=3)
    body_f, blines = fit(body, 44, "regular", max_lines=6, min_size=32)
    n = sum(len(l) for l in hlines) + sum(len(l) for l in blines)
    y, drawn = draw_letters(img, hlines, head_f, MARGIN, 430, FG,
                            int(head_f.size * 1.24), progress, 0, n)
    draw_letters(img, blines, body_f, MARGIN, y + 36, MUTED,
                 int(body_f.size * 1.41), progress, drawn, n)
    return img.convert("RGB")


def frame_cta(headline, body, progress):
    img = base_cached().convert("RGBA")
    head_f, hlines = fit(headline, 88, "black", max_lines=3)
    body_f, blines = fit(body, 44, "regular", max_lines=5, min_size=32)
    n = sum(len(l) for l in hlines) + sum(len(l) for l in blines)
    y, drawn = draw_letters(img, hlines, head_f, MARGIN, 420, FG,
                            int(head_f.size * 1.20), progress, 0, n)
    y, _ = draw_letters(img, blines, body_f, MARGIN, y + 36, MUTED,
                        int(body_f.size * 1.41), progress, drawn, n)
    if progress > 0.7:
        a = min(1.0, (progress - 0.7) / 0.25)
        btn = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(btn)
        label, bf = f"Follow {HANDLE}", font(42, "bold")
        bw = bf.getlength(label)
        bd.rounded_rectangle([MARGIN, y + 70, MARGIN + bw + 76, y + 190],
                             radius=24, fill=(*ACCENT, int(255 * a)))
        bd.text((MARGIN + 38, y + 100), label, font=bf,
                fill=(8, 12, 18, int(255 * a)))
        img.alpha_composite(btn)
    return img.convert("RGB")


def render_slide_frames(spec, outdir, n_frames, start_index):
    """Write n_frames PNGs for one slide. Once every letter has landed the
    image stops changing, so later frames are byte-copies of the first
    settled one instead of being re-rendered."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    settled = None
    written = 0
    for i in range(n_frames):
        progress = (i + 1) / n_frames
        path = outdir / f"f{start_index + i:05d}.png"
        if settled is not None:
            path.write_bytes(settled)
            written += 1
            continue
        kind = spec["kind"]
        if kind == "hook":
            img = frame_hook(spec["headline"], spec.get("kicker", ""), progress)
        elif kind == "cta":
            img = frame_cta(spec["headline"], spec["body"], progress)
        else:
            img = frame_content(spec["headline"], spec["body"], spec["idx"],
                                spec["total"], progress)
        img.save(path)
        written += 1
        if progress >= 0.96:
            settled = path.read_bytes()
    return written
