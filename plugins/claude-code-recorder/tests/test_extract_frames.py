# tests/test_extract_frames.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.pipeline.extract_frames import (
    FrameEvent,
    dedup_timestamps,
    extract_frames,
    find_deictic_cues,
    merge_events,
)


def test_find_deictic_cues() -> None:
    segments = [
        {"start_s": 0.0, "end_s": 2.0, "text": "okay now"},
        {"start_s": 2.0, "end_s": 5.0, "text": "click here to submit"},
        {"start_s": 5.0, "end_s": 8.0, "text": "notice the error"},
    ]
    events = find_deictic_cues(segments)
    # "click" cue at 2.0, "here" also at 2.0 (dedup later), "notice" at 5.0
    timestamps = [e.timestamp_s for e in events]
    assert 2.0 in timestamps
    assert 5.0 in timestamps


def test_dedup_timestamps() -> None:
    events = [
        FrameEvent(timestamp_s=0.5, trigger="scene"),
        FrameEvent(timestamp_s=1.0, trigger="cue"),
        FrameEvent(timestamp_s=2.8, trigger="scene"),
        FrameEvent(timestamp_s=3.0, trigger="cue"),  # within 2s of 2.8, drop
        FrameEvent(timestamp_s=6.0, trigger="cue"),
    ]
    result = dedup_timestamps(events, window_s=2.0)
    kept = [e.timestamp_s for e in result]
    assert kept == [0.5, 2.8, 6.0]


def test_merge_events_sorts_and_dedups() -> None:
    scene = [FrameEvent(2.8, "scene")]
    cue = [FrameEvent(0.5, "cue"), FrameEvent(3.0, "cue"), FrameEvent(6.0, "cue")]
    merged = merge_events(scene, cue, window_s=2.0)
    assert [e.timestamp_s for e in merged] == [0.5, 2.8, 6.0]


@patch("bin.pipeline.extract_frames._perceptual_dedup")
@patch("bin.pipeline.extract_frames._extract_frame_png")
@patch("bin.pipeline.extract_frames._detect_scene_changes")
def test_extract_frames_integration(
    detect_scene: MagicMock,
    extract_png: MagicMock,
    perceptual: MagicMock,
    tmp_path: Path,
) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "video.mp4").write_bytes(b"fake")
    transcript = {
        "segments": [
            {"start_s": 0.0, "end_s": 2.0, "text": "click here"},
            {"start_s": 4.0, "end_s": 6.0, "text": "notice the error"},
        ]
    }
    (sdir / "transcript.json").write_text(json.dumps(transcript))

    detect_scene.return_value = [1.0, 4.5]
    perceptual.side_effect = lambda events, frames_dir: events  # pass-through
    # extract_png writes a dummy file per call
    def _write(video: Path, ts: float, out: Path) -> None:
        out.write_bytes(b"png")
    extract_png.side_effect = _write

    extract_frames(sdir)

    frames_json = json.loads((sdir / "frames.json").read_text())
    assert len(frames_json["frames"]) >= 2
    for f in frames_json["frames"]:
        assert "timestamp_s" in f
        assert "filename" in f
        assert "trigger" in f


@patch("bin.pipeline.extract_frames._perceptual_dedup")
@patch("bin.pipeline.extract_frames._extract_frame_png")
@patch("bin.pipeline.extract_frames._detect_scene_changes")
def test_extract_frames_without_transcript_still_emits_scene_frames(
    detect_scene: MagicMock,
    extract_png: MagicMock,
    perceptual: MagicMock,
    tmp_path: Path,
) -> None:
    """If transcribe failed upstream (no transcript.json), frames should
    still be produced from scene-change timestamps alone."""
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "video.mp4").write_bytes(b"fake")
    # Intentionally: no transcript.json.

    detect_scene.return_value = [1.0, 4.5]
    perceptual.side_effect = lambda events, frames_dir: events
    extract_png.side_effect = lambda video, ts, out: out.write_bytes(b"png")

    extract_frames(sdir)

    frames = json.loads((sdir / "frames.json").read_text())["frames"]
    assert len(frames) == 2
    assert all(f["trigger"] == "scene" for f in frames)
