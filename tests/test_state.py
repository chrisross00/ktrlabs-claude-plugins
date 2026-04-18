from __future__ import annotations

import os
from pathlib import Path

from bin.state import State, clear_state, is_process_alive, load_state, save_state


def test_load_returns_none_when_missing(tmp_cache_root: Path) -> None:
    assert load_state() is None


def test_save_and_load_roundtrip(tmp_cache_root: Path) -> None:
    s = State(pid=42, session_id="20260418-143200", started_at=1234567890.0)
    save_state(s)
    assert load_state() == s


def test_save_is_atomic(tmp_cache_root: Path) -> None:
    s = State(pid=1, session_id="a", started_at=0.0)
    save_state(s)
    # No stray .tmp file should remain.
    assert not list(tmp_cache_root.glob("*.tmp"))


def test_clear_state(tmp_cache_root: Path) -> None:
    save_state(State(pid=1, session_id="a", started_at=0.0))
    clear_state()
    assert load_state() is None


def test_clear_state_is_idempotent(tmp_cache_root: Path) -> None:
    clear_state()  # no error when nothing to clear


def test_is_process_alive_true_for_self() -> None:
    assert is_process_alive(os.getpid()) is True


def test_is_process_alive_false_for_nonexistent() -> None:
    # PID 999999 is extremely unlikely to exist
    assert is_process_alive(999999) is False
