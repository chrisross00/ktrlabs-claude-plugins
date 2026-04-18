"""CLI entry for /record slash command. Prints output CC injects as prompt."""
from __future__ import annotations

import sys
from pathlib import Path

from bin.record_toggle import start_recording, stop_recording
from bin.state import load_state


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        title = " ".join(argv).strip() or None
        session_id = start_recording(title=title)
        print(f"Recording started (session: {session_id}). Run /record again to stop.")
        return 0

    if argv:
        print("Stopping active session — title argument ignored.", file=sys.stderr)
    sdir = stop_recording()
    if sdir is None:
        print("No active recording found.", file=sys.stderr)
        return 0
    prompt_path = sdir / "prompt.md"
    if prompt_path.exists():
        print(prompt_path.read_text())
    else:
        print(f"Recording stopped but prompt not generated. Session: {sdir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
