"""Render 1080x1350 (4:5) carousel slides for Instagram.

Three slide kinds, per 2026 carousel best practice:
  hook    - huge curiosity-gap headline, swipe cue, no body
  content - numbered point, big title, short body (<=20 words)
  cta     - follow/share close

Usage: python make_image.py "Headline" "body" [out.png]   (renders a content slide)
"""

import sys
import textwrap
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


def wrap_text(d, text, f, y, fill, width_chars, line_h, x=72):
    for line in textwrap.wrap(text, width=width_chars):
        d.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y


def render_hook(headline, kicker="", out="slide.png"):
    img, d = base()
    if kicker:
        d.text((72, 300), kicker.upper(), font=font(34, "mono"), fill=ACCENT)
    y = 380
    y = wrap_text(d, headline, font(104, "black"), y, FG, 17, 124)
    d.text((72, H - 250), "swipe", font=font(40, "semibold"), fill=ACCENT)
    d.text((196, H - 254), "———›", font=font(44, "bold"), fill=ACCENT)
    img.save(out)


def render_content(headline, body, idx, total, out="slide.png"):
    img, d = base()
    d.text((72, 240), f"{idx:02d}", font=font(140, "black"), fill=(34, 44, 62))
    d.text((W - 190, 64), f"{idx}/{total}", font=font(34, "mono"), fill=MUTED)
    y = 430
    y = wrap_text(d, headline, font(76, "bold"), y, FG, 22, 94)
    wrap_text(d, body, font(44, "regular"), y + 36, MUTED, 40, 62)
    img.save(out)


def render_cta(headline, body, out="slide.png"):
    img, d = base()
    y = 420
    y = wrap_text(d, headline, font(88, "black"), y, FG, 19, 106)
    y = wrap_text(d, body, font(44, "regular"), y + 36, MUTED, 40, 62)
    d.rounded_rectangle([72, y + 70, 640, y + 190], radius=24, fill=ACCENT)
    d.text((110, y + 100), f"Follow {HANDLE}", font=font(42, "bold"), fill=(8, 12, 18))
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
