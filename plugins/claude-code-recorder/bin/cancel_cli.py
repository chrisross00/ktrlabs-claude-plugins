"""CLI for /record-cancel: stop the active recording and delete its session
directory without running the pipeline. For when you realize mid-recording
that you want to start over.
"""
from __future__ import annotations

import shutil
import sys

from bin.paths import session_dir
from bin.record_toggle import _stop_ffmpeg
from bin.state import clear_state, is_process_alive, load_state


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        print("No active recording to cancel.")
        return 0

    if is_process_alive(state.pid):
        _stop_ffmpeg(state.pid)

    clear_state()

    sdir = session_dir(state.session_id)
    if sdir.exists():
        shutil.rmtree(sdir)
        print(f"Cancelled recording; deleted session {state.session_id}.")
    else:
        print(f"Cancelled recording; session {state.session_id} had no directory to delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
