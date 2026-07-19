"""Synthesize original lo-fi/synthwave loops for Reels. Zero licensing risk.

Generates layered tracks: warm pad chords, sub bass, soft kick, vinyl-ish
noise hats. Each variant uses a different key/progression/tempo so posts
don't all sound identical. If music/*.mp3 files exist (user-supplied
royalty-free tracks), pick_track() prefers those instead.

Usage: python music_maker.py     (renders music/gen_*.wav variants)
"""

import random
import wave
from pathlib import Path

import numpy as np

from agent import BASE

SR = 44100
MUSIC = BASE / "music"

PROGRESSIONS = [  # semitone offsets of chord roots + minor/major thirds
    [(0, "m"), (-4, "M"), (5, "M"), (-2, "M")],   # Am F C G feel
    [(0, "m"), (3, "M"), (-2, "M"), (-4, "M")],
    [(0, "m"), (5, "m"), (3, "M"), (-2, "M")],
]

STYLES = {
    #  name:      (bpm range,  drums,      arp,   pad_vol, four_floor)
    "lofi":       ((76, 90),   True,       False, 0.16,    False),
    "synthwave":  ((100, 112), True,       True,  0.13,    False),
    "ambient":    ((66, 74),   False,      False, 0.18,    False),
    "house":      ((120, 126), True,       True,  0.12,    True),
    "halftime":   ((136, 144), True,       False, 0.14,    False),
}


def note(freq, secs, vol=0.3, shape="sine"):
    t = np.linspace(0, secs, int(SR * secs), endpoint=False)
    if shape == "saw":
        w = 2 * ((t * freq) % 1) - 1
        w = np.convolve(w, np.ones(24) / 24, mode="same")   # soften
    else:
        w = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, np.minimum(t / 0.08, (secs - t) / 0.25))
    return w * env * vol


def chord(root_midi, quality, secs, vol=0.16):
    third = 3 if quality == "m" else 4
    out = np.zeros(int(SR * secs))
    for iv in (0, third, 7, 12):
        f = 440 * 2 ** ((root_midi + iv - 69) / 12)
        out += note(f, secs, vol, "saw")
        out += note(f / 2, secs, vol * 0.5)          # sub layer
    return out


def drums(secs, bpm, four_floor=False, halftime=False):
    n = int(SR * secs)
    out = np.zeros(n)
    beat = 60 / bpm
    t_k = np.linspace(0, 0.22, int(SR * 0.22), endpoint=False)
    kick = np.sin(2 * np.pi * (55 * np.exp(-t_k * 9)) * t_k) * np.exp(-t_k * 14) * 0.8
    rng = np.random.default_rng(7)
    hat = (rng.standard_normal(int(SR * 0.05)) *
           np.exp(-np.linspace(0, 0.05, int(SR * 0.05)) * 90) * 0.12)
    pos = 0.0
    i = 0
    while pos < secs:
        s = int(pos * SR)
        kick_now = (i % 4 == 0) if halftime else (True if four_floor else i % 2 == 0)
        if kick_now and s + len(kick) < n:
            out[s:s + len(kick)] += kick
        h = int((pos + beat / 2) * SR)
        if h + len(hat) < n:
            out[h:h + len(hat)] += hat
        if halftime:                                  # extra 16th hats
            for off in (0.25, 0.75):
                h2 = int((pos + beat * off) * SR)
                if h2 + len(hat) < n:
                    out[h2:h2 + len(hat)] += hat * 0.6
        pos += beat
        i += 1
    return out


def arp(root_midi, quality, secs, bpm, vol=0.10):
    third = 3 if quality == "m" else 4
    ivs = [0, third, 7, 12, 7, third]
    step = 60 / bpm / 2                               # eighth notes
    out = np.zeros(int(SR * secs))
    pos, i = 0.0, 0
    while pos + step <= secs:
        f = 440 * 2 ** ((root_midi + 12 + ivs[i % len(ivs)] - 69) / 12)
        seg = note(f, step * 0.9, vol)
        s = int(pos * SR)
        out[s:s + len(seg)] += seg
        pos += step
        i += 1
    return out


def render_track(out_path, seed, style="lofi"):
    random.seed(seed)
    (blo, bhi), use_drums, use_arp, pad_vol, four_floor = STYLES[style]
    bpm = random.randint(blo, bhi)
    root = random.choice([55, 57, 59, 60, 62])        # G3..D4 region
    prog = random.choice(PROGRESSIONS)
    bar = 60 / bpm * 4
    pads, arps = [], []
    for root_off, qual in prog * 2:                   # 8 bars
        pads.append(chord(root + root_off, qual, bar, pad_vol))
        arps.append(arp(root + root_off, qual, bar, bpm) if use_arp
                    else np.zeros(int(SR * bar)))
    mix = np.concatenate(pads) + np.concatenate(arps)
    if use_drums:
        mix = mix + drums(len(mix) / SR, bpm, four_floor, style == "halftime")
    mix = mix / np.max(np.abs(mix)) * 0.85
    pcm = (mix * 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out_path


def build_library(per_style=3):
    MUSIC.mkdir(exist_ok=True)
    made = []
    for style in STYLES:
        for i in range(per_style):
            p = MUSIC / f"gen_{style}_{i}.wav"
            if not p.exists():
                render_track(p, seed=hash((style, i)) % 10000, style=style)
            made.append(p)
    return made


def pick_track():
    """User-supplied mp3s win; otherwise a generated wav from the library."""
    MUSIC.mkdir(exist_ok=True)
    user = list(MUSIC.glob("*.mp3"))
    if user:
        return random.choice(user)
    gen = list(MUSIC.glob("gen_*.wav"))
    if not gen:
        gen = build_library()
    return random.choice(gen)


if __name__ == "__main__":
    for p in build_library():
        print(f"library: {p.name}")
