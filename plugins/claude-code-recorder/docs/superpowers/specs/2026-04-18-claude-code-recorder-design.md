# claude-code-recorder — Design

**Status**: Draft
**Date**: 2026-04-18
**Owner**: Chris

## Problem

When developing locally, communicating UI bugs or unexpected behavior to Claude Code currently requires manually taking screenshots, annotating what's actual vs. expected, and assembling that into a prompt. This is slow and error-prone, especially for multi-step flows where cause/effect matters.

A Loom-style "record your screen while narrating" workflow would be far faster: one recording produces a full, timestamped demo. But Claude Code cannot accept video directly — video must be decomposed into frames + transcript before it's usable as prompt context.

## Goal

A Claude Code plugin that lets a developer record a narrated screen demo, then automatically converts it into a chronological prompt (narration interleaved with relevant screenshots) that's dropped into the current CC conversation for Claude to act on.

Target audience: an internal developer population of ~3000 engineers. Onboarding friction is a first-class concern.

## Non-goals

- Replacing Claude Code's built-in `/voice` dictation (that's real-time prompt input; this is async demo capture).
- Server-side transcription (all transcription happens locally to avoid uploading proprietary UI/code).
- Cross-platform support in v1 (macOS only).
- Editing the recording after the fact.

## Core decisions

| Question | Decision | Why |
|---|---|---|
| Shape | CC plugin, `/record` slash command | Lowest-friction invocation for CC users |
| Start/stop | Single toggle command | One command to remember; mirrors QuickTime-style recording UX |
| Screenshot selection | Hybrid: scene-change (structural markers) + transcript-cued deictic words (primary) | Scene-change gives backbone; narration cues catch emphasis; dedup handles overlap |
| Transcription | Local Whisper (`whisper.cpp`) | Free, offline, fast on Apple Silicon, no uploads of proprietary material |
| Recording tool | `ffmpeg` with avfoundation | Single binary captures screen + mic; portable; install friction absorbed by the plugin's SessionStart hook |
| Output structure | Chronological timeline — narration interleaved with screenshot paths at their timestamps | Preserves temporal cause/effect; Claude invokes `Read` on paths for vision |
| Internal architecture | Staged pipeline (`capture → transcribe → extract_frames → assemble`) | Each stage independently testable; iterating on heuristics touches one file |
| Distribution | CC plugin marketplace | One-step install (`/plugin install`) for the org |
| Dependency bootstrap | SessionStart hook + `${CLAUDE_PLUGIN_DATA}` | Official CC pattern; lazy install on first session; cached across plugin updates |

Claude Code plugin slash commands cannot directly attach images to prompts. Workaround: the generated `prompt.md` contains image file paths as text, and Claude auto-invokes the `Read` tool (which supports PNG vision) on those paths.

## Architecture

Three internal layers:

1. **Bootstrap layer** — `hooks/session-start.sh` verifies `ffmpeg`, `whisper.cpp` binary, and Whisper model are present in `${CLAUDE_PLUGIN_DATA}`. On the happy path (manifest recent, all files present) it exits in ~50ms. Fully installs on first session (~2 min for model download).
2. **Recording layer** — `bin/record_toggle.py` manages state via an atomically-written `state.json` (PID + session ID + start time). Toggle semantics: absent = idle; present = active.
3. **Processing pipeline** — four discrete stages run on stop, each reading from disk and writing to disk: `capture → transcribe → extract_frames → assemble`.

### User-facing commands

- `/record [TITLE]` — toggle. First call starts recording (optional title names the session); second call stops and emits the prompt.
- `/record-clean [all | older-than <N> | <id>]` — safe-by-default: no args lists sessions with sizes + ages; args delete.
- `/record-doctor` — diagnostics: rerun bootstrap, clear stale state, show permission status, print disk usage, show last 3 session outcomes.

### Plugin structure

