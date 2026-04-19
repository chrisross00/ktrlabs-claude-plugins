"""Brief avfoundation probe shared by /record-setup and /record-doctor.

Spawns ffmpeg, polls the output file for growth up to PROBE_WAIT_S, then
stops ffmpeg. Uses ffprobe to check which streams actually made it into
the file so Screen Recording and Microphone permissions are reported
independently (size alone can pass on mic-only output).

Also exposes `request_screen_access()` which invokes macOS's
CGRequestScreenCaptureAccess() — the documented API for triggering the
Screen Recording permission prompt. ffmpeg/avfoundation doesn't reliably
surface the prompt on modern macOS; calling the CG API directly does.
"""
from __future__ import annotations

import shutil
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


# macOS silently substitutes a dark-gray (~Y=17) buffer when Screen Recording
# is denied. ffmpeg's `blackdetect` filter identifies frames that are black or
# near-black using a configurable threshold. A legitimate desktop virtually
# never produces sustained 0.1s of >80% near-black pixels during a short probe.
def _video_is_black(ffmpeg: Path, video: Path) -> bool:
    """True iff the video is essentially all black (denied screen capture)."""
    result = subprocess.run(
        [
            str(ffmpeg), "-nostdin",
            "-i", str(video),
            "-vf", "blackdetect=d=0.1:pic_th=0.8:pix_th=0.1",
            "-an",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    return "black_start" in result.stderr


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
            has_video = _ffprobe_has_stream(ffprobe, out, "v")
            mic_ok = _ffprobe_has_stream(ffprobe, out, "a")
            if has_video:
                screen_ok = not _video_is_black(ffmpeg, out)
            else:
                screen_ok = False
        else:
            screen_ok = mic_ok = False

    tail = [ln for ln in stderr_text.splitlines() if ln.strip()][-4:]
    return ProbeResult(
        screen_ok=screen_ok,
        mic_ok=mic_ok,
        bytes_seen=final_bytes,
        stderr_tail=tail,
    )


def request_screen_access(timeout_s: float = 60.0) -> bool | None:
    """Invoke macOS `CGRequestScreenCaptureAccess()` via a swift one-liner.

    This is the documented API for triggering the Screen Recording permission
    prompt — it shows the system dialog when no TCC decision exists, or
    returns the cached decision silently otherwise.

    Returns:
        True  — access granted (prompted + allowed, or previously allowed)
        False — access denied (prompted + denied, or previously denied)
        None  — swift isn't available on this machine
    """
    swift = shutil.which("swift")
    if not swift:
        return None
    code = "import CoreGraphics; exit(CGRequestScreenCaptureAccess() ? 0 : 1)"
    try:
        result = subprocess.run(
            [swift, "-e", code],
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def request_microphone_access(timeout_s: float = 60.0) -> bool | None:
    """Invoke macOS `AVCaptureDevice.requestAccess(for: .audio)`.

    Same pattern as `request_screen_access` for the Microphone permission.
    Uses a completion handler, so the swift snippet waits on a semaphore.
    """
    swift = shutil.which("swift")
    if not swift:
        return None
    code = (
        "import AVFoundation\n"
        "import Foundation\n"
        "let sem = DispatchSemaphore(value: 0)\n"
        "var granted = false\n"
        "AVCaptureDevice.requestAccess(for: .audio) { ok in\n"
        "    granted = ok\n"
        "    sem.signal()\n"
        "}\n"
        "_ = sem.wait(timeout: .now() + 55)\n"
        "exit(granted ? 0 : 1)\n"
    )
    try:
        result = subprocess.run(
            [swift, "-e", code],
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def permission_remediation_lines() -> list[str]:
    """Shared remediation copy for denied permissions."""
    return [
        "CLI tools never trigger macOS permission dialogs — the parent app",
        "(e.g. cmux, Terminal, iTerm) hosting Claude Code must be granted:",
        "  System Settings → Privacy & Security → Screen Recording",
        "  System Settings → Privacy & Security → Microphone",
        "If the app isn't listed, use the + button or quit+relaunch it, then retry.",
        "If macOS has a cached decision and won't re-prompt, reset the TCC entry:",
        "  mdls -name kMDItemCFBundleIdentifier -r /Applications/<app>.app",
        "  tccutil reset ScreenCapture <bundle-id>   # for Screen Recording",
        "  tccutil reset Microphone    <bundle-id>   # for Microphone",
        "Note: Screen Recording capture that produces all-black frames means",
        "macOS silently denied it — the TCC reset above is the fix.",
    ]
