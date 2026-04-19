from __future__ import annotations

from pathlib import Path

from bin.paths import cache_root, plugin_data_root, session_dir, state_file


def test_cache_root_respects_env(tmp_cache_root: Path) -> None:
    assert cache_root() == tmp_cache_root


def test_plugin_data_root_respects_env(tmp_plugin_data: Path) -> None:
    assert plugin_data_root() == tmp_plugin_data


def test_state_file_path(tmp_cache_root: Path) -> None:
    assert state_file() == tmp_cache_root / "state.json"


def test_session_dir_format(tmp_cache_root: Path) -> None:
    result = session_dir("20260418-143200-fix-checkout")
    assert result == tmp_cache_root / "sessions" / "20260418-143200-fix-checkout"
