"""Shared pytest fixtures."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from collections.abc import Iterator

import pytest


@pytest.fixture
def tmp_plugin_data(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp dir used as ${CLAUDE_PLUGIN_DATA} for tests."""
    tmp = Path(tempfile.mkdtemp(prefix="cc-recorder-test-"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def tmp_cache_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp dir used as recorder cache root (instead of ~/.cache/recorder)."""
    tmp = Path(tempfile.mkdtemp(prefix="cc-recorder-cache-"))
    monkeypatch.setenv("RECORDER_CACHE_ROOT", str(tmp))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
