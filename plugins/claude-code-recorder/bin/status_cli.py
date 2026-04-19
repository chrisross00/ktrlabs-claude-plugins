"""CLI for /record-status: inspect the currently-active recording without stopping it."""
from __future__ import annotations

import subprocess
import sys
import time

from bin.devices import DeviceDetectionError, detect_devices
from bin.paths import plugin_data_root, session_dir
from bin.state import is_process_alive, load_state


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n} TB"


def _format_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


def _measure_mic_level() -> str | None:
    """Side-channel 1s mic capture + volumedetect filter. Returns a short
    human-readable mean-volume string (e.g. '-21.3 dB') or None on failure.

    macOS typically allows concurrent mic access across processes, so running
    this while the main recording is active should not disrupt ffmpeg.
    """
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        return None
    try:
        devices = detect_devices()
    except DeviceDetectionError:
        return None

    try:
        result = subprocess.run(
            [
                str(ffmpeg), "-y", "-nostdin",
                "-f", "avfoundation",
                "-i", f":{devices.mic_index}",
                "-t", "0.5",
                "-af", "volumedetect",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return None

    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            tail = line.split("mean_volume:", 1)[1].strip()
            return tail  # e.g. "-21.3 dB"
    return None


def _interpret_mic_level(level_str: str) -> str:
    """Append a human hint so muted/quiet mic is obvious."""
    try:
        # "-21.3 dB" → -21.3
        db = float(level_str.replace("dB", "").strip())
    except ValueError:
        return level_str
    if db < -60:
        return f"{level_str}  ⚠ very quiet / likely muted"
    if db < -40:
        return f"{level_str}  (quiet — speak louder or move closer)"
    return f"{level_str}  (OK)"


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        print("No active recording. Start one with /claude-code-recorder:record [title]")
        return 0

    sdir = session_dir(state.session_id)
    # During recording, ffmpeg writes to video_NNN.mp4 chunk files; the
    # concatenated video.mp4 is only produced after stop. Report total size
    # across all existing sources.
    video_size = 0
    final = sdir / "video.mp4"
    if final.exists():
        video_size = final.stat().st_size
    for chunk in sdir.glob("video_*.mp4"):
        video_size += chunk.stat().st_size
    elapsed = time.time() - state.started_at

    alive = is_process_alive(state.pid)
    status_line = "alive" if alive else "DEAD (stale state — run /record-doctor)"

    print(f"Recording session: {state.session_id}")
    print(f"Elapsed:           {_format_elapsed(elapsed)}")
    print(f"Video size:        {_format_size(video_size)}")
    print(f"ffmpeg pid {state.pid}: {status_line}")

    if alive:
        level = _measure_mic_level()
        if level:
            print(f"Mic level:         {_interpret_mic_level(level)}")
        else:
            print("Mic level:         (could not probe)")

    print("Stop with: /claude-code-recorder:record")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
