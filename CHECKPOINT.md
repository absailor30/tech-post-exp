# Checkpoint — 2026-09-29

Status doc for picking this project back up in a fresh chat. This is the
`@thealgorithmzedge` autonomous Instagram content pipeline in
`absailor30/tech-post-exp`.

## Current state: healthy

- Posting twice daily (morning + evening IST slots), reels-only, AI-news-only,
  research-gated with dedup against post history.
- Instagram token was regenerated on 2026-09-25 after two separate expiries
  and is currently working — verified via a forced run that published
  successfully (media id `17873164452593225`, topic "Gemini 3.8 speaks text
  aloud").
- Seed-comment feature (see below) is live and has a safety guard after an
  early bug shipped a bad comment to a real post.
- `tech-myth-bust` (a separate, unrelated repo — an abandoned scraper
  prototype) had its daily cron disabled 2026-09-27 after failing silently
  since mid-August (Groq retired `llama-3.3-70b-versatile`). Not part of this
  pipeline; only mentioned here so a future "why did I get an email" question
  isn't re-investigated from scratch.

## Architecture (quick map)

- `autonomous_run.py` — the whole pipeline: research → LLM plan → render →
  publish → seed comment → record. Entry point for `daily-post.yml`.
- `research.py` — multi-source aggregation (21 sources, min 5 required),
  dedup via `content_tokens()`/`significance()`/`similarity()`, `record()`
  only fires after a successful publish.
- `agent.py` — LLM client (NVIDIA NIM, model `nvidia/nemotron-3-ultra-550b-a55b`
  with fallbacks), `IG_API` base, `ig_token()`, shared `log()`.
- `make_image.py` — Pillow rendering, light/dark WCAG-AA themes chosen
  per-story by tone, per-letter reveal animation.
- `reel_maker.py` — word-count-paced slide durations, ffmpeg video build.
- `notify.py` — Telegram summaries/failure alerts, deduped by
  (date, failure-signature) so a recurring known issue doesn't spam.
- `.github/workflows/daily-post.yml` — 6 cron firings/day (3 per slot:
  primary/backup/last-resort), `workflow_dispatch` with `force` and
  `metrics_only` inputs.
- `.github/workflows/dm-responder.yml` — polls own-post comments every 3h,
  sends private-reply DMs on trigger keyword "EDGE". Not webhook-based.

## Seed comment feature (added 2026-09-25, fixed 2026-09-25)

`post_seed_comment()` in `autonomous_run.py`, called right after every
successful publish. Generates one short, non-salesy first comment via the
same LLM (opinion question / take / tag-a-friend prompt) to seed engagement
on a fresh post instead of leaving it at zero comments.

**Known failure mode already fixed**: the LLM once echoed its own prompt
instructions back as the "comment" (a bulleted list like "- Max 2 sentences
- Under 150 characters..."), and that got posted verbatim to a real
Instagram post before the guard existed. `_looks_like_a_real_comment()` now
rejects anything that's multi-line, starts with a bullet, is over 220 chars,
or contains phrases like "max ", "sentence", "hashtag" that indicate the
model is talking about its own constraints rather than writing a comment.
Failure is always non-fatal — a bad/failed comment never fails the whole run
since the post itself already succeeded by that point.

If seed comments start looking off again, check `_looks_like_a_real_comment`
first — it's a heuristic, not exhaustive, so a sufficiently different
degenerate output could still slip through.

## Open/paused thread: Google Veo video backgrounds

The user asked to explore generating Veo background video (via Vertex AI) to
replace/augment the current Pillow gradient reel background. This is
**parked, not resolved** — do not assume it's working.

- Diagnostic-only files exist and are explicitly throwaway, safe to delete
  once/if real Veo integration ever lands: `veo_probe.py` and
  `.github/workflows/veo-probe.yml`.
- Root cause found 2026-09-20: the service account actually baked into the
  `GCP_SA_KEY` secret is `tech-post-algorithmzedge@yt-post-502319.iam.gserviceaccount.com`,
  but every IAM role fix/verification was done against a **different**
  service account, `vertex-express@yt-post-502319.iam.gserviceaccount.com`.
  That mismatch fully explains the persistent identical 404s across region
  and global endpoints despite "correct" IAM — the role was never on the
  account making the calls.
- **Not yet done**: granting the role to the correct account (or swapping
  the secret to a key for the account that already has it), re-running
  `veo-probe.yml` to confirm success, and then actually building the
  production integration (compositing a Veo clip behind the existing
  Pillow text overlays — text-to-video models aren't reliable for precise
  on-screen text, so keep text rendering under our own control).
- A budget-aware fallback to the current Pillow gradient (in case Veo
  credit/quota runs out) was proposed but never built.
- This was a live security event during the debugging: the user pasted a
  real GCP service account private key directly into chat. It was treated
  as compromised-by-exposure, tested only in an isolated scratchpad, never
  committed, and the user was told to rotate it (it later started failing
  with `invalid_grant`, consistent with Google auto-revoking it).

## Useful verification commands

```bash
# confirm main is clean and pushed
git fetch origin main -q && git rev-list --left-right --count HEAD...origin/main   # want "0 0"

# check for an unresolved failure recorded by the pipeline itself
git show origin/main:last_error.txt 2>&1   # errors "does not exist" when healthy

# recent post history at a glance
git log origin/main --oneline -20 | grep "^.......* post "
```

To trigger a real run and check Actions logs, use the GitHub MCP tools
(`mcp__github__actions_run_trigger`, `mcp__github__get_job_logs`) against
`absailor30/tech-post-exp` — always pull real log output before reporting
success or failure; this project has a strict "verify against evidence,
never guess" norm established over many rounds of debugging.

## Added 2026-10-03 (voiceover, accuracy, repos series)

- **Voiceover**: `voiceover.py` narrates each slide's on-screen text (edge-tts;
  Riva is tried first only if `NVIDIA_TTS_FUNCTION_ID` is set — it isn't). Slide
  length stretches to fit the audio; any TTS failure falls back to music-only.
- **Accuracy**: `research.fetch_article()` grabs article text; the plan prompt
  allows only source-backed facts; `fact_check()` is a second LLM pass that blocks
  unsupported claims (one rewrite, then skip and log `fact_check_blocked`).
- **Seed comment fix**: the 120-token cap truncated the reasoning model's
  scratchpad every time. Now 3000 tokens + a `COMMENT:` marker line.
- **Image generation**: no usable backend. NVIDIA key lists no image models;
  hosted FLUX.1-dev returned 500 and schnell timed out (2026-10-03 probe); SD3 is
  404 for this account. Veo/Imagen blocked by the GCP key issue above.
- **100-day "AI repos worth knowing" series**: `repos.json` (100 repos, spaced by
  category; 39 seeded from the owner's SecondBrain/00-Inbox/Review.md),
  `series.py` (live GitHub API facts + README as source material),
  `series_state.json` (posted/skipped/blocked), `python autonomous_run.py --series`,
  workflow `series-post.yml` (once a day, 09:00 IST primary + 2 backups). Repos
  that 404/are archived are skipped automatically.
- **Posting cadence caveat**: scheduled runs fire 4-7h late, so the "morning" news
  runs land in the evening slot and real news output is ~1 post/day, not 2.
- **Git gotcha**: the Actions bot token cannot push commits that touch
  `.github/workflows/`. Never let a branch run push workflow-file history to main.
