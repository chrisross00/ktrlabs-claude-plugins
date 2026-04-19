"""CLI for /record-doctor: diagnostics only (read-only + stale-state cleanup).

For first-run install and permission prompting, see /record-setup.
"""
from __future__ import annotations

import sys

from bin.paths import plugin_data_root, sessions_root
from bin.probe import permission_remediation_lines, run_probe
from bin.state import clear_state, is_process_alive, load_state


def _check_deps() -> list[str]:
    lines = ["Dependencies:"]
    for rel in ["bin/ffmpeg", "bin/whisper", "models/ggml-small.en.bin"]:
        path = plugin_data_root() / rel
        status = "OK" if path.exists() else "MISSING"
        lines.append(f"  {rel}: {status}")
    lines.append("  (run /record-setup to install if MISSING)")
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


def _check_permissions() -> list[str]:
    lines = ["Permissions (macOS avfoundation probe):"]
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        lines.append("  skipped — ffmpeg not installed. Run /record-setup first.")
        return lines
    result = run_probe()
    if result.captured:
        lines.append(f"  OK — captured {result.bytes_seen} bytes during probe.")
        return lines
    lines.append(f"  NOT WORKING — only {result.bytes_seen} bytes captured.")
    for stderr_line in result.stderr_tail:
        lines.append(f"    {stderr_line}")
    lines.append("")
    for line in permission_remediation_lines():
        lines.append(f"  {line}")
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
    print("claude-code-recorder diagnostics")
    print("=" * 40)
    for section in (_check_deps(), _check_permissions(), _check_state(), _check_disk()):
        print()
        for line in section:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
