"""CLI for /record-status: inspect the currently-active recording without stopping it."""
from __future__ import annotations

import sys
import time

from bin.paths import session_dir
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


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        print("No active recording. Start one with /claude-code-recorder:record [title]")
        return 0

    sdir = session_dir(state.session_id)
    video = sdir / "video.mp4"
    video_size = video.stat().st_size if video.exists() else 0
    elapsed = time.time() - state.started_at

    alive = is_process_alive(state.pid)
    status_line = "alive" if alive else "DEAD (stale state — run /record-doctor)"

    print(f"Recording session: {state.session_id}")
    print(f"Elapsed:           {_format_elapsed(elapsed)}")
    print(f"Video size:        {_format_size(video_size)}")
    print(f"ffmpeg pid {state.pid}: {status_line}")
    print("Stop with: /claude-code-recorder:record")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
