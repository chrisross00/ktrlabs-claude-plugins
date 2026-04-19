# Post-mortem: real-world bugs that 62 unit tests didn't catch

**Date**: 2026-04-18
**Context**: After the plan's 16 TDD tasks landed with 60/60 green tests, installing the plugin into a real Claude Code session surfaced 9 distinct bugs that would have blocked the plugin from working at all. This is the pattern analysis.

## The bugs

| # | Symptom | Root cause | Fix commit |
|---|---|---|---|
| 1 | Plugin install fails: `author: Invalid input: expected object, received string` | `plugin.json` schema requires `author` as object `{"name": "..."}`. Plan specified a string. | `6eced37` |
| 2 | First `/record` raises `RuntimeError: CLAUDE_PLUGIN_DATA not set` | CC sets `CLAUDE_PLUGIN_DATA` for hooks but not for slash-command bash. Our `plugin_data_root()` did a strict env-var check. | `fe3d962` |
| 3 | Tests required Python ≥3.11 but system `python3` is 3.9 | Plan assumed Python 3.11; macOS default is 3.9 via Xcode CLT. Code was 3.9-safe thanks to `from __future__ import annotations` — only the `pyproject.toml` constraint was wrong. | `fe3d962` |
| 4 | Bootstrap fails: `No such file or directory: /opt/homebrew/opt/whisper-cpp/bin/whisper-cpp` | Brew package `whisper-cpp` ships the binary as `whisper-cli`, not `whisper-cpp`. Plan hardcoded the wrong name. | `6139442` |
| 5 | First recording's MP4 had no moov atom | `ffmpeg` was being sent SIGKILL (or equivalent) before it could flush. Stdin on a closed pipe, stdout/stderr routed to DEVNULL — no diagnostic signal. | `158581f` |
| 6 | Recording immediately terminates to 0 bytes when spawned via slash command | CC slash-command bash reaps detached descendants more aggressively than the `Bash` tool. `subprocess.Popen(..., start_new_session=True)` was insufficient. | `e0e97f2` |
| 7 | `whisper` binary crashes on startup: `Library not loaded: @rpath/libwhisper.1.dylib` | We *copied* the binary from the brew prefix. Its `@rpath` lookup expects a sibling `lib/` directory that only exists at the original brew location. | `80bb076` |
| 8 | Pipeline fails: `No module named 'imagehash'` | Slash commands use whichever `python3` is on `PATH` (system 3.9 by default), not the plugin's venv. `imagehash` was declared in `pyproject.toml` but not available to system Python. | `da616dd` |
| 9 | On a fresh install, `/record` hangs with no frames captured | macOS only shows TCC permission dialogs **once per app**. If dismissed earlier, avfoundation silently blocks — no dialog, no error, no exit. CLI tools never trigger the dialog themselves; it's the parent app's permission. | `ed98376`, `0b7c9cd` |

## Root-cause categories

### A. Plan was wrong about an external schema or convention (1, 3, 4)

Bugs 1, 3, 4 were all "the plan specified X; reality required Y." The plan's values came from either stale documentation (whisper binary name) or best-guess assumptions (plugin schema, Python version). Tests couldn't catch these because tests match code against plan; plan itself was wrong.

**Guardrail**: Validate external contracts at CI time, not design time.
- Generate a `plugin.json` from templates and run it through CC's install path in CI (if feasible).
- Pin a known-good brew binary name by shell-probing in a test.
- Have CI run on both Python 3.9 and 3.11 minima to catch version-specific footguns.

### B. Plan assumed an API behaved the way its docs implied (2, 6, 8)

Bugs 2, 6, 8 all stem from "CC provides X to slash commands." Documentation said yes. Reality was more nuanced — `CLAUDE_PLUGIN_DATA` is hook-only, not slash-command; slash-command bash reaps descendants; slash-command bash runs under system `python3`, not our venv.

These were verified pre-implementation via the `claude-code-guide` subagent — but it's a LLM reading docs, not actually testing the behavior. The documented behavior and the empirical behavior differed.

**Guardrail**: Assume any documented behavior is a hint, not a contract. Before relying on an external runtime guarantee, *actually run a spike that exercises it*. We did this for one piece (process detachment) and caught a separate divergence from that very spike — reinforcing the lesson.

### C. Tests mocked the expensive parts and missed the integration surface (5, 7)

Bugs 5 and 7 were in code where every test was mocked: `_spawn_ffmpeg` was patched in every state-machine test; `install_whisper` was patched in bootstrap tests. The code "worked" under its mocks but the real binary and real subprocess lifecycle weren't exercised.

**Guardrail**:
- Add at least one **un-mocked integration test per layer**: actually spawn a short subprocess, actually produce a real file, actually verify stdin/stdout/fd semantics.
- Move heavily-mocked "does this call the function" assertions into a smaller layer; use real process work in a broader layer.

### D. Platform-specific UX the plan skipped (9)

macOS permission handling was in the design spec but never made it into a task — we implemented the happy path assuming permission was granted. Denial was invisible until a real install surfaced it.

**Guardrail**: Any task in the plan that says "first run" or "permission" or "install" should have an explicit sub-task for the denial/error branch, not just the success path. Add a design checklist: "for each external state the feature assumes (permissions, network, disk space), what is the denial UX?"

## Test improvements to add

Prioritized from highest-value to least:

1. **Binary-install smoke test**: in CI, actually run `bootstrap.install_whisper` against the symlink path and verify the resulting binary executes (`--help` returns 0). Would have caught bugs 4 and 7.
2. **Plugin manifest validation**: a test that loads `.claude-plugin/plugin.json` and asserts schema shape (types, required fields). Would have caught bug 1.
3. **Real subprocess detachment test**: spawn `sleep 30` via `_spawn_ffmpeg`'s production code, verify the resulting process has `PPID=1` within 1s, then SIGINT and verify it dies. Would have caught bug 6.
4. **Python-version matrix in CI**: run tests on 3.9, 3.10, 3.11. Would have caught bug 3 earlier.
5. **Paths smoke without env vars**: run `plugin_data_root()` with `CLAUDE_PLUGIN_DATA` unset and assert a sensible fallback path. Would have caught bug 2.
6. **E2E fixture test (Task 17)**: recording → transcribe → extract_frames → assemble against a real pre-recorded fixture, asserting a plausible `prompt.md`. Would have caught bugs 5, 7, and 8 collectively.

## Generalizable takeaway

The 62 unit tests gave **high confidence in internal logic correctness**, but near-zero confidence in **external integration correctness**. Mock-heavy TDD produces well-shaped code and fast feedback; it doesn't guarantee the code touches reality correctly.

For a platform plugin targeting 3000 engineers, ship-readiness requires at least one *real install and exercise* in the development environment before declaring done — not a substitute for unit tests, but complementary and irreplaceable. This exercise is what drove all 9 bugfixes above, found in ~90 minutes of testing that unit tests could not have caught in any duration.

**Rule of thumb for future plans**: budget "install the thing, use the thing, find 5 bugs you couldn't have predicted" as an explicit checkpoint in every plan with an external runtime contract.
