from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.record_toggle import pause_recording, resume_recording
from bin.state import State, load_state, save_state


@patch("bin.record_toggle._stop_ffmpeg")
@patch("bin.state.is_process_alive", return_value=True)
def test_pause_marks_state_paused_and_stops_ffmpeg(
    is_alive: MagicMock, stop: MagicMock, tmp_cache_root: Path
) -> None:
    save_state(State(pid=111, session_id="s1", started_at=0.0))

    assert pause_recording() is True

    stop.assert_called_once_with(111)
    loaded = load_state()
    assert loaded is not None
    assert loaded.is_paused is True


def test_pause_noop_when_idle(tmp_cache_root: Path) -> None:
    assert pause_recording() is False


@patch("bin.record_toggle._spawn_ffmpeg")
def test_resume_spawns_new_ffmpeg_and_clears_paused(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 222
    sid = "s1"
    sdir = tmp_cache_root / "sessions" / sid
    sdir.mkdir(parents=True)
    # Simulate one existing chunk.
    (sdir / "video_000.mp4").write_bytes(b"x")
    save_state(State(pid=111, session_id=sid, started_at=0.0, is_paused=True))

    assert resume_recording() is True

    # Spawn should have been called with the NEXT chunk path.
    called_path = spawn.call_args[0][0]
    assert called_path.name == "video_001.mp4"

    loaded = load_state()
    assert loaded is not None
    assert loaded.is_paused is False
    assert loaded.pid == 222


def test_resume_noop_when_not_paused(tmp_cache_root: Path) -> None:
    save_state(State(pid=111, session_id="s1", started_at=0.0, is_paused=False))
    assert resume_recording() is False


def test_state_json_without_is_paused_loads_with_default(
    tmp_cache_root: Path,
) -> None:
    # Old-format state file (pre-0.3) has no is_paused field.
    import json
    (tmp_cache_root / "state.json").write_text(
        json.dumps({"pid": 1, "session_id": "s", "started_at": 0.0})
    )
    loaded = load_state()
    assert loaded is not None
    assert loaded.is_paused is False
