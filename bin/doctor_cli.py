"""CLI for /record-doctor: diagnostics and cleanup."""
from __future__ import annotations

import signal
import subprocess
import sys
import tempfile
import time
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


_PROBE_WAIT_S = 6.0  # max time to wait for bytes to flow
_PROBE_MIN_BYTES = 5_000  # output needed to declare "captured"


def _check_permissions() -> list[str]:
    """Probe avfoundation by watching output file size grow, not by waiting
    for ffmpeg to finish. Avoids false-timeout on slow device init.
    """
    lines = ["Permissions (macOS avfoundation probe):"]
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        lines.append("  ffmpeg not installed — bootstrap first.")
        return lines

    with tempfile.TemporaryDirectory(prefix="cc-recorder-probe-") as tmp:
        out = Path(tmp) / "probe.mp4"
        err_log = Path(tmp) / "ffmpeg.stderr"
        with open(err_log, "wb") as err_f:
            proc = subprocess.Popen(
                [
                    str(ffmpeg), "-y", "-nostdin",
                    "-f", "avfoundation", "-framerate", "30",
                    "-i", "1:0",
                    str(out),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err_f,
            )

        # Poll for output-file growth up to _PROBE_WAIT_S.
        deadline = time.time() + _PROBE_WAIT_S
        captured_bytes = 0
        while time.time() < deadline:
            if proc.poll() is not None:
                break  # ffmpeg died — permission denied or other failure
            if out.exists():
                captured_bytes = out.stat().st_size
                if captured_bytes >= _PROBE_MIN_BYTES:
                    break
            time.sleep(0.2)

        # Stop ffmpeg (SIGINT for clean MP4 shutdown) so the probe is cheap.
        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        final_bytes = out.stat().st_size if out.exists() else 0
        stderr_text = err_log.read_text(errors="replace")

    if captured_bytes >= _PROBE_MIN_BYTES or final_bytes >= _PROBE_MIN_BYTES:
        lines.append(f"  OK — avfoundation captured {max(captured_bytes, final_bytes)} bytes.")
        return lines

    lines.append(
        f"  NOT WORKING — no capture output after {_PROBE_WAIT_S}s "
        f"(got {final_bytes} bytes)."
    )
    tail = [ln for ln in stderr_text.splitlines() if ln.strip()][-4:]
    for line in tail:
        lines.append(f"    {line}")
    lines.append("")
    lines.append("  If ffmpeg logged nothing at all, permission is DENIED")
    lines.append("  (CLI tools never trigger macOS permission dialogs — the")
    lines.append("  parent app like cmux/Terminal must be granted):")
    lines.append("    System Settings → Privacy & Security → Screen Recording")
    lines.append("    System Settings → Privacy & Security → Microphone")
    lines.append("  If the app isn't listed: the `+` button or quit+relaunch.")
    lines.append("  If it's listed but toggled off and mic has no `-` button,")
    lines.append("  use: tccutil reset Microphone <bundle-id>  (outside CC).")
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
