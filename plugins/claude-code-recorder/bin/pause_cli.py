"""CLI for /record-pause: pause the active recording without running the
pipeline. Resume with /claude-code-recorder:record."""
from __future__ import annotations

import sys

from bin.record_toggle import pause_recording
from bin.state import load_state


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        print("No active recording to pause.")
        return 0
    if state.is_paused:
        print("Recording is already paused. Run /claude-code-recorder:record to resume.")
        return 0
    if pause_recording():
        print(
            f"Paused recording (session: {state.session_id}).\n"
            "Resume with /claude-code-recorder:record, discard with /claude-code-recorder:record-cancel."
        )
    else:
        print("Could not pause — state may have changed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
