"""CLI for /record-doctor: diagnostics and cleanup."""
from __future__ import annotations

import sys

from bin.bootstrap import check_and_install
from bin.paths import plugin_data_root, sessions_root
from bin.state import clear_state, is_process_alive, load_state


def _check_deps() -> list[str]:
    lines = ["Dependencies:"]
    for rel in ["bin/ffmpeg", "bin/whisper", "models/ggml-small.en.bin"]:
        path = plugin_data_root() / rel
        status = "OK" if path.exists() else "MISSING"
        lines.append(f"  {rel}: {status}")
    return lines


def _check_state() -> list[str]:
    lines = ["State:"]
    state = load_state()
    if state is None:
        lines.append("  Idle.")
        return lines
    if is_process_alive(state.pid):
        lines.append(f"  Active recording (pid {state.pid}, session {state.session_id}).")
    else:
        clear_state()
        lines.append(f"  Stale state (pid {state.pid} dead) — cleared.")
    return lines


def _check_disk() -> list[str]:
    lines = ["Disk usage:"]
    root = sessions_root()
    if not root.exists():
        lines.append("  No sessions.")
        return lines
    total = 0
    count = 0
    for d in root.iterdir():
        if d.is_dir():
            count += 1
            for p in d.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
    mb = total / (1024 * 1024)
    lines.append(f"  {count} session(s), {mb:.1f} MB total.")
    return lines


def main(argv: list[str]) -> int:
    exit_code = 0
    print("claude-code-recorder diagnostics")
    print("=" * 40)

    try:
        check_and_install()
        print("Bootstrap: OK")
    except Exception as e:
        print(f"Bootstrap: FAILED — {e}", file=sys.stderr)
        exit_code = 1

    for section in (_check_deps(), _check_state(), _check_disk()):
        print()
        for line in section:
            print(line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
