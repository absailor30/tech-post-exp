"""Scratch: audition voices on the runner. Writes audition/*.mp3 and prints timings."""
import asyncio, os, subprocess, sys, time, traceback
from pathlib import Path
from imageio_ffmpeg import get_ffmpeg_exe
FF = get_ffmpeg_exe()
OUT = Path("audition"); OUT.mkdir(exist_ok=True)
TEXT = ("Did you know... you can now run your own local AI models, right on your own computer? "
        "No sign-up. No waiting. Just you, and your laptop. Let me show you how this works.")

def to_mp3(src, dst):
    subprocess.run([FF, "-y", "-i", str(src), "-ac", "1", "-b:a", "96k", str(dst)], capture_output=True)

# 1. edge-tts voices
async def edge():
    import edge_tts
    voices = {v["ShortName"] for v in await edge_tts.list_voices()}
    want = ["en-US-AvaMultilingualNeural", "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural",
            "en-US-EmmaMultilingualNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-US-GuyNeural"]
    print("edge voices available:", sorted(v for v in voices if v.startswith(("en-US-","en-IN-")) and "Multilingual" in v or "IN" in v)[:30])
    for v in want:
        if v not in voices:
            print("  missing", v); continue
        try:
            await edge_tts.Communicate(TEXT, v, rate="+0%").save(str(OUT / f"edge_{v}.mp3"))
            print("  ok", v)
        except Exception as e:
            print("  fail", v, repr(e)[:100])
try: asyncio.run(edge())
except Exception: traceback.print_exc()

# 2. Kokoro (Apache-2.0, CPU)
try:
    subprocess.run("sudo apt-get install -y -q espeak-ng >/dev/null 2>&1", shell=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kokoro", "soundfile"], check=True)
    import numpy as np, soundfile as sf
    from kokoro import KPipeline
    t = time.time(); pipe = KPipeline(lang_code="a"); print(f"kokoro load {time.time()-t:.1f}s")
    for v in ["af_heart", "af_bella", "af_nicole", "am_adam", "am_michael"]:
        t = time.time()
        audio = np.concatenate([a for _, _, a in pipe(TEXT, voice=v, speed=1.0)])
        sf.write(OUT / f"kokoro_{v}.wav", audio, 24000)
        to_mp3(OUT / f"kokoro_{v}.wav", OUT / f"kokoro_{v}.mp3"); (OUT / f"kokoro_{v}.wav").unlink()
        print(f"  kokoro {v}: {len(audio)/24000:.1f}s audio in {time.time()-t:.1f}s")
except Exception:
    traceback.print_exc()

# 3. Chatterbox (MIT, zero-shot cloning) — default voice, CPU speed check
try:
    t = time.time()
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "torch==2.6.0", "torchaudio==2.6.0",
                    "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "chatterbox-tts"], check=True)
    print(f"chatterbox install {time.time()-t:.0f}s")
    import torch, torchaudio as ta
    from chatterbox.tts import ChatterboxTTS
    t = time.time(); model = ChatterboxTTS.from_pretrained(device="cpu"); print(f"chatterbox load {time.time()-t:.0f}s")
    for name, kw in (("neutral", dict(exaggeration=0.5, cfg_weight=0.5)), ("expressive", dict(exaggeration=0.8, cfg_weight=0.3))):
        t = time.time()
        wav = model.generate(TEXT, **kw)
        dur = wav.shape[-1] / model.sr
        ta.save(str(OUT / f"chatterbox_{name}.wav"), wav, model.sr)
        to_mp3(OUT / f"chatterbox_{name}.wav", OUT / f"chatterbox_{name}.mp3"); (OUT / f"chatterbox_{name}.wav").unlink()
        print(f"  chatterbox {name}: {dur:.1f}s audio in {time.time()-t:.0f}s (RTF {(time.time()-t)/dur:.1f}x)")
except Exception:
    traceback.print_exc()
print("files:", sorted(p.name for p in OUT.glob("*.mp3")))
