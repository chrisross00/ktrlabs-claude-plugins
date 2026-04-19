# Backlog — claude-code-recorder

Improvements deferred from v0.1.0, roughly ordered by expected impact.

## Correctness / reliability

- **Multilingual transcription.** Current `small.en` model silently produces garbage for non-English speech. Ship the multilingual `small` model, or detect language and warn.
- **Model upgrade path.** Bootstrap only verifies existing hashes — no migration if a later version needs a newer model. For long-term 3000-user support, add a version-keyed manifest.
- **Brittle brew binary discovery.** We hardcode `whisper-cli` inside the `whisper-cpp` brew package. A rename would break us silently. Search `<prefix>/bin/` for any `whisper*` executable and prefer the newest.

## UX / polish

- **Frame cue list is too broad.** "this", "here", "see" fire on nearly every sentence; 2-min recordings typically emit 30+ cued frames before dedup. Tighten triggers (multi-word phrases, verb-biased) or weight frames by surrounding segment density.
- **Perceptual dedup is effectively disabled** under system Python because `imagehash` isn't installed. Vendor `imagehash` into the plugin or ship a bundled Python env so the dedup pass actually runs.
- **Shrink first-run footprint.** The ~500MB `small.en` model blocks users for minutes on first install. Ship `tiny.en` (~75MB) as the quick-start default; `small`/`medium` as opt-in upgrades.
- **Audio-level feedback.** `/record-status` could show the last few seconds' RMS so users don't discover a muted mic only after stopping.
- **Auto-prune old sessions.** Currently sessions accumulate under `~/.cache/recorder/sessions/` until the user runs `/record-clean`. After N days or M sessions, prune oldest automatically.
- **Pause/resume.** One-take recording is a usability constraint. Let users pause and resume without restarting ffmpeg.

## Performance

- **Pipeline is sequential.** `transcribe` and `extract_frames` are independent — could run in parallel for ~30% speedup on long recordings.
- **ffmpeg log grows unbounded** within a session. Not a real issue until someone records for hours, but cheap to rotate.

## Distribution / operations

- **Integration-test gap** (from the post-mortem). 62 unit tests are mostly mocked. Until at least the binary-install smoke, real-subprocess-detachment, and E2E-fixture tests land, regressions will ship the same way v0.1.0 did.
- **No telemetry.** Zero signal about usage/failure modes at scale. Even anonymous "X recorded / Y pipeline-failed at stage Z" would be invaluable. Requires privacy review.
- **No plugin signing.** Any CC install of this plugin is full-trust. For internal org deployment, at minimum sign commits; ideally a signed release artifact + verified marketplace manifest.
- **Plan/spec drift.** The original `docs/superpowers/specs/` and `plans/` documents don't reflect the 9 real-world bugfixes from the post-mortem. Future contributors reading them get a false picture.
