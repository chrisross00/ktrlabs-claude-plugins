"""Brief avfoundation probe shared by /record-setup and /record-doctor.

Spawns ffmpeg, polls the output file for growth up to PROBE_WAIT_S, then
stops ffmpeg. Uses ffprobe to check which streams actually made it into
the file so Screen Recording and Microphone permissions are reported
independently (size alone can pass on mic-only output).
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
    screen_ok: bool
    mic_ok: bool
    bytes_seen: int
    stderr_tail: list[str]

    @property
    def captured(self) -> bool:
        """Both permissions working."""
        return self.screen_ok and self.mic_ok


def _ffprobe_has_stream(ffprobe: Path, media: Path, kind: str) -> bool:
    """kind is 'v' (video) or 'a' (audio)."""
    result = subprocess.run(
        [
            str(ffprobe), "-v", "error",
            "-select_streams", kind,
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(media),
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def run_probe() -> ProbeResult:
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    # ffprobe lives next to ffmpeg in brew's prefix; when our bin/ffmpeg is
    # a symlink to brew, ffprobe is at the sibling path in the same bin dir.
    ffprobe = ffmpeg.resolve().parent / "ffprobe"
    if not ffmpeg.exists():
        return ProbeResult(False, False, 0, ["ffmpeg not installed"])

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
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            if out.exists() and out.stat().st_size >= PROBE_MIN_BYTES:
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

        if final_bytes >= PROBE_MIN_BYTES and ffprobe.exists() and out.exists():
            screen_ok = _ffprobe_has_stream(ffprobe, out, "v")
            mic_ok = _ffprobe_has_stream(ffprobe, out, "a")
        else:
            screen_ok = mic_ok = False

    tail = [ln for ln in stderr_text.splitlines() if ln.strip()][-4:]
    return ProbeResult(
        screen_ok=screen_ok,
        mic_ok=mic_ok,
        bytes_seen=final_bytes,
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
