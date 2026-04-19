from __future__ import annotations

import pytest

from bin.devices import (
    DeviceDetectionError,
    Devices,
    parse_device_listing,
    pick_mic,
    pick_screen,
)


STANDARD_LISTING = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] Capture screen 0
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Pro Microphone
[in#0 @ 0x2] Error opening input: Input/output error
"""

EXTERNAL_MONITOR_LISTING = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] External USB Camera
[AVFoundation indev @ 0x1] [2] Capture screen 0
[AVFoundation indev @ 0x1] [3] Capture screen 1
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] External USB Audio
[AVFoundation indev @ 0x1] [1] MacBook Pro Microphone
"""

NO_SCREEN_LISTING = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Pro Microphone
"""


def test_parse_standard_listing() -> None:
    sections = parse_device_listing(STANDARD_LISTING)
    assert sections["video"] == [(0, "FaceTime HD Camera"), (1, "Capture screen 0")]
    assert sections["audio"] == [(0, "MacBook Pro Microphone")]


def test_pick_screen_prefers_capture_screen_device() -> None:
    sections = parse_device_listing(STANDARD_LISTING)
    assert pick_screen(sections["video"]) == 1


def test_pick_screen_on_external_monitor_setup() -> None:
    sections = parse_device_listing(EXTERNAL_MONITOR_LISTING)
    # Should pick first Capture screen (index 2), not the external camera (1).
    assert pick_screen(sections["video"]) == 2


def test_pick_mic_prefers_builtin() -> None:
    sections = parse_device_listing(EXTERNAL_MONITOR_LISTING)
    assert pick_mic(sections["audio"]) == 1


def test_pick_mic_falls_back_to_first_audio() -> None:
    audio = [(0, "External USB Audio")]
    assert pick_mic(audio) == 0


def test_pick_screen_returns_none_when_no_screen() -> None:
    sections = parse_device_listing(NO_SCREEN_LISTING)
    assert pick_screen(sections["video"]) is None


def test_detect_devices_raises_on_missing_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    from bin import devices

    monkeypatch.setattr(
        devices, "list_devices",
        lambda: {"video": [(0, "FaceTime HD Camera")], "audio": [(0, "Mic")]},
    )
    with pytest.raises(DeviceDetectionError, match="No screen-capture"):
        devices.detect_devices()


def test_detect_devices_returns_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    from bin import devices

    monkeypatch.setattr(
        devices, "list_devices",
        lambda: parse_device_listing(EXTERNAL_MONITOR_LISTING),
    )
    result = devices.detect_devices()
    assert result == Devices(screen_index=2, mic_index=1)
    assert result.ffmpeg_input == "2:1"
