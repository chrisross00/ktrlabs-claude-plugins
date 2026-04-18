"""Assemble stage: combine transcript + frames into prompt.md."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def _load_metadata(session_dir: Path) -> dict:
    return json.loads((session_dir / "metadata.json").read_text())


def _header(session_dir: Path, meta: dict, duration_s: float) -> str:
    title = meta.get("title") or "Screen demo"
    started = datetime.fromtimestamp(meta.get("started_at", 0.0))
    label = f"Screen demo — {title} — {started.strftime('%Y-%m-%d %H:%M')} — {int(duration_s)}s"
    return f"# {label}\n\n"


def _build_events(
    transcript_segments: list[dict],
    frames: list[dict],
    abs_frames_dir: Path,
) -> list[tuple[float, str]]:
    events: list[tuple[float, str]] = []
    for seg in transcript_segments:
        events.append((float(seg["start_s"]), f"[{format_timestamp(seg['start_s'])}] {seg['text']}"))
    for frame in frames:
        abs_path = abs_frames_dir / frame["filename"]
        line = f"[{format_timestamp(frame['timestamp_s'])}] ![{frame['filename']}]({abs_path})"
        events.append((float(frame["timestamp_s"]), line))
    events.sort(key=lambda e: e[0])
    return events


def assemble(session_dir: Path) -> None:
    """Write session_dir/prompt.md. Resilient to missing transcript or frames."""
    sdir = session_dir.resolve()
    meta = _load_metadata(sdir)

    transcript_segments: list[dict] = []
    frames: list[dict] = []
    warnings: list[str] = []

    transcript_path = sdir / "transcript.json"
    if transcript_path.exists():
        transcript_segments = json.loads(transcript_path.read_text())["segments"]
    elif (sdir / "transcribe.error.txt").exists():
        warnings.append(
            f"⚠ transcript missing — video available at: {sdir / 'video.mp4'}"
        )

    frames_path = sdir / "frames.json"
    if frames_path.exists():
        frames = json.loads(frames_path.read_text())["frames"]
    elif (sdir / "extract_frames.error.txt").exists():
        warnings.append(
            f"⚠ frames missing — video available at: {sdir / 'video.mp4'}"
        )

    duration = max(
        [s["end_s"] for s in transcript_segments] + [f["timestamp_s"] for f in frames] + [0.0]
    )

    out = _header(sdir, meta, duration)
    for w in warnings:
        out += w + "\n"
    if warnings:
        out += "\n"

    events = _build_events(transcript_segments, frames, sdir / "frames")
    for _, line in events:
        out += line + "\n"

    out += f"\nSession dir: {sdir}\n"
    (sdir / "prompt.md").write_text(out)
