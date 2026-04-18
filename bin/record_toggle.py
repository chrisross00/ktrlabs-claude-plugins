"""Record start/stop toggle. Invoked by the /record slash command."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

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
    """Spawn ffmpeg in background. Returns PID."""
    cmd = [
        str(bin_dir() / "ffmpeg"),
        "-y",
        "-f", "avfoundation",
        "-framerate", "30",
        "-i", "1:0",  # screen dev 1, mic dev 0 (macOS default)
        str(video_path),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def start_recording(title: str | None) -> str:
    """Create session dir, spawn ffmpeg, persist state. Returns session_id."""
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

    video_path = sdir / "video.mp4"
    pid = _spawn_ffmpeg(video_path)
    save_state(State(pid=pid, session_id=session_id, started_at=time.time()))
    return session_id
