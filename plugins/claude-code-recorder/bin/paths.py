"""Shared path resolution for runtime + tests."""
from __future__ import annotations

import os
from pathlib import Path


def cache_root() -> Path:
    """Runtime cache dir. Overridable via RECORDER_CACHE_ROOT for tests."""
    override = os.environ.get("RECORDER_CACHE_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "recorder"


def plugin_data_root() -> Path:
    """Persistent plugin data dir (binaries, model).

    CLAUDE_PLUGIN_DATA is honored when set (hooks, tests), but CC doesn't
    appear to set it for slash-command bash. Fall back to a stable user-scoped
    location so both contexts read/write the same path.
    """
    value = os.environ.get("CLAUDE_PLUGIN_DATA")
    if value:
        return Path(value)
    return Path.home() / ".local" / "share" / "claude-code-recorder"


def state_file() -> Path:
    return cache_root() / "state.json"


def sessions_root() -> Path:
    return cache_root() / "sessions"


def session_dir(session_id: str) -> Path:
    return sessions_root() / session_id


def bootstrap_manifest() -> Path:
    return cache_root() / "bootstrap.json"


def bin_dir() -> Path:
    return plugin_data_root() / "bin"


def models_dir() -> Path:
    return plugin_data_root() / "models"
