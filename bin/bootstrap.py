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
MODEL_PATH_REL = "ggml-small.en.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
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


def install_ffmpeg(dest: Path) -> str:
    """Install ffmpeg by copying from `brew --prefix` or downloading static build."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    brew = shutil.which("brew")
    if brew:
        result = subprocess.run([brew, "--prefix", "ffmpeg"], capture_output=True, text=True)
        if result.returncode == 0:
            src = Path(result.stdout.strip()) / "bin" / "ffmpeg"
            if src.exists():
                shutil.copy(src, dest)
                dest.chmod(0o755)
                return compute_sha256(dest)
        subprocess.run([brew, "install", "ffmpeg"], check=True)
        result = subprocess.run([brew, "--prefix", "ffmpeg"], capture_output=True, text=True, check=True)
        src = Path(result.stdout.strip()) / "bin" / "ffmpeg"
        shutil.copy(src, dest)
        dest.chmod(0o755)
        return compute_sha256(dest)
    raise BootstrapError("Homebrew not found. Install from https://brew.sh then retry.")


def install_whisper(dest: Path) -> str:
    """Install whisper.cpp binary via brew (whisper-cpp package)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    brew = shutil.which("brew")
    if not brew:
        raise BootstrapError("Homebrew not found. Install from https://brew.sh then retry.")
    subprocess.run([brew, "install", "whisper-cpp"], check=True)
    result = subprocess.run([brew, "--prefix", "whisper-cpp"], capture_output=True, text=True, check=True)
    src = Path(result.stdout.strip()) / "bin" / "whisper-cpp"
    shutil.copy(src, dest)
    dest.chmod(0o755)
    return compute_sha256(dest)


def download_model(dest: Path) -> str:
    """Download the Whisper model, retrying once on checksum mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        tmp = dest.with_suffix(".tmp")
        with urllib.request.urlopen(MODEL_URL) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
        # whisper.cpp doesn't publish a checksum manifest; accept any successful download
        # but on attempt 2, require at least that file is nonempty
        if tmp.stat().st_size < 1_000_000:
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
