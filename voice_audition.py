"""Render the same ~45-word script in many voices so they can be compared by ear.
Writes voice_samples/<engine>-<voice>.mp3. Kokoro voices run on CPU; edge voices need internet."""
import asyncio
import subprocess
import sys
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

TEXT = ("Stop scrolling... you can run agents that think in code. This tool lets you run powerful "
        "agents in just a few lines of code. It has over twenty thousand stars on GitHub and uses "
        "the Apache licence. That was Day 5 of 100. Save this, send it to a friend, and follow, "
        "or you might not see us again.")
OUT = Path("voice_samples")
OUT.mkdir(exist_ok=True)
KOKORO = ["am_michael", "am_adam", "am_eric", "am_puck", "af_heart", "af_bella", "af_nicole",
          "bm_george", "bm_fable", "bf_emma"]
EDGE = ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural", "en-US-AvaMultilingualNeural",
        "en-US-EmmaMultilingualNeural", "en-US-GuyNeural", "en-GB-RyanNeural",
        "en-IN-PrabhatNeural", "en-IN-NeerjaExpressiveNeural"]


def to_mp3(src, dst):
    subprocess.run([get_ffmpeg_exe(), "-y", "-i", str(src), "-b:a", "128k", str(dst)],
                   capture_output=True, check=True)


def kokoro():
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")
    bpipe = None
    for v in KOKORO:
        try:
            if v.startswith("b"):
                from kokoro import KPipeline as K
                bpipe = bpipe or K(lang_code="b")
                p = bpipe
            else:
                p = pipe
            audio = np.concatenate([a for _, _, a in p(TEXT, voice=v, speed=1.3)])
            wav = OUT / f"kokoro-{v}.wav"
            sf.write(str(wav), audio, 24000)
            to_mp3(wav, OUT / f"kokoro-{v}.mp3")
            wav.unlink()
            print("ok kokoro", v)
        except Exception as e:
            print("fail kokoro", v, repr(e)[:120])


async def edge():
    import edge_tts
    for v in EDGE:
        try:
            await edge_tts.Communicate(TEXT, v, rate="+15%").save(str(OUT / f"edge-{v}.mp3"))
            print("ok edge", v)
        except Exception as e:
            print("fail edge", v, repr(e)[:120])


if __name__ == "__main__":
    kokoro()
    asyncio.run(edge())
