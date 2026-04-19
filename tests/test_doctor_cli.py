from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.doctor_cli import main
from bin.state import State, save_state


@patch("bin.doctor_cli.check_and_install")
def test_report_shows_sections(
    bootstrap: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dependencies" in out
    assert "State" in out
    assert "Disk usage" in out


@patch("bin.doctor_cli.is_process_alive", return_value=False)
@patch("bin.doctor_cli.check_and_install")
def test_clears_stale_state(
    bootstrap: MagicMock,
    is_alive: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_state(State(pid=999999, session_id="x", started_at=0.0))

    code = main([])

    assert code == 0
    from bin.state import load_state
    assert load_state() is None
    assert "stale" in capsys.readouterr().out.lower()


@patch("bin.doctor_cli.check_and_install", side_effect=RuntimeError("install failed"))
def test_bootstrap_failure_exits_nonzero(
    bootstrap: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([])
    assert code == 1
    captured = capsys.readouterr()
    assert "install failed" in captured.out + captured.err
