"""Scratch: re-mix only the audio of an existing series preview (no page capture).
Re-synthesizes the narration from slides.json, rebuilds the mix with the current
levels, and muxes it onto the existing video stream (copied, not re-encoded)."""
import glob, json, os, re, subprocess, sys, tempfile
from pathlib import Path
from imageio_ffmpeg import get_ffmpeg_exe
import reel_maker as rm
from music_maker import pick_track

d = Path(os.environ["PREVIEW_DIR"])      # explicit: never guess which preview to remix
specs = json.loads((d / "slides.json").read_text())["slides"]
tmp = Path(tempfile.mkdtemp())
clips = rm._narrate(specs, tmp)
assert clips, "narration failed"
voice, idx = [], 0
for spec, (path, secs_audio) in zip(specs, clips):
    secs = max(2.5, secs_audio + rm.VOICE_PAD)
    voice.append((path, idx / rm.FPS + rm.VOICE_LEAD))
    idx += int(secs * rm.FPS)
dur = idx / rm.FPS
ff = get_ffmpeg_exe()
out = d / "reel_v3.mp4"
cmd = [ff, "-y", "-i", str(d / "reel.mp4"), "-i", str(pick_track()),
       *sum([["-i", str(c)] for c, _ in voice], []),
       "-filter_complex", rm.audio_graph(voice, dur),
       "-map", "0:v", "-map", "[aud]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
       "-shortest", "-movflags", "+faststart", str(out)]
r = subprocess.run(cmd, capture_output=True, text=True)
print("ffmpeg rc", r.returncode, r.stderr[-400:] if r.returncode else "")
m = subprocess.run([ff, "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"],
                   capture_output=True, text=True).stderr
print("integrated LUFS:", re.findall(r"I:\s+(-?[\d.]+) LUFS", m)[-1:], "| true peak dBFS:",
      re.findall(r"Peak:\s+(-?[\d.]+) dBFS", m)[-1:], "| duration %.1fs" % dur)
