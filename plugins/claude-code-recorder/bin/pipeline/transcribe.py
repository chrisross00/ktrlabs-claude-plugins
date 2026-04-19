"""Transcribe stage: video.mp4 → transcript.json via whisper.cpp."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from bin.bootstrap import MODEL_PATH_REL
from bin.paths import bin_dir, models_dir


@dataclass(frozen=True)
class TranscriptSegment:
    start_s: float
    end_s: float
    text: str


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    subprocess.run(
        [
            str(bin_dir() / "ffmpeg"),
            "-y",
            "-i", str(video_path),
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
    )


def _run_whisper(audio_path: Path) -> dict:
    """Invoke whisper.cpp with JSON output. Returns parsed JSON."""
    out_prefix = audio_path.with_suffix("")
    subprocess.run(
        [
            str(bin_dir() / "whisper"),
            "-m", str(models_dir() / MODEL_PATH_REL),
            "-f", str(audio_path),
            "-oj",
            "-of", str(out_prefix),
        ],
        check=True,
        capture_output=True,
    )
    return json.loads(out_prefix.with_suffix(".json").read_text())


def parse_whisper_json(data: dict) -> list[TranscriptSegment]:
    """whisper.cpp's JSON uses millisecond offsets under `transcription[].offsets`."""
    segments: list[TranscriptSegment] = []
    for entry in data.get("transcription", []):
        offsets = entry["offsets"]
        text = entry["text"].strip()
        segments.append(TranscriptSegment(
            start_s=offsets["from"] / 1000.0,
            end_s=offsets["to"] / 1000.0,
            text=text,
        ))
    return segments


def transcribe(session_dir: Path) -> None:
    """Read session_dir/video.mp4, write session_dir/transcript.json."""
    video = session_dir / "video.mp4"
    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")

    audio = session_dir / "audio.wav"
    _extract_audio(video, audio)

    raw = _run_whisper(audio)
    segments = parse_whisper_json(raw)

    out = {"segments": [asdict(s) for s in segments]}
    (session_dir / "transcript.json").write_text(json.dumps(out, indent=2))
