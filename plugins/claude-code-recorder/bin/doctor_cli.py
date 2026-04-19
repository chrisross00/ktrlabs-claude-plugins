"""CLI for /record-doctor: diagnostics and cleanup."""
from __future__ import annotations

import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bin.bootstrap import MODEL_PATH_REL, check_and_install
from bin.devices import DeviceDetectionError, detect_devices
from bin.paths import plugin_data_root, sessions_root
from bin.state import clear_state, is_process_alive, load_state


def _check_deps() -> list[str]:
    lines = ["Dependencies:"]
    for rel in ["bin/ffmpeg", "bin/whisper", f"models/{MODEL_PATH_REL}"]:
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


def _check_permissions() -> list[str]:
    """Probe avfoundation, then verify video + audio streams independently so
    screen-only denial vs mic-only denial vs both-denied each report clearly.
    """
    lines = ["Permissions (macOS avfoundation probe):"]
    ffmpeg = plugin_data_root() / "bin" / "ffmpeg"
    if not ffmpeg.exists():
        lines.append("  ffmpeg not installed — bootstrap first.")
        return lines

    try:
        devices = detect_devices()
    except DeviceDetectionError as e:
        lines.append(f"  Device detection failed: {e}")
        return lines

    ffprobe = ffmpeg.resolve().parent / "ffprobe"

    with tempfile.TemporaryDirectory(prefix="cc-recorder-probe-") as tmp:
        out = Path(tmp) / "probe.mp4"
        err_log = Path(tmp) / "ffmpeg.stderr"
        with open(err_log, "wb") as err_f:
            proc = subprocess.Popen(
                [
                    str(ffmpeg), "-y", "-nostdin",
                    "-f", "avfoundation", "-framerate", "30",
                    "-i", devices.ffmpeg_input,
                    str(out),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err_f,
            )

        # Poll for output growth up to _PROBE_WAIT_S.
        deadline = time.time() + _PROBE_WAIT_S
        captured_bytes = 0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            if out.exists():
                captured_bytes = out.stat().st_size
                if captured_bytes >= _PROBE_MIN_BYTES:
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

        has_video = False
        has_audio = False
        if ffprobe.exists() and final_bytes > 0:
            has_video = _ffprobe_has_stream(ffprobe, out, "v")
            has_audio = _ffprobe_has_stream(ffprobe, out, "a")

    lines.append(f"  Probed devices: video={devices.screen_index}, audio={devices.mic_index}")
    lines.append(f"  Captured {final_bytes} bytes in up to {_PROBE_WAIT_S}s.")
    lines.append(f"  Screen Recording: {'OK' if has_video else 'DENIED'}")
    lines.append(f"  Microphone:       {'OK' if has_audio else 'DENIED'}")

    if has_video and has_audio:
        return lines

    lines.append("")
    lines.append("  Remediation (macOS):")
    if not has_video:
        lines.append("    • System Settings → Privacy & Security → Screen Recording")
        lines.append("      Add or enable the app that hosts Claude Code (cmux/")
        lines.append("      Terminal/iTerm). Use `+` or remove+relaunch to force")
        lines.append("      a fresh permission prompt.")
    if not has_audio:
        lines.append("    • System Settings → Privacy & Security → Microphone")
        lines.append("      The Microphone pane has no `-` button. To force a")
        lines.append("      fresh prompt for an app:")
        lines.append("        mdls -name kMDItemCFBundleIdentifier -r /Applications/<app>.app")
        lines.append("        tccutil reset Microphone <bundle-id>")
        lines.append("      Run these from a Terminal outside Claude Code.")
    if stderr_text.strip():
        lines.append("")
        lines.append("  Last ffmpeg stderr lines:")
        for ln in [line for line in stderr_text.splitlines() if line.strip()][-4:]:
            lines.append(f"    {ln}")
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
