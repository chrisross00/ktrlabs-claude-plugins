"""Record start/stop toggle. Invoked by the /record slash command."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from bin import state as _state_mod
from bin.devices import detect_devices
from bin.paths import bin_dir, session_dir, sessions_root
from bin.slug import slugify
from bin.state import State, save_state


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_session_id(base: str) -> str:
    """Return `base` if free, else `base-2`, `base-3`, …"""
    if not session_dir(base).exists():
        return base
    n = 2
    while session_dir(f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def _spawn_ffmpeg(video_path: Path) -> int:
    """Spawn ffmpeg fully detached via nohup + disown so it survives
    when the spawning slash-command bash reaps its children.

    Returns the ffmpeg PID (read from a pidfile the shell wrote).
    """
    ffmpeg = str(bin_dir() / "ffmpeg")
    log_path = video_path.parent / "ffmpeg.log"
    pid_path = video_path.parent / "ffmpeg.pid"
    devices = detect_devices()
    # Quote every path to tolerate spaces. Use bash -c so nohup/disown work.
    shell_cmd = (
        f'nohup "{ffmpeg}" -y -nostdin -f avfoundation -framerate 30 '
        f'-i "{devices.ffmpeg_input}" "{video_path}" '
        f'>"{log_path}" 2>&1 & '
        f'echo $! > "{pid_path}"; disown'
    )
    subprocess.run(
        ["/bin/bash", "-c", shell_cmd],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Tiny wait so the pidfile is definitely written (bash already returned,
    # but just in case the OS hasn't flushed the single write).
    for _ in range(20):
        if pid_path.exists() and pid_path.read_text().strip():
            break
        time.sleep(0.05)
    return int(pid_path.read_text().strip())


def _next_chunk_path(sdir: Path) -> Path:
    """Return the next `video_NNN.mp4` path not yet used in sdir."""
    existing = sorted(sdir.glob("video_*.mp4"))
    n = len(existing)
    return sdir / f"video_{n:03d}.mp4"


def start_recording(title: str | None) -> str:
    """Create session dir, spawn ffmpeg writing video_000.mp4, persist state."""
    base = _timestamp()
    if title:
        base = f"{base}-{slugify(title)}"
    session_id = _unique_session_id(base)
    sdir = session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "session_id": session_id,
        "title": title or "",
        "started_at": time.time(),
    }
    (sdir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    chunk = _next_chunk_path(sdir)  # video_000.mp4 on first call
    pid = _spawn_ffmpeg(chunk)
    save_state(State(
        pid=pid, session_id=session_id, started_at=time.time(), is_paused=False,
    ))
    return session_id


def pause_recording() -> bool:
    """Stop ffmpeg cleanly, mark state as paused. Returns True if paused,
    False if idle / already paused / process dead."""
    state_obj = _state_mod.load_state()
    if state_obj is None or state_obj.is_paused:
        return False
    if not _state_mod.is_process_alive(state_obj.pid):
        _state_mod.clear_state()
        return False
    _stop_ffmpeg(state_obj.pid)
    save_state(State(
        pid=state_obj.pid,
        session_id=state_obj.session_id,
        started_at=state_obj.started_at,
        is_paused=True,
    ))
    return True


def resume_recording() -> bool:
    """Spawn a new ffmpeg writing the next chunk; clear paused flag. Returns
    True if resumed, False if nothing to resume."""
    state_obj = _state_mod.load_state()
    if state_obj is None or not state_obj.is_paused:
        return False
    sdir = session_dir(state_obj.session_id)
    chunk = _next_chunk_path(sdir)
    pid = _spawn_ffmpeg(chunk)
    save_state(State(
        pid=pid,
        session_id=state_obj.session_id,
        started_at=state_obj.started_at,
        is_paused=False,
    ))
    return True


def _concat_chunks(sdir: Path) -> None:
    """Produce sdir/video.mp4 from sdir/video_*.mp4. Deletes chunks on success."""
    chunks = sorted(sdir.glob("video_*.mp4"))
    if not chunks:
        return
    final = sdir / "video.mp4"
    if len(chunks) == 1:
        chunks[0].rename(final)
        return
    listing = sdir / "chunks.txt"
    listing.write_text("\n".join(f"file '{c.resolve()}'" for c in chunks) + "\n")
    subprocess.run(
        [
            str(bin_dir() / "ffmpeg"), "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(listing),
            "-c", "copy",
            str(final),
        ],
        check=True,
        capture_output=True,
    )
    listing.unlink(missing_ok=True)
    for c in chunks:
        c.unlink(missing_ok=True)


def _stop_ffmpeg(pid: int, timeout_s: float = 10.0) -> None:
    """Send SIGINT (lets ffmpeg flush the MP4 moov atom), then wait."""
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _state_mod.is_process_alive(pid):
            return
        time.sleep(0.1)
    # Escalate if ffmpeg won't exit cleanly.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_pipeline(sdir: Path) -> None:
    """Import lazily so start-path doesn't pay pipeline import cost."""
    from bin.pipeline.transcribe import transcribe
    from bin.pipeline.extract_frames import extract_frames
    from bin.pipeline.assemble import assemble

    try:
        transcribe(sdir)
    except Exception as e:
        (sdir / "transcribe.error.txt").write_text(str(e))

    try:
        extract_frames(sdir)
    except Exception as e:
        (sdir / "extract_frames.error.txt").write_text(str(e))

    # assemble always runs — it handles upstream errors.
    assemble(sdir)


def stop_recording() -> Path | None:
    """Stop active recording (or paused session), concat chunks, run pipeline.
    Returns session dir or None if there was nothing to stop."""
    state_obj = _state_mod.load_state()
    if state_obj is None:
        return None

    if state_obj.is_paused:
        # ffmpeg already terminated at pause time; no process to signal.
        pass
    elif not _state_mod.is_process_alive(state_obj.pid):
        _state_mod.clear_state()
        return None
    else:
        _stop_ffmpeg(state_obj.pid)

    _state_mod.clear_state()

    sdir = session_dir(state_obj.session_id)
    _concat_chunks(sdir)
    _run_pipeline(sdir)
    return sdir
