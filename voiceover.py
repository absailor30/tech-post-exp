"""Text-to-speech narration for Reels.

Order: Kokoro (open source, Apache-2.0, runs on CPU, voice am_michael) -> NVIDIA
Riva (only if NVIDIA_TTS_FUNCTION_ID is set) -> Microsoft edge-tts -> silence.

Best-effort by design: every failure returns None so the reel falls back to
music-only exactly as before. A voice problem must never fail a post.
"""

import asyncio
import os
import re
import subprocess
import wave
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

VOICE = "en-US-AndrewMultilingualNeural"   # fallback; the older AndrewNeural sounded robotic
RATE = "+8%"          # slightly brisk; Reels viewers skip slow narration


def narration_text(spec):
    """What gets spoken for a slide: its own spoken script if it has one
    (series reels), else the on-screen words."""
    if spec.get("say"):
        return re.sub(r"\s+", " ", spec["say"]).strip()
    parts = [spec.get("headline", ""), spec.get("body", "")]
    text = ". ".join(p.strip().rstrip(".!?") for p in parts if p and p.strip())
    return re.sub(r"\s+", " ", text).strip()


def duration(path):
    """Seconds of audio in a file (imageio-ffmpeg ships no ffprobe)."""
    r = subprocess.run([get_ffmpeg_exe(), "-i", str(path)],
                       capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


async def _synth(text, out):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(out))


# NVIDIA Riva (hosted Magpie TTS) — uses the same NIM_API_KEY as the LLM, but
# needs the hosted function id of the TTS model. Copy it from the model's
# "Try API" > Python sample on build.nvidia.com (`function-id` metadata) and
# set it as NVIDIA_TTS_FUNCTION_ID. Unset => Riva is skipped.
RIVA_URI = "grpc.nvcf.nvidia.com:443"
RIVA_VOICE = os.environ.get("NVIDIA_TTS_VOICE", "Magpie-Multilingual.EN-US.Aria")
RIVA_RATE = 44100


def _synth_riva(text, out):
    import riva.client
    auth = riva.client.Auth(
        use_ssl=True, uri=RIVA_URI,
        metadata_args=[["function-id", os.environ["NVIDIA_TTS_FUNCTION_ID"]],
                       ["authorization", f"Bearer {os.environ['NIM_API_KEY']}"]])
    resp = riva.client.SpeechSynthesisService(auth).synthesize(
        text, voice_name=RIVA_VOICE, language_code="en-US",
        sample_rate_hz=RIVA_RATE, encoding=riva.client.AudioEncoding.LINEAR_PCM)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RIVA_RATE)
        w.writeframes(resp.audio)


KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "am_michael")
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", "1.3"))   # measured: 1.08 -> ~141 wpm, 1.25 -> ~174 wpm overall incl. pauses; 1.4 -> ~215 wpm; 1.3 + fuller script targets ~185
_kokoro = None


def _synth_kokoro(text, out):
    """Kokoro-82M on CPU. Punctuation drives its phrasing: '...' gives a pause,
    '?' lifts the pitch, short sentences land with emphasis."""
    global _kokoro
    import numpy as np
    import soundfile as sf
    if _kokoro is None:
        from kokoro import KPipeline
        _kokoro = KPipeline(lang_code="a")
    audio = np.concatenate([a for _, _, a in _kokoro(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED)])
    sf.write(str(out), audio, 24000)


def _ok(path):
    return Path(path).exists() and Path(path).stat().st_size > 1000


def synth(text, out_stem, retries=2):
    """Speak `text` to a file starting with `out_stem`.

    Tries Kokoro, then Riva (if NVIDIA_TTS_FUNCTION_ID is set), then edge-tts. Returns the
    written path, or None if every backend failed.
    """
    if not text:
        return None
    stem = str(out_stem)
    backends = []
    if os.environ.get("VOICE_ENGINE", "kokoro") == "kokoro":
        backends.append(("kokoro", ".wav", _synth_kokoro))
    if os.environ.get("NVIDIA_TTS_FUNCTION_ID") and os.environ.get("NIM_API_KEY"):
        backends.append(("riva", ".wav", _synth_riva))
    backends.append(("edge-tts", ".mp3", lambda t, o: asyncio.run(_synth(t, o))))
    for name, ext, fn in backends:
        out = stem + ext
        for attempt in range(retries + 1):
            try:
                fn(text, out)
                if _ok(out):
                    return Path(out)
            except Exception as e:  # network, blocked endpoint, bad id, no package
                print(f"  [voiceover] {name} attempt {attempt + 1} failed: {e!r:.200}")
    return None
