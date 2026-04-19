"""Brief avfoundation probe shared by /record-setup and /record-doctor.

Spawns ffmpeg, polls the output file for growth up to PROBE_WAIT_S, then
stops ffmpeg. Returns whether bytes were actually captured (permission OK)
plus ffmpeg's stderr tail so callers can surface diagnostics.
"""
from __future__ import annotations

import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from bin.paths import plugin_data_root

PROBE_WAIT_S = 6.0
PROBE_MIN_BYTES = 5_000


@dataclass(frozen=True)
class ProbeResult:
    captured: bool
    bytes_seen: int
    stderr_tail: list[str]


def run_probe() -> ProbeResult:
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        return ProbeResult(captured=False, bytes_seen=0, stderr_tail=["ffmpeg not installed"])

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

        deadline = time.time() + PROBE_WAIT_S
        captured_bytes = 0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            if out.exists():
                captured_bytes = out.stat().st_size
                if captured_bytes >= PROBE_MIN_BYTES:
                    break
            time.sleep(0.2)

        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        final_bytes = out.stat().st_size if out.exists() else 0
        stderr_text = err_log.read_text(errors="replace")

    best = max(captured_bytes, final_bytes)
    tail = [ln for ln in stderr_text.splitlines() if ln.strip()][-4:]
    return ProbeResult(
        captured=best >= PROBE_MIN_BYTES,
        bytes_seen=best,
        stderr_tail=tail,
    )


def permission_remediation_lines() -> list[str]:
    """Shared remediation copy for denied permissions."""
    return [
        "CLI tools never trigger macOS permission dialogs — the parent app",
        "(e.g. cmux, Terminal, iTerm) hosting Claude Code must be granted:",
        "  System Settings → Privacy & Security → Screen Recording",
        "  System Settings → Privacy & Security → Microphone",
        "If the app isn't listed: use the + button, or quit+relaunch it, then retry.",
        "If listed+off with no - button (mic pane): tccutil reset Microphone <bundle-id>",
        "  (find bundle-id via `mdls -name kMDItemCFBundleIdentifier -r /Applications/<app>.app`)",
    ]
