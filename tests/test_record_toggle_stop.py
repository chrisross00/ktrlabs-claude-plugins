# tests/test_record_toggle_stop.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.record_toggle import stop_recording
from bin.state import State, load_state, save_state


def test_stop_noop_when_idle(tmp_cache_root: Path) -> None:
    result = stop_recording()
    assert result is None


@patch("bin.record_toggle._run_pipeline")
@patch("bin.record_toggle._stop_ffmpeg")
@patch("bin.state.is_process_alive", return_value=True)
def test_stop_sigints_and_runs_pipeline(
    is_alive: MagicMock, stop_ffmpeg: MagicMock, run_pipeline: MagicMock, tmp_cache_root: Path
) -> None:
    sid = "20260418-143200-demo"
    sdir = tmp_cache_root / "sessions" / sid
    sdir.mkdir(parents=True)
    save_state(State(pid=99999, session_id=sid, started_at=0.0))

    result = stop_recording()

    stop_ffmpeg.assert_called_once_with(99999)
    run_pipeline.assert_called_once_with(sdir)
    assert result == sdir
    assert load_state() is None


@patch("bin.record_toggle._run_pipeline")
@patch("bin.record_toggle._stop_ffmpeg")
@patch("bin.state.is_process_alive", return_value=False)
def test_stop_with_stale_pid_clears_state_and_returns_none(
    is_alive: MagicMock,
    stop_ffmpeg: MagicMock,
    run_pipeline: MagicMock,
    tmp_cache_root: Path,
) -> None:
    save_state(State(pid=999999, session_id="x", started_at=0.0))

    result = stop_recording()

    assert result is None
    assert load_state() is None
    stop_ffmpeg.assert_not_called()
    run_pipeline.assert_not_called()
