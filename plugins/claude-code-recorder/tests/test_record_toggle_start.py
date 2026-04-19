# tests/test_record_toggle_start.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.record_toggle import start_recording
from bin.state import load_state


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_creates_session_dir_and_state(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 12345  # simulated ffmpeg PID
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("#!/bin/sh")

    session_id = start_recording(title="fix checkout 500")

    assert session_id.endswith("-fix-checkout-500")
    session_dir = tmp_cache_root / "sessions" / session_id
    assert session_dir.exists()
    assert (session_dir / "metadata.json").exists()

    state = load_state()
    assert state is not None
    assert state.pid == 12345
    assert state.session_id == session_id
    spawn.assert_called_once()


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_without_title_uses_timestamp_only(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 1
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("")

    session_id = start_recording(title=None)

    # YYYYMMDD-HHMMSS with no slug suffix
    assert len(session_id) == 15
    assert session_id[8] == "-"


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_handles_slug_collision(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 1
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("")

    # Pre-create a dir that would collide (same second, same title)
    with patch("bin.record_toggle._timestamp", return_value="20260418-143200"):
        sid1 = start_recording(title="demo")
        # clear state so start_recording proceeds again
        from bin.state import clear_state
        clear_state()
        sid2 = start_recording(title="demo")

    assert sid1 != sid2
    assert sid2.endswith("-2")
