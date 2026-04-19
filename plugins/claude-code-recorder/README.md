# claude-code-recorder

Record a narrated screen demo; get a transcript + relevant screenshots dropped back into Claude Code as a prompt. Ends the "screenshot → paste → describe what's wrong" dance for local UI bugs.

## Install

From within Claude Code, once per user:

```
/plugin marketplace add /path/to/claude-code-recorder
/plugin install claude-code-recorder@claude-code-recorder
```

On the **first new CC session after install**, a SessionStart hook bootstraps dependencies:

- `ffmpeg` and `whisper-cpp` via Homebrew
- Whisper `tiny` multilingual model (~75 MB) from Hugging Face

Binaries and the model are cached under `~/.local/share/claude-code-recorder/`. Subsequent sessions verify in ~50 ms.

## First-run macOS permissions

Before recording you must grant your terminal host (cmux, iTerm, Terminal, etc.) two macOS permissions. Run once:

```
/claude-code-recorder:record-doctor
```

If the **Permissions** section reports `NOT WORKING`, follow its remediation block. On a truly fresh machine, `/record` itself will also trigger the permission dialogs the first time ffmpeg tries to access the screen and mic.

Notes:
- macOS shows a **permission dialog only once per app**. If dismissed or later revoked, there is no re-prompt; the app is silently denied until you toggle it back on in System Settings.
- **Screen Recording** list has `+`/`-` buttons and supports forcing a re-prompt by removing the app.
- **Microphone** list has *no* `-` button. To force a re-prompt for an app:
  ```
  mdls -name kMDItemCFBundleIdentifier -r /Applications/<app>.app
  tccutil reset Microphone <bundle-id>
  ```

## Commands

| Command | What it does |
|---|---|
| `/claude-code-recorder:record [TITLE]` | Toggle. First call starts recording (optional title). If paused, resumes. Otherwise stops and emits a chronological prompt (transcript interleaved with screenshots) into your CC conversation. |
| `/claude-code-recorder:record-pause` | Pause the active recording without running the pipeline. Run `/record` again to resume. Useful for multi-take demos. |
| `/claude-code-recorder:record-cancel` | Stop ffmpeg and delete the session dir without running the pipeline. Use when you want to start over. |
| `/claude-code-recorder:record-status` | Inspect the active recording without stopping it — session ID, elapsed time, video file size, ffmpeg PID liveness, recent mic level. |
| `/claude-code-recorder:record-clean [all \| older-than <Nd\|Nh\|Nm> \| <id-or-slug>]` | No args: list sessions with size/age. Args: delete all, by age, or by session ID. Sessions older than 30 days are also auto-pruned on plugin startup. |
| `/claude-code-recorder:record-doctor` | Verify dependencies, permissions (screen + mic checked independently via ffprobe), state, and disk usage. Repairs stale state automatically. |

A running recording is indicated by the **orange dot** in the macOS menu bar (native macOS screen-capture indicator).

## How it works

1. `/record` spawns `ffmpeg` (fully detached via `nohup` + `disown`) capturing screen 0 + mic 0 to `~/.cache/recorder/sessions/<id>/video.mp4`. State is persisted atomically to `~/.cache/recorder/state.json`.
2. `/record` again sends SIGINT to the ffmpeg PID (lets it flush the MP4 moov atom), clears state, then runs the pipeline:
   - **transcribe** — extract 16 kHz mono WAV via ffmpeg, run `whisper-cli` → `transcript.json` with per-segment timestamps.
   - **extract_frames** — find scene-change timestamps (`select=gt(scene,0.4)` ffmpeg filter) and deictic-word timestamps in the transcript (`here|this|notice|look at|see|watch|click|type|press`); dedup within 2s windows; optionally dedup near-identical frames via perceptual hash; emit `frames/*.png` + `frames.json`.
   - **assemble** — interleave transcript segments with screenshot paths chronologically into `prompt.md`.
3. The slash command prints `prompt.md` to stdout, which CC injects as the user's prompt. Claude automatically `Read`s the absolute-path screenshot references to view them.

## Output format example

```markdown
# Screen demo — fix checkout 500 — 2026-04-18 14:32 — 47s

[00:00] Opening the checkout page locally.
[00:03] ![frame_003.png](/Users/you/.cache/recorder/sessions/20260418-143200-fix-checkout-500/frames/frame_003.png)
[00:05] I'm clicking the Submit button — notice the button turns red.
[00:05] ![frame_005.png](...)
[00:12] Expected: green success banner. Actual: console shows a 500.
[00:12] ![frame_012.png](...)

Session dir: /Users/you/.cache/recorder/sessions/20260418-143200-fix-checkout-500/
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `NOT WORKING — no capture output` from `/record-doctor` | Screen Recording or Microphone permission denied for the terminal-host app. | Grant in System Settings → Privacy & Security. If app isn't listed: remove via `-` (Screen Recording) or `tccutil reset` (Microphone). Quit and relaunch the terminal host. |
| `/record` outputs "0s" with warnings about missing transcript/frames. | The recording's MP4 was corrupt (no moov atom) or ffmpeg died mid-init. | Check `ffmpeg.log` in the session dir. Usually fixes itself after permissions are granted. |
| Plugin install error: `Invalid input: expected object, received string` | CC plugin schema validation failure on `author` or other fields. | Ensure `plugin.json` has `"author": {"name": "..."}` (object, not string). |
| Slash command fails with `python3: command not found` | System lacks Python 3. | macOS normally ships 3.9; otherwise `brew install python@3.11`. |

Session artifacts are kept under `~/.cache/recorder/sessions/` until you clean them up; `video.mp4` + `audio.wav` stay even after `prompt.md` is produced so you can re-process or inspect.

## Development

```bash
git clone <repo>
cd claude-code-recorder
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest           # unit tests (62 tests, <1s)
.venv/bin/pytest -m e2e    # full pipeline against a real fixture (opt-in)
```

Design, plan, and post-mortem live under `docs/superpowers/`.

## Non-goals (v1)

- Cross-platform: macOS only.
- Recording editing / trimming: use the raw `video.mp4` if you need it.
- Replacing CC's built-in `/voice`: that's for live prompt dictation; this is async demo capture.
- Uploading audio for transcription: Whisper runs locally.
