from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.probe import ProbeResult
from bin.setup_cli import main


@patch("bin.setup_cli.run_probe")
@patch("bin.setup_cli.check_and_install")
def test_happy_path(
    bootstrap: MagicMock,
    probe: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe.return_value = ProbeResult(captured=True, bytes_seen=12345, stderr_tail=[])
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "Setup complete" in out
    bootstrap.assert_called_once()


@patch("bin.setup_cli.run_probe")
@patch("bin.setup_cli.check_and_install")
def test_probe_failure_returns_nonzero_and_shows_remediation(
    bootstrap: MagicMock,
    probe: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe.return_value = ProbeResult(
        captured=False,
        bytes_seen=0,
        stderr_tail=["[AVFoundation] access denied"],
    )
    code = main([])
    assert code == 1
    out = capsys.readouterr().out
    assert "NOT WORKING" in out
    assert "access denied" in out
    assert "Privacy & Security" in out


@patch("bin.setup_cli.check_and_install", side_effect=RuntimeError("install failed"))
def test_bootstrap_failure_returns_nonzero(
    bootstrap: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([])
    assert code == 2
    combined = capsys.readouterr()
    assert "install failed" in combined.out + combined.err
