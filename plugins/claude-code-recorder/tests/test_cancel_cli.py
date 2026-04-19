from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.cancel_cli import main
from bin.state import State, load_state, save_state


def test_cancel_noop_when_idle(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([])
    assert code == 0
    assert "no active recording" in capsys.readouterr().out.lower()


@patch("bin.cancel_cli._stop_ffmpeg")
@patch("bin.cancel_cli.is_process_alive", return_value=True)
def test_cancel_stops_ffmpeg_and_removes_session_dir(
    is_alive: MagicMock,
    stop_ffmpeg: MagicMock,
    tmp_cache_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sid = "20260418-143200-demo"
    sdir = tmp_cache_root / "sessions" / sid
    sdir.mkdir(parents=True)
    (sdir / "video.mp4").write_bytes(b"fake")
    save_state(State(pid=12345, session_id=sid, started_at=0.0))

    code = main([])

    assert code == 0
    stop_ffmpeg.assert_called_once_with(12345)
    assert load_state() is None
    assert not sdir.exists()
    assert "cancelled" in capsys.readouterr().out.lower()


@patch("bin.cancel_cli._stop_ffmpeg")
@patch("bin.cancel_cli.is_process_alive", return_value=False)
def test_cancel_skips_kill_when_process_already_dead(
    is_alive: MagicMock,
    stop_ffmpeg: MagicMock,
    tmp_cache_root: Path,
) -> None:
    sid = "x"
    sdir = tmp_cache_root / "sessions" / sid
    sdir.mkdir(parents=True)
    save_state(State(pid=999999, session_id=sid, started_at=0.0))

    code = main([])

    assert code == 0
    stop_ffmpeg.assert_not_called()
    assert load_state() is None
    assert not sdir.exists()
