# Music library provenance

- `px_*.mp3` — downloaded 2026-07-17 from Pixabay Music (pixabay.com/music).
  License: Pixabay Content License — free for commercial use incl. social media
  videos, no attribution required, cannot be resold as standalone audio.
- `gen_*.wav` — original tracks synthesized locally by music_maker.py (5 styles,
  no external source, no license constraints). Fallback pool if mp3s are removed.

pick_track() in music_maker.py prefers mp3s over generated wavs.
