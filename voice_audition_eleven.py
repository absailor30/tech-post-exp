"""Audition ElevenLabs voices with ONE short line each (a few hundred characters of the monthly
credits in total). Lists every voice on the account into the log, renders a handful of the
premade English ones to voice_samples/eleven-<name>.mp3. Needs ELEVENLABS_API_KEY."""
import json
import os
import re
import urllib.request
from pathlib import Path

KEY = os.environ["ELEVENLABS_API_KEY"]
TEXT = ("Stop scrolling... you can run AI agents that write and execute code. "
        "It has over twenty thousand stars on GitHub, and it's free.")
MAX_VOICES = int(os.environ.get("MAX_VOICES", "4"))
OUT = Path("voice_samples")
OUT.mkdir(exist_ok=True)


def api(path, body=None):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io{path}", method="POST" if body else "GET",
        data=json.dumps(body).encode() if body else None,
        headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


voices = json.loads(api("/v1/voices"))["voices"]
print(f"{len(voices)} voices on the account:")
for v in voices:
    lab = v.get("labels") or {}
    print(f"  {v['voice_id']}  {v['name']:<14} {v.get('category', ''):<10} "
          f"{lab.get('gender', '')}/{lab.get('age', '')}/{lab.get('accent', '')}/{lab.get('use_case', '')}")

pick, seen = [], set()
for want in ("male", "female"):                      # alternate so both are represented
    for v in voices:
        lab = v.get("labels") or {}
        if v.get("category") == "premade" and lab.get("gender") == want and v["voice_id"] not in seen \
                and (lab.get("accent", "american") in ("american", "british", "")):
            pick.append(v); seen.add(v["voice_id"])
            if len(pick) % 2 == 0 or want == "female":
                break
    # keep going until we have MAX_VOICES
more = [v for v in voices if v["voice_id"] not in seen and v.get("category") == "premade"]
pick = (pick + more)[:MAX_VOICES]
print("auditioning:", [v["name"] for v in pick])
for v in pick:
    try:
        audio = api(f"/v1/text-to-speech/{v['voice_id']}?output_format=mp3_44100_128",
                    {"text": TEXT, "model_id": os.environ.get("ELEVENLABS_MODEL") or "eleven_flash_v2_5",
                     "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35,
                                        "use_speaker_boost": True}})
        name = re.sub(r"[^A-Za-z0-9]+", "", v["name"])
        (OUT / f"eleven-{name}-{v['voice_id'][:6]}.mp3").write_bytes(audio)
        print("ok", v["name"], len(audio) // 1024, "KB")
    except Exception as e:
        print("fail", v["name"], repr(e)[:200])
