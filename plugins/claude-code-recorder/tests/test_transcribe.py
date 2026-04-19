from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.pipeline.transcribe import (
    TranscriptSegment,
    parse_whisper_json,
    transcribe,
)


def test_parse_whisper_json() -> None:
    whisper_out = {
        "transcription": [
            {"offsets": {"from": 0, "to": 3000}, "text": " Hello world"},
            {"offsets": {"from": 3000, "to": 5500}, "text": " click here"},
        ]
    }
    segments = parse_whisper_json(whisper_out)
    assert segments == [
        TranscriptSegment(start_s=0.0, end_s=3.0, text="Hello world"),
        TranscriptSegment(start_s=3.0, end_s=5.5, text="click here"),
    ]


@patch("bin.pipeline.transcribe._run_whisper")
@patch("bin.pipeline.transcribe._extract_audio")
def test_transcribe_writes_json(
    extract_audio: MagicMock,
    run_whisper: MagicMock,
    tmp_path: Path,
) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "video.mp4").write_bytes(b"fake")

    run_whisper.return_value = {
        "transcription": [
            {"offsets": {"from": 0, "to": 1000}, "text": "hi"},
        ]
    }

    transcribe(sdir)

    transcript = json.loads((sdir / "transcript.json").read_text())
    assert transcript["segments"] == [
        {"start_s": 0.0, "end_s": 1.0, "text": "hi"},
    ]
    extract_audio.assert_called_once()
    run_whisper.assert_called_once()


def test_transcribe_missing_video_raises(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    with pytest.raises(FileNotFoundError):
        transcribe(sdir)
