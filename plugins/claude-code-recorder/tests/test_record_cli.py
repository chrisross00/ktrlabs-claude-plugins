from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.record_cli import main


@patch("bin.record_cli.stop_recording")
@patch("bin.record_cli.start_recording")
@patch("bin.record_cli.load_state", return_value=None)
def test_idle_starts_recording_with_title(
    load_state: MagicMock,
    start: MagicMock,
    stop: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start.return_value = "20260418-143200-demo"
    exit_code = main(["fix", "checkout", "500"])
    start.assert_called_once_with(title="fix checkout 500")
    stop.assert_not_called()
    assert exit_code == 0
    assert "started" in capsys.readouterr().out.lower()


@patch("bin.record_cli.stop_recording")
@patch("bin.record_cli.start_recording")
@patch("bin.record_cli.load_state")
def test_active_runs_stop_and_prints_prompt(
    load_state: MagicMock,
    start: MagicMock,
    stop: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    load_state.return_value = object()  # truthy
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# hi\n[00:00] demo\n")
    stop.return_value = sdir

    exit_code = main([])

    stop.assert_called_once()
    start.assert_not_called()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "# hi" in out
    assert "[00:00] demo" in out
