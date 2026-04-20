# Backlog — claude-code-recorder

Deferred items after v0.3.0, roughly ordered by expected impact.

## Correctness / reliability

- **Model upgrade path.** Bootstrap only verifies existing hashes; no migration if a future version needs a newer model. Add a version-keyed manifest for long-term maintainability.

## UX / polish

- **Perceptual dedup effectively disabled** under system Python because `imagehash` isn't installed. Vendor `imagehash` in the plugin or ship a bundled Python env so the dedup pass actually runs.

## Performance

- **Pipeline is sequential.** `transcribe` and `extract_frames` are independent; could run in parallel for ~30% speedup on long recordings.
- **ffmpeg log unbounded** within a session. Rotate after a size threshold.

## Distribution / operations

- **Integration-test gap** (from the post-mortem). 81 unit tests still mostly mocked. Until binary-install smoke, real-subprocess-detachment, and E2E-fixture tests land, regressions will ship the same way v0.1.0 did.
- **No telemetry.** Zero signal at scale. Anthropic's plugin ecosystem doesn't provide a mechanism yet — if/when they do, revisit.
- **No plugin signing.** Any CC install is full-trust. Anthropic's plugin ecosystem doesn't provide signing yet — revisit if that changes.
- **Plan/spec drift.** `docs/superpowers/specs/` and `plans/` predate the 9 post-mortem bugfixes plus the v0.2.0 and v0.3.0 improvements. Either update or archive.

## Done in 0.3.0

- ~~Multilingual transcription~~ — switched default to `ggml-tiny.bin` (multilingual).
- ~~Shrink first-run footprint~~ — `tiny` is ~75 MB vs `small.en`'s ~500 MB.
- ~~Brittle brew binary discovery~~ — `install_whisper` now tries `whisper-cli`, `whisper-cpp`, `main` in order.
- ~~Frame cue list too broad~~ — tightened to action-verbs + pointing phrases; dropped bare "this/here/see".
- ~~Auto-prune old sessions~~ — sessions older than 30 days removed by SessionStart hook.
- ~~Audio-level feedback~~ — `/record-status` now includes a mean-volume probe with muted-mic warning.
- ~~Pause/resume~~ — `/record-pause` + `/record` (when paused) writes discrete chunks; `stop_recording` concats via ffmpeg's concat demuxer.
