"""Active-recording state — atomically stored JSON at cache_root/state.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from bin.paths import state_file


@dataclass(frozen=True)
class State:
    pid: int
    session_id: str
    started_at: float
    is_paused: bool = False


def load_state() -> State | None:
    path = state_file()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    # Tolerate pre-0.3 state files without newer fields.
    data.setdefault("is_paused", False)
    return State(**data)


def save_state(s: State) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2))
    tmp.replace(path)


def clear_state() -> None:
    path = state_file()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def is_process_alive(pid: int) -> bool:
    """POSIX: signal 0 checks existence without sending anything."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, we just can't signal it
    return True