```
claude-code-recorder/
├── .claude-plugin/
│   └── plugin.json              # manifest
├── commands/
│   ├── record.md                # /record toggle
│   ├── record-clean.md          # /record-clean
│   └── record-doctor.md         # /record-doctor
├── hooks/
│   └── session-start.sh         # dep bootstrap
├── bin/
│   ├── bootstrap.py             # install/verify deps
│   ├── record_toggle.py         # start/stop state machine
│   └── pipeline/
│       ├── transcribe.py        # whisper.cpp wrapper, emits timestamped JSON
│       ├── extract_frames.py    # scene-change + transcript-cued frame extraction + dedup
│       └── assemble.py          # produces final prompt.md
└── tests/
    ├── fixtures/                # sample video+audio, expected outputs
    └── test_*.py
```

### Runtime paths

- `${CLAUDE_PLUGIN_DATA}/bin/` — installed `ffmpeg` + `whisper.cpp` binaries.
- `${CLAUDE_PLUGIN_DATA}/models/` — Whisper model (default: `ggml-small.en.bin`).
- `~/.cache/recorder/sessions/<YYYYMMDD-HHMMSS>[-<slug>]/` — per-recording working dir (video, audio, frames, `prompt.md`, `metadata.json`).
- `~/.cache/recorder/state.json` — active-recording state. Absent = idle.
- `~/.cache/recorder/bootstrap.json` — dep-verification manifest (last-verified timestamp, binary/model hashes).

## Data flow

### Start (`/record [TITLE]`, no active session)

1. `record_toggle.py` sees no `state.json`.
2. Generates session ID `<YYYYMMDD-HHMMSS>` + optional slug from `TITLE`.
3. Mkdirs `~/.cache/recorder/sessions/<id>/`, writes `metadata.json` with full title.
4. Spawns `ffmpeg -f avfoundation -i "1:0" -framerate 30 video.mp4` in background, captures PID.
5. Atomically writes `state.json` with `{pid, session_id, started_at}`.
6. Output: `"Recording started. Run /record again to stop."`

### Stop (`/record`, active session)

1. `record_toggle.py` sees `state.json` → sends `SIGINT` to ffmpeg PID → waits for clean exit (flushes MP4 moov atom).
2. Deletes `state.json`.
3. Runs pipeline stages sequentially on the session dir:
   - `transcribe.py video.mp4 → transcript.json` (whisper.cpp with `--output-json` and word-level timestamps).
   - `extract_frames.py video.mp4 transcript.json → frames/*.png + frames.json`:
     - Scene-change pass: `ffmpeg` with `select=gt(scene,0.4)` filter.
     - Transcript-cue pass: scan transcript for deictic markers (`here|this|notice|look at|see|watch|click|type|press`), emit timestamps.
     - Merge both lists, dedup within 2s windows.
     - Perceptual-hash pass to drop near-duplicates.
     - `frames.json` maps timestamp → filename → trigger type.
   - `assemble.py transcript.json frames.json → prompt.md` (chronological markdown).
4. Slash command output prints `prompt.md` content. CC injects it as the user prompt. Claude sees image paths and invokes `Read` to view them.

### Output format (`prompt.md`)

All image paths emitted in `prompt.md` are **absolute** (no `~` or relative paths), since the `Read` tool doesn't expand `~` and Claude's working directory is not guaranteed.

```markdown
# Screen demo — fix checkout 500 — 2026-04-18 14:32 — 47s

[00:00] Opening the checkout page locally.
[00:03] ![frame_003.png](/Users/chris/.cache/recorder/sessions/20260418-143200-fix-checkout-500/frames/frame_003.png)
[00:05] I'm clicking the Submit button — notice the button turns red.
[00:05] ![frame_005.png](...)
[00:12] Expected: green success banner. Actual: console shows a 500.
[00:12] ![frame_012.png](...)

Session dir: /Users/chris/.cache/recorder/sessions/20260418-143200-fix-checkout-500/
```

## Error handling

Principle: every failure path produces a one-line, actionable message. Never leave the system in a state where `/record` is unusable with no recovery.

**Bootstrap failures**:
- Missing network during dep download → hook exits with clear message; slash commands hint at `/record-doctor` when online.
- Disk full / permission denied on `${CLAUDE_PLUGIN_DATA}` → error names the offending path.
- Model checksum mismatch → auto-redownload once, then fail loud if the second attempt mismatches.
- Partial download → manifest not updated until verification succeeds; crashed bootstrap is retried next session.

