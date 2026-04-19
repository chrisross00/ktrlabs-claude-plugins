"""Detect avfoundation screen and microphone device indices at runtime.

Hardcoding indices (e.g. "1:0") breaks on Macs with external monitors, webcams,
or audio interfaces — avfoundation reassigns indices based on what's connected.
We parse ffmpeg's device listing and match by name instead.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from bin.paths import bin_dir


@dataclass(frozen=True)
class Devices:
    screen_index: int
    mic_index: int

    @property
    def ffmpeg_input(self) -> str:
        return f"{self.screen_index}:{self.mic_index}"


def parse_device_listing(stderr: str) -> dict[str, list[tuple[int, str]]]:
    """Parse ffmpeg stderr into {"video": [(idx, name), ...], "audio": [...]}."""
    sections: dict[str, list[tuple[int, str]]] = {"video": [], "audio": []}
    current: str | None = None
    for line in stderr.splitlines():
        if "AVFoundation video devices:" in line:
            current = "video"
            continue
        if "AVFoundation audio devices:" in line:
            current = "audio"
            continue
        if current is None:
            continue
        # Device lines look like: "[AVFoundation indev @ ...] [1] Capture screen 0"
        m = re.search(r"\[(\d+)\]\s+(.+?)\s*$", line)
        if m:
            sections[current].append((int(m.group(1)), m.group(2).strip()))
    return sections


def _first_matching(devices: list[tuple[int, str]], pattern: str) -> int | None:
    for idx, name in devices:
        if re.search(pattern, name, re.IGNORECASE):
            return idx
    return None


def pick_screen(video_devices: list[tuple[int, str]]) -> int | None:
    """Prefer 'Capture screen' devices; fall back to anything with 'screen'."""
    exact = _first_matching(video_devices, r"capture screen")
    if exact is not None:
        return exact
    return _first_matching(video_devices, r"screen")


def pick_mic(audio_devices: list[tuple[int, str]]) -> int | None:
    """Prefer the built-in microphone; fall back to the first audio input."""
    builtin = _first_matching(audio_devices, r"microphone")
    if builtin is not None:
        return builtin
    return audio_devices[0][0] if audio_devices else None


def list_devices() -> dict[str, list[tuple[int, str]]]:
    """Invoke ffmpeg to enumerate avfoundation devices. Returns parsed sections."""
    # ffmpeg exits non-zero because we pass "" as input — that's expected.
    result = subprocess.run(
        [
            str(bin_dir() / "ffmpeg"),
            "-hide_banner",
            "-f", "avfoundation",
            "-list_devices", "true",
            "-i", "",
        ],
        capture_output=True,
        text=True,
    )
    return parse_device_listing(result.stderr)


class DeviceDetectionError(RuntimeError):
    pass


def detect_devices() -> Devices:
    """Return screen + mic indices, or raise with a readable listing on failure."""
    listing = list_devices()
    screen = pick_screen(listing["video"])
    mic = pick_mic(listing["audio"])
    if screen is None:
        raise DeviceDetectionError(
            f"No screen-capture device found. Video devices: {listing['video']}"
        )
    if mic is None:
        raise DeviceDetectionError(
            f"No audio input device found. Audio devices: {listing['audio']}"
        )
    return Devices(screen_index=screen, mic_index=mic)
