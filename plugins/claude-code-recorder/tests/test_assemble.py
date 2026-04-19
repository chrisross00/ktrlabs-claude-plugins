from __future__ import annotations

import json
from pathlib import Path

from bin.pipeline.assemble import assemble, format_timestamp


def test_format_timestamp() -> None:
    assert format_timestamp(0.0) == "00:00"
    assert format_timestamp(65.3) == "01:05"
    assert format_timestamp(3600.0) == "60:00"


def test_assemble_interleaves_transcript_and_frames(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "metadata.json").write_text(json.dumps({
        "session_id": "20260418-143200-demo",
        "title": "demo title",
        "started_at": 0.0,
    }))
    (sdir / "transcript.json").write_text(json.dumps({
        "segments": [
            {"start_s": 0.0, "end_s": 3.0, "text": "Opening the checkout page."},
            {"start_s": 5.0, "end_s": 8.0, "text": "I'm clicking Submit."},
        ]
    }))
    (sdir / "frames.json").write_text(json.dumps({
        "frames": [
            {"timestamp_s": 3.0, "filename": "frame_003.png", "trigger": "scene"},
            {"timestamp_s": 5.0, "filename": "frame_005.png", "trigger": "cue"},
        ]
    }))

    assemble(sdir)

    prompt = (sdir / "prompt.md").read_text()
    assert "# Screen demo — demo title" in prompt
    assert "[00:00] Opening the checkout page." in prompt
    assert "[00:05] I'm clicking Submit." in prompt
    # Absolute paths required.
    assert "![frame_003.png](" in prompt
    assert str(sdir.resolve()) in prompt


def test_assemble_handles_missing_transcript(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "metadata.json").write_text(json.dumps({
        "session_id": "x", "title": "", "started_at": 0.0
    }))
    (sdir / "transcribe.error.txt").write_text("whisper failed")

    assemble(sdir)

    prompt = (sdir / "prompt.md").read_text()
    assert "⚠" in prompt
    assert "transcript" in prompt.lower()
    assert "video.mp4" in prompt


def test_assemble_handles_missing_frames(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "metadata.json").write_text(json.dumps({
        "session_id": "x", "title": "", "started_at": 0.0
    }))
    (sdir / "transcript.json").write_text(json.dumps({
        "segments": [{"start_s": 0.0, "end_s": 1.0, "text": "hi"}]
    }))
    (sdir / "extract_frames.error.txt").write_text("ffmpeg failed")

    assemble(sdir)
    prompt = (sdir / "prompt.md").read_text()
    assert "[00:00] hi" in prompt
