"""CLI for /record-doctor: diagnostics and cleanup."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

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


def _check_permissions() -> list[str]:
    """Probe avfoundation briefly to surface macOS permission state.

    Runs a 0.5s ffmpeg capture to a throwaway file. Valid capture (>50KB) means
    Screen Recording + Microphone are granted. Empty or tiny output means at
    least one was denied / hasn't been approved yet.
    """
    lines = ["Permissions (macOS avfoundation probe):"]
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        lines.append("  ffmpeg not installed — bootstrap first.")
        return lines

    with tempfile.TemporaryDirectory(prefix="cc-recorder-probe-") as tmp:
        out = Path(tmp) / "probe.mp4"
        try:
            result = subprocess.run(
                [
                    str(ffmpeg), "-y", "-nostdin",
                    "-f", "avfoundation", "-framerate", "30",
                    "-i", "1:0", "-t", "0.5",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            lines.append("  TIMEOUT — avfoundation produced no frames in 15s.")
            lines.append("  On macOS this almost always means Screen Recording")
            lines.append("  is DENIED (CLI tools never trigger the permission")
            lines.append("  dialog; the parent terminal/Claude Code app must be")
            lines.append("  granted access).")
            lines.append("")
            lines.append("  Open System Settings → Privacy & Security → Screen")
            lines.append("  Recording, add/enable the app hosting Claude Code,")
            lines.append("  restart that app, then rerun /record-doctor.")
            return lines

        size = out.stat().st_size if out.exists() else 0

    if size > 50_000 and result.returncode == 0:
        lines.append(f"  OK (probe captured {size // 1024} KB in 0.5s)")
        return lines

    # Failure path — surface the last few stderr lines + remediation.
    lines.append(f"  NOT WORKING (probe produced {size} bytes, ffmpeg exit {result.returncode})")
    tail = [line for line in result.stderr.splitlines() if line.strip()][-4:]
    for line in tail:
        lines.append(f"    {line}")
    lines.append("")
    lines.append("  To grant permissions on macOS:")
    lines.append("    System Settings → Privacy & Security → Screen Recording → enable for Claude Code / Terminal")
    lines.append("    System Settings → Privacy & Security → Microphone → same")
    lines.append("  Then rerun /record-doctor to verify.")
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

    for section in (_check_deps(), _check_permissions(), _check_state(), _check_disk()):
        print()
        for line in section:
            print(line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
