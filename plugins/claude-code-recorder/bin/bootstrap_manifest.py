"""Bootstrap manifest: tracks last-verified state of installed dependencies."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from bin.paths import bootstrap_manifest


@dataclass(frozen=True)
class Manifest:
    verified_at: float
    ffmpeg_sha256: str
    whisper_sha256: str
    model_sha256: str


def load_manifest() -> Manifest | None:
    path = bootstrap_manifest()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Manifest(**data)


def save_manifest(m: Manifest) -> None:
    path = bootstrap_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(m), indent=2))
    tmp.replace(path)


def is_fresh(m: Manifest, ttl_seconds: int) -> bool:
    return (time.time() - m.verified_at) < ttl_seconds
