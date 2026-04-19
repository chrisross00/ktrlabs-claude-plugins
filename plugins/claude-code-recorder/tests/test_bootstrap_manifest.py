# tests/test_bootstrap_manifest.py
from __future__ import annotations

import time
from pathlib import Path

from bin.bootstrap_manifest import (
    Manifest,
    is_fresh,
    load_manifest,
    save_manifest,
)


def test_load_returns_none_when_missing(tmp_cache_root: Path) -> None:
    assert load_manifest() is None


def test_save_and_load_roundtrip(tmp_cache_root: Path) -> None:
    m = Manifest(
        verified_at=1234567890.0,
        ffmpeg_sha256="abc",
        whisper_sha256="def",
        model_sha256="ghi",
    )
    save_manifest(m)
    loaded = load_manifest()
    assert loaded == m


def test_is_fresh_true_within_ttl(tmp_cache_root: Path) -> None:
    now = time.time()
    m = Manifest(verified_at=now - 60, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    assert is_fresh(m, ttl_seconds=7 * 86400) is True


def test_is_fresh_false_past_ttl(tmp_cache_root: Path) -> None:
    now = time.time()
    m = Manifest(verified_at=now - 10 * 86400, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    assert is_fresh(m, ttl_seconds=7 * 86400) is False


def test_save_creates_parent_dir(tmp_cache_root: Path) -> None:
    m = Manifest(verified_at=0.0, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    save_manifest(m)
    assert (tmp_cache_root / "bootstrap.json").exists()
