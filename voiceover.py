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


TARGET_WPM = float(os.environ.get("TARGET_WPM", "190"))   # speech-only; ~180+ overall once scene gaps are counted
MAX_STRETCH = 1.35                                         # beyond this the voice starts to sound chipmunk-y


def tighten(path, text, target=None):
    """Make a narration clip meet the target pace, whatever the TTS engine did.

    1. Collapse silences longer than ~0.25s (Kokoro turns '...' and sentence ends into
       long gaps that make the pace feel slow even when the words are fast).
    2. If the speech is still slower than `target` WPM, time-stretch it (pitch-preserving
       atempo) up to MAX_STRETCH.
    Returns (path, seconds, wpm). Falls back to the untouched clip if ffmpeg fails."""
    target = target or TARGET_WPM
    words = len(text.split())
    out = Path(str(path)).with_name(Path(path).stem + "_t.wav")
    ff = get_ffmpeg_exe()
    base = duration(path)
    cmd = [ff, "-y", "-i", str(path), "-af",
           "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.03:"
           "stop_periods=-1:stop_duration=0.25:stop_threshold=-45dB:stop_silence=0.12",
           "-ar", "24000", str(out)]
    if subprocess.run(cmd, capture_output=True).returncode != 0 or not _ok(out):
        return Path(path), base, words / base * 60 if base else 0
    secs = duration(out)
    wpm = words / secs * 60 if secs else 0
    if wpm and wpm < target:
        k = min(MAX_STRETCH, target / wpm)
        out2 = out.with_name(Path(path).stem + "_s.wav")
        r = subprocess.run([ff, "-y", "-i", str(out), "-af", f"atempo={k:.3f}", str(out2)],
                           capture_output=True)
        if r.returncode == 0 and _ok(out2):
            out, secs = out2, duration(out2)
            wpm = words / secs * 60
    return out, secs, wpm


# ElevenLabs (paid-quality voices; free plan = 10,000 credits a month, no commercial licence).
# Needs the ELEVENLABS_API_KEY secret. Characters are counted in eleven_usage.json and the
# backend stops at ELEVENLABS_BUDGET (default 9,000) so a month's credits are never overrun;
# past that, or on any error (including out of credits), the next backend takes over.
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID") or "pNInz6obpgDQGcFmaJgB"   # "Adam" (premade); override with your pick
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
ELEVEN_BUDGET = int(os.environ.get("ELEVENLABS_BUDGET", "9000"))
ELEVEN_USAGE = Path(__file__).parent / "eleven_usage.json"


def _eleven_used():
    import datetime
    import json
    month = datetime.date.today().strftime("%Y-%m")
    try:
        d = json.loads(ELEVEN_USAGE.read_text())
        return month, (d["chars"] if d.get("month") == month else 0)
    except Exception:
        return month, 0


def _synth_eleven(text, out):
    import json
    import urllib.request
    month, used = _eleven_used()
    if used + len(text) > ELEVEN_BUDGET:
        raise RuntimeError(f"ElevenLabs budget reached ({used}/{ELEVEN_BUDGET} chars this month)")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": ELEVEN_MODEL,
                         "voice_settings": {"stability": 0.4, "similarity_boost": 0.8,
                                            "style": 0.35, "use_speaker_boost": True}}).encode(),
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                 "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        f.write(r.read())
    ELEVEN_USAGE.write_text(json.dumps({"month": month, "chars": used + len(text)}))


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
    if os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("VOICE_ENGINE", "kokoro") in ("kokoro", "eleven"):
        backends.append(("elevenlabs", ".mp3", _synth_eleven))
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
                    print(f"  [voiceover] voice: {name}")
                    return Path(out)
            except Exception as e:  # network, blocked endpoint, bad id, no package
                print(f"  [voiceover] {name} attempt {attempt + 1} failed: {e!r:.200}")
    return None
