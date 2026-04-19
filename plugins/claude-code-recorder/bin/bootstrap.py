"""Dependency bootstrap: ffmpeg, whisper.cpp, Whisper model."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from bin.bootstrap_manifest import (
    Manifest,
    is_fresh,
    load_manifest,
    save_manifest,
)
from bin.paths import bin_dir, models_dir

FFMPEG_PATH_REL = "ffmpeg"
WHISPER_PATH_REL = "whisper"
# base multilingual: ~150MB. Noticeably more accurate than tiny (which garbled
# normal narration in testing) while still ~70% smaller than small. Supports
# all languages via a single model.
MODEL_PATH_REL = "ggml-base.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_MIN_BYTES = 100_000_000  # base is ~140MB; refuse anything suspiciously small
MANIFEST_TTL = 7 * 86400  # 7 days


class BootstrapError(RuntimeError):
    pass


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fast_path_ok() -> bool:
    """Return True if all deps are present and manifest is fresh."""
    m = load_manifest()
    if m is None or not is_fresh(m, MANIFEST_TTL):
        return False
    return (
        (bin_dir() / FFMPEG_PATH_REL).exists()
        and (bin_dir() / WHISPER_PATH_REL).exists()
        and (models_dir() / MODEL_PATH_REL).exists()
    )


def _link_brew_binary(dest: Path, formula: str, binary_candidates: list[str]) -> str:
    """Ensure `formula` is installed via brew, symlink the first matching binary
    in <prefix>/bin/ from `binary_candidates` to dest.

    Trying multiple candidate names protects against upstream renames — e.g.
    whisper.cpp's binary was `main`, then `whisper-cpp`, then `whisper-cli`.
    Symlink (not copy) preserves the binary's @rpath-relative dylib lookups.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    brew = shutil.which("brew")
    if not brew:
        raise BootstrapError("Homebrew not found. Install from https://brew.sh then retry.")
    probe = subprocess.run([brew, "--prefix", formula], capture_output=True, text=True)
    if probe.returncode != 0:
        subprocess.run([brew, "install", formula], check=True)
        probe = subprocess.run(
            [brew, "--prefix", formula], capture_output=True, text=True, check=True
        )
    prefix_bin = Path(probe.stdout.strip()) / "bin"
    src: Path | None = None
    for name in binary_candidates:
        candidate = prefix_bin / name
        if candidate.exists():
            src = candidate
            break
    if src is None:
        available = sorted(p.name for p in prefix_bin.iterdir()) if prefix_bin.exists() else []
        raise BootstrapError(
            f"None of {binary_candidates} found under {prefix_bin} after "
            f"`brew install {formula}`. Available: {available}"
        )
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(src)
    return compute_sha256(dest)


def install_ffmpeg(dest: Path) -> str:
    return _link_brew_binary(dest, "ffmpeg", ["ffmpeg"])


def install_whisper(dest: Path) -> str:
    # Tried in order; accommodates whisper.cpp's rename history.
    return _link_brew_binary(dest, "whisper-cpp", ["whisper-cli", "whisper-cpp", "main"])


def download_model(dest: Path) -> str:
    """Download the Whisper model, retrying once on checksum mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        tmp = dest.with_suffix(".tmp")
        with urllib.request.urlopen(MODEL_URL) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
        # whisper.cpp doesn't publish a checksum manifest; accept any successful download
        # but on attempt 2, require at least that file is nonempty
        if tmp.stat().st_size < MODEL_MIN_BYTES:
            tmp.unlink(missing_ok=True)
            if attempt == 2:
                raise BootstrapError(f"Model download failed (too small) from {MODEL_URL}")
            continue
        tmp.replace(dest)
        return compute_sha256(dest)
    raise BootstrapError("Model download failed after 2 attempts")


def check_and_install() -> None:
    """Main entry: fast path or full install. Called from SessionStart hook."""
    if fast_path_ok():
        return

    ffmpeg_path = bin_dir() / FFMPEG_PATH_REL
    whisper_path = bin_dir() / WHISPER_PATH_REL
    model_path = models_dir() / MODEL_PATH_REL

    ffmpeg_hash = compute_sha256(ffmpeg_path) if ffmpeg_path.exists() else install_ffmpeg(ffmpeg_path)
    whisper_hash = compute_sha256(whisper_path) if whisper_path.exists() else install_whisper(whisper_path)
    model_hash = compute_sha256(model_path) if model_path.exists() else download_model(model_path)

    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))
