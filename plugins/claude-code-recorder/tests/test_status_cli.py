from __future__ import annotations

import time
from pathlib import Path

import pytest

from bin.state import State, save_state
from bin.status_cli import main


def test_idle_prints_no_recording(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([])
    assert code == 0
    assert "No active recording" in capsys.readouterr().out


def test_active_shows_session_and_elapsed(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = "20260418-143200-demo"
    sdir = tmp_cache_root / "sessions" / session_id
    sdir.mkdir(parents=True)
    (sdir / "video.mp4").write_bytes(b"x" * 2048)
    # started 5 seconds ago
    save_state(State(pid=9999, session_id=session_id, started_at=time.time() - 5))

    code = main([])

    assert code == 0
    out = capsys.readouterr().out
    assert session_id in out
    assert "5s" in out
    assert "2.0 KB" in out
    # pid 9999 is almost certainly not alive; status line reflects that.
    assert "DEAD" in out