**macOS permission failures**:
- First `/record` invocation probes devices before starting ffmpeg. If Screen Recording or Microphone permission denied, output a pre-formatted block naming the exact System Settings path and the binary needing permission.

**Recording failures**:
- Stale `state.json` (PID points to dead process) → treat as idle and clear state file. Catches orphans from crashes / reboots / killed terminals.
- ffmpeg crashes mid-record → session dir keeps partial `video.mp4`; stop path still attempts pipeline on it; unrecoverable cases leave the partial video accessible with an error message.
- Disk full during record → caught when ffmpeg exits nonzero on SIGINT; error names the session dir.
- Double `/record` race → `state.json` writes are atomic (write-temp-then-rename); no broken-intermediate state.

**Processing failures**:
- Each pipeline stage catches its own errors and writes `error.txt` to the session dir.
- Assemble detects upstream `error.txt` and produces best-effort `prompt.md` with `⚠ transcript missing — video available at: …` so the user still gets something.
- Session dir is never auto-deleted on failure.

**User-arg errors**:
- `/record-clean older-than abc` → prints accepted format.
- `/record-clean foo` with no match → prints matching-session count and available IDs.
- `/record "title"` while session active → title ignored with one-line note.
- Title slug collision → append `-2`, `-3`.

**`/record-doctor`** covers: rerun bootstrap, clear stale state.json, show permission status, print disk usage, show last 3 session outcomes, reset to clean slate (with confirmation).

## Testing

### Cadence

- **Every PR** (GitHub Actions, <1 min): unit tests per stage (with canned fixture inputs; no real whisper/ffmpeg), state-machine tests, bootstrap tests with mocked network + temp data dir, lint, type-check.
- **Pre-release only**: E2E runs once before a version tag. Either manual (`pytest -m e2e` locally) or a manually-triggered GitHub Actions workflow on GitHub-hosted macOS runners with a cached Whisper model.
- **No nightly** in v1. Defer until multiple maintainers or upstream-breakage patterns justify the infra cost.

### What's tested

**Unit tests per stage** (`tests/test_<stage>.py`):
- `transcribe.py`: fixture `audio_short.wav` (3s canned phrase) → assert transcript has expected words at expected word-level timestamps (±500ms tolerance).
- `extract_frames.py`: fixture `video_with_modal.mp4` + canned `transcript.json` containing deictic words → assert frames extracted at scene-change points, at transcript-cue points, dedup removes frames within 2s, perceptual-hash dedup removes near-identical frames.
- `assemble.py`: fixture `transcript.json` + `frames.json` → assert `prompt.md` interleaves correctly, timestamps monotonic, image paths valid.

**State-machine tests** (`tests/test_record_toggle.py`):
- Idle → start → valid `state.json`.
- Active → stop → pipeline runs, `state.json` gone, `prompt.md` exists.
- Stale PID → start treats as idle.
- Concurrent invocations — simulate atomic write race, verify no corruption.
- Title slug collision → dir gets `-2`.

**Bootstrap tests** (`tests/test_bootstrap.py`):
- Missing manifest → full verification runs.
- Recent manifest + all files present → fast-path in <100ms (asserted).
- Stale manifest → hash re-verification runs.
- Checksum mismatch → redownload triggered once, then fail.
- Tests use temp `${CLAUDE_PLUGIN_DATA}` dir.

**End-to-end smoke test** (`tests/test_e2e.py`, marked `@pytest.mark.e2e`):
- Fixture 10s screen recording with narration ("Here is the button. Watch it turn red. Notice the 500 error.") → full pipeline → assert `prompt.md` contains all three deictic-cued frames, output format parses correctly.
- Skipped if fixtures/model missing.

### What's not tested

- Real macOS permission dialogs (manual testing only; verified once per OS version on a clean user profile).
- First-install experience (manual).
- Whisper transcription quality (upstream).
- ffmpeg correctness (upstream).

## Open questions

None as of spec sign-off. Future revisits, deferred from v1:

- **Recording tool**: revisit Swift/ScreenCaptureKit if ffmpeg friction surfaces in practice.
- **Nightly CI**: add if upstream breakage becomes a support-burden pattern.
- **Cross-platform**: Linux/Windows support post-v1 if adoption demands it.
