from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch


from bin.bootstrap import (
    MODEL_PATH_REL,
    check_and_install,
    compute_sha256,
    fast_path_ok,
)
from bin.bootstrap_manifest import Manifest, save_manifest


def _touch(path: Path, content: bytes = b"dummy") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_compute_sha256(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert compute_sha256(p) == hashlib.sha256(b"abc").hexdigest()


def test_fast_path_ok_with_fresh_manifest_and_files(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    ffmpeg_hash = _touch(tmp_plugin_data / "bin" / "ffmpeg")
    whisper_hash = _touch(tmp_plugin_data / "bin" / "whisper")
    model_hash = _touch(tmp_plugin_data / "models" / MODEL_PATH_REL)
    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))
    assert fast_path_ok() is True


def test_fast_path_fails_when_manifest_missing(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    assert fast_path_ok() is False


def test_fast_path_fails_when_file_missing(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    save_manifest(Manifest(verified_at=time.time(), ffmpeg_sha256="x", whisper_sha256="y", model_sha256="z"))
    assert fast_path_ok() is False


def test_fast_path_fails_when_stale(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    for name in ("bin/ffmpeg", "bin/whisper", f"models/{MODEL_PATH_REL}"):
        _touch(tmp_plugin_data / name)
    save_manifest(Manifest(
        verified_at=time.time() - 30 * 86400,
        ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c",
    ))
    assert fast_path_ok() is False


def test_check_and_install_runs_install_when_missing(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    called: list[str] = []

    def fake_install_ffmpeg(dest: Path) -> str:
        return _touch(dest)

    def fake_install_whisper(dest: Path) -> str:
        return _touch(dest)

    def fake_download_model(dest: Path) -> str:
        called.append("model")
        return _touch(dest)

    with patch("bin.bootstrap.install_ffmpeg", fake_install_ffmpeg), \
         patch("bin.bootstrap.install_whisper", fake_install_whisper), \
         patch("bin.bootstrap.download_model", fake_download_model):
        check_and_install()

    assert (tmp_plugin_data / "bin" / "ffmpeg").exists()
    assert (tmp_plugin_data / "bin" / "whisper").exists()
    assert (tmp_plugin_data / "models" / MODEL_PATH_REL).exists()
    assert called == ["model"]


def test_check_and_install_skips_install_on_fast_path(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    ffmpeg_hash = _touch(tmp_plugin_data / "bin" / "ffmpeg")
    whisper_hash = _touch(tmp_plugin_data / "bin" / "whisper")
    model_hash = _touch(tmp_plugin_data / "models" / MODEL_PATH_REL)
    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))

    def should_not_run(dest: Path) -> str:
        raise AssertionError("install should not run on fast path")

    with patch("bin.bootstrap.install_ffmpeg", should_not_run), \
         patch("bin.bootstrap.install_whisper", should_not_run), \
         patch("bin.bootstrap.download_model", should_not_run):
        check_and_install()
