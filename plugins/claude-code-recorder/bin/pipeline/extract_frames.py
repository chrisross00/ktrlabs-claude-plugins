"""Extract screenshots at scene-changes and transcript-cued timestamps."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bin.paths import bin_dir

# Tightened cue list: prefer strong, action-oriented phrases over weak deictics
# ("this", "here", "see" fire on nearly every sentence). We want frames at
# moments the narrator is calling attention to something specific.
#
# Keeps: verbs that imply a specific thing-on-screen ("notice", "watch", "look at"),
#        action verbs ("click", "type", "press", "scroll", "drag"),
#        pointing phrases ("right here", "right there", "over here", "over there").
# Drops: bare "here/this/see" which are too common to be useful signals.
DEICTIC_PATTERN = re.compile(
    r"\b("
    r"notice|watch|look at|"
    r"click|type|press|scroll|drag|hover|select|"
    r"right (?:here|there)|over (?:here|there)|"
    r"check out|pay attention to"
    r")\b",
    re.IGNORECASE,
)
DEDUP_WINDOW_S = 2.0
SCENE_THRESHOLD = 0.4


@dataclass(frozen=True)
class FrameEvent:
    timestamp_s: float
    trigger: str  # "scene" | "cue"


def _detect_scene_changes(video: Path) -> list[float]:
    """Run ffmpeg scene-change filter, parse 'pts_time:<N>' from stderr."""
    cmd = [
        str(bin_dir() / "ffmpeg"),
        "-i", str(video),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    timestamps: list[float] = []
    for match in re.finditer(r"pts_time:([\d.]+)", result.stderr):
        timestamps.append(float(match.group(1)))
    return timestamps


def find_deictic_cues(segments: list[dict]) -> list[FrameEvent]:
    """Return events at the start timestamp of any segment matching deictic words."""
    events: list[FrameEvent] = []
    for seg in segments:
        if DEICTIC_PATTERN.search(seg["text"]):
            events.append(FrameEvent(timestamp_s=float(seg["start_s"]), trigger="cue"))
    return events


def dedup_timestamps(events: list[FrameEvent], window_s: float) -> list[FrameEvent]:
    """Keep the first event in each `window_s` cluster; drop later ones."""
    if not events:
        return []
    sorted_events = sorted(events, key=lambda e: e.timestamp_s)
    kept: list[FrameEvent] = [sorted_events[0]]
    for e in sorted_events[1:]:
        if e.timestamp_s - kept[-1].timestamp_s >= window_s:
            kept.append(e)
    return kept


def merge_events(
    scene: list[FrameEvent], cue: list[FrameEvent], window_s: float
) -> list[FrameEvent]:
    return dedup_timestamps(scene + cue, window_s)


def _extract_frame_png(video: Path, timestamp_s: float, out_path: Path) -> None:
    cmd = [
        str(bin_dir() / "ffmpeg"),
        "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _perceptual_dedup(events: list[FrameEvent], frames_dir: Path) -> list[FrameEvent]:
    """Drop frames whose perceptual hash is within 5 bits of a kept frame.

    If imagehash / Pillow aren't installed (e.g. plugin running under system
    Python with no extra packages), skip dedup and return events as-is. The
    2s timestamp-based dedup already handled the worst duplication.
    """
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        return events

    kept: list[tuple[FrameEvent, "imagehash.ImageHash"]] = []
    for e in events:
        filename = _frame_filename(e)
        path = frames_dir / filename
        if not path.exists():
            continue
        h = imagehash.phash(Image.open(path))
        if any(h - prev_h < 5 for _, prev_h in kept):
            path.unlink(missing_ok=True)
            continue
        kept.append((e, h))
    return [e for e, _ in kept]


def _frame_filename(event: FrameEvent) -> str:
    return f"frame_{event.timestamp_s:07.3f}.png".replace(".", "_", 1).replace("_png", ".png")


def extract_frames(session_dir: Path) -> None:
    """Produce frames/*.png and frames.json from video.mp4.

    Transcript is optional — if transcribe failed upstream, we still produce
    scene-change frames (just no deictic-cue frames). Partial output is
    strictly better than total failure here.
    """
    video = session_dir / "video.mp4"

    frames_dir = session_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    transcript_path = session_dir / "transcript.json"
    transcript_segments: list[dict] = []
    if transcript_path.exists():
        transcript_segments = json.loads(transcript_path.read_text()).get("segments", [])

    scene_events = [FrameEvent(t, "scene") for t in _detect_scene_changes(video)]
    cue_events = find_deictic_cues(transcript_segments)
    merged = merge_events(scene_events, cue_events, DEDUP_WINDOW_S)

    for e in merged:
        _extract_frame_png(video, e.timestamp_s, frames_dir / _frame_filename(e))

    final = _perceptual_dedup(merged, frames_dir)

    out = {
        "frames": [
            {
                "timestamp_s": e.timestamp_s,
                "filename": _frame_filename(e),
                "trigger": e.trigger,
            }
            for e in final
        ]
    }
    (session_dir / "frames.json").write_text(json.dumps(out, indent=2))
