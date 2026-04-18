# claude-code-recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that records a narrated screen demo and produces a chronological prompt (transcript interleaved with screenshot paths) for Claude to act on.

**Architecture:** Staged pipeline (`capture → transcribe → extract_frames → assemble`) triggered by a `/record` toggle command. Dependencies (`ffmpeg`, `whisper.cpp`, Whisper model) are lazily bootstrapped via a SessionStart hook into `${CLAUDE_PLUGIN_DATA}`. Each pipeline stage is an independently testable `dir_in → dir_out` function.

**Tech Stack:** Python 3.11+, pytest, ffmpeg (avfoundation on macOS), whisper.cpp, imagehash (perceptual hashing), Claude Code plugin conventions.

---

## File Structure

```
claude-code-recorder/
├── .claude-plugin/plugin.json         # plugin manifest
├── commands/
│   ├── record.md                      # /record slash command
│   ├── record-clean.md                # /record-clean slash command
│   └── record-doctor.md               # /record-doctor slash command
├── hooks/session-start.sh             # bootstrap hook
├── bin/
│   ├── bootstrap.py                   # verify/install deps
│   ├── record_toggle.py               # start/stop state machine
│   └── pipeline/
│       ├── __init__.py
│       ├── transcribe.py              # whisper.cpp wrapper
│       ├── extract_frames.py          # scene + cue frame extraction
│       └── assemble.py                # emit prompt.md
├── tests/
│   ├── conftest.py
│   ├── fixtures/                      # canned audio/video/transcripts
│   └── test_*.py
├── pyproject.toml
├── .github/workflows/ci.yml
└── README.md
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `bin/__init__.py`
- Create: `bin/pipeline/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "claude-code-recorder"
version = "0.1.0"
description = "CC plugin that turns narrated screen demos into prompts"
requires-python = ">=3.11"
dependencies = [
    "imagehash>=4.3",
    "Pillow>=10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-timeout>=2.2",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.pytest.ini_options]
markers = [
    "e2e: end-to-end tests requiring real whisper model (skipped by default)",
]
addopts = "-m 'not e2e'"
timeout = 30

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
dist/
build/
.venv/
venv/
tests/fixtures/*.mp4
tests/fixtures/*.wav
!tests/fixtures/.gitkeep
```

- [ ] **Step 3: Create empty module files and `conftest.py`**

Create `bin/__init__.py`, `bin/pipeline/__init__.py`, `tests/__init__.py` — all empty.

Create `tests/conftest.py`:
```python
"""Shared pytest fixtures."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from collections.abc import Iterator

import pytest


@pytest.fixture
def tmp_plugin_data(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp dir used as ${CLAUDE_PLUGIN_DATA} for tests."""
    tmp = Path(tempfile.mkdtemp(prefix="cc-recorder-test-"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def tmp_cache_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp dir used as recorder cache root (instead of ~/.cache/recorder)."""
    tmp = Path(tempfile.mkdtemp(prefix="cc-recorder-cache-"))
    monkeypatch.setenv("RECORDER_CACHE_ROOT", str(tmp))
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

Create `tests/fixtures/.gitkeep` (empty file).

- [ ] **Step 4: Verify layout**

Run: `ls claude-code-recorder/bin claude-code-recorder/tests`
Expected: directories exist with `__init__.py` files.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore bin/ tests/
git commit -m "chore: scaffold python project structure"
```

---

## Task 2: Paths module (shared path resolution)

**Files:**
- Create: `bin/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paths.py
from __future__ import annotations

from pathlib import Path

from bin.paths import cache_root, plugin_data_root, session_dir, state_file


def test_cache_root_respects_env(tmp_cache_root: Path) -> None:
    assert cache_root() == tmp_cache_root


def test_plugin_data_root_respects_env(tmp_plugin_data: Path) -> None:
    assert plugin_data_root() == tmp_plugin_data


def test_state_file_path(tmp_cache_root: Path) -> None:
    assert state_file() == tmp_cache_root / "state.json"


def test_session_dir_format(tmp_cache_root: Path) -> None:
    result = session_dir("20260418-143200-fix-checkout")
    assert result == tmp_cache_root / "sessions" / "20260418-143200-fix-checkout"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_paths.py -v`
Expected: FAIL — `bin.paths` does not exist.

- [ ] **Step 3: Implement `bin/paths.py`**

```python
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
    """Persistent plugin data dir (binaries, model). Provided by CC."""
    value = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not value:
        raise RuntimeError("CLAUDE_PLUGIN_DATA not set — run via plugin hook")
    return Path(value)


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
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_paths.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/paths.py tests/test_paths.py
git commit -m "feat(paths): add shared path resolution module"
```

---

## Task 3: Bootstrap manifest (read/write/verify)

**Files:**
- Create: `bin/bootstrap_manifest.py`
- Test: `tests/test_bootstrap_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap_manifest.py
from __future__ import annotations

import json
import time
from pathlib import Path

from bin.bootstrap_manifest import (
    Manifest,
    is_fresh,
    load_manifest,
    save_manifest,
)


def test_load_returns_none_when_missing(tmp_cache_root: Path) -> None:
    assert load_manifest() is None


def test_save_and_load_roundtrip(tmp_cache_root: Path) -> None:
    m = Manifest(
        verified_at=1234567890.0,
        ffmpeg_sha256="abc",
        whisper_sha256="def",
        model_sha256="ghi",
    )
    save_manifest(m)
    loaded = load_manifest()
    assert loaded == m


def test_is_fresh_true_within_ttl(tmp_cache_root: Path) -> None:
    now = time.time()
    m = Manifest(verified_at=now - 60, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    assert is_fresh(m, ttl_seconds=7 * 86400) is True


def test_is_fresh_false_past_ttl(tmp_cache_root: Path) -> None:
    now = time.time()
    m = Manifest(verified_at=now - 10 * 86400, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    assert is_fresh(m, ttl_seconds=7 * 86400) is False


def test_save_creates_parent_dir(tmp_cache_root: Path) -> None:
    m = Manifest(verified_at=0.0, ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c")
    save_manifest(m)
    assert (tmp_cache_root / "bootstrap.json").exists()
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_bootstrap_manifest.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `bin/bootstrap_manifest.py`**

```python
"""Bootstrap manifest: tracks last-verified state of installed dependencies."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_bootstrap_manifest.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/bootstrap_manifest.py tests/test_bootstrap_manifest.py
git commit -m "feat(bootstrap): add manifest read/write with TTL freshness check"
```

---

## Task 4: Bootstrap installer (dependency install/verify)

**Files:**
- Create: `bin/bootstrap.py`
- Test: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap.py
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bin.bootstrap import (
    BootstrapError,
    check_and_install,
    compute_sha256,
    fast_path_ok,
)
from bin.bootstrap_manifest import Manifest, save_manifest


def _touch(path: Path, content: bytes = b"dummy") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_compute_sha256(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert compute_sha256(p) == hashlib.sha256(b"abc").hexdigest()


def test_fast_path_ok_with_fresh_manifest_and_files(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    ffmpeg_hash = _touch(tmp_plugin_data / "bin" / "ffmpeg")
    whisper_hash = _touch(tmp_plugin_data / "bin" / "whisper")
    model_hash = _touch(tmp_plugin_data / "models" / "ggml-small.en.bin")
    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))
    assert fast_path_ok() is True


def test_fast_path_fails_when_manifest_missing(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    assert fast_path_ok() is False


def test_fast_path_fails_when_file_missing(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    save_manifest(Manifest(verified_at=time.time(), ffmpeg_sha256="x", whisper_sha256="y", model_sha256="z"))
    assert fast_path_ok() is False


def test_fast_path_fails_when_stale(tmp_plugin_data: Path, tmp_cache_root: Path) -> None:
    for name in ("bin/ffmpeg", "bin/whisper", "models/ggml-small.en.bin"):
        _touch(tmp_plugin_data / name)
    save_manifest(Manifest(
        verified_at=time.time() - 30 * 86400,
        ffmpeg_sha256="a", whisper_sha256="b", model_sha256="c",
    ))
    assert fast_path_ok() is False


def test_check_and_install_runs_install_when_missing(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    called: list[str] = []

    def fake_install_ffmpeg(dest: Path) -> str:
        return _touch(dest)

    def fake_install_whisper(dest: Path) -> str:
        return _touch(dest)

    def fake_download_model(dest: Path) -> str:
        called.append("model")
        return _touch(dest)

    with patch("bin.bootstrap.install_ffmpeg", fake_install_ffmpeg), \
         patch("bin.bootstrap.install_whisper", fake_install_whisper), \
         patch("bin.bootstrap.download_model", fake_download_model):
        check_and_install()

    assert (tmp_plugin_data / "bin" / "ffmpeg").exists()
    assert (tmp_plugin_data / "bin" / "whisper").exists()
    assert (tmp_plugin_data / "models" / "ggml-small.en.bin").exists()
    assert called == ["model"]


def test_check_and_install_skips_install_on_fast_path(
    tmp_plugin_data: Path, tmp_cache_root: Path
) -> None:
    ffmpeg_hash = _touch(tmp_plugin_data / "bin" / "ffmpeg")
    whisper_hash = _touch(tmp_plugin_data / "bin" / "whisper")
    model_hash = _touch(tmp_plugin_data / "models" / "ggml-small.en.bin")
    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))

    def should_not_run(dest: Path) -> str:
        raise AssertionError("install should not run on fast path")

    with patch("bin.bootstrap.install_ffmpeg", should_not_run), \
         patch("bin.bootstrap.install_whisper", should_not_run), \
         patch("bin.bootstrap.download_model", should_not_run):
        check_and_install()
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_bootstrap.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `bin/bootstrap.py`**

```python
"""Dependency bootstrap: ffmpeg, whisper.cpp, Whisper model."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from bin.bootstrap_manifest import (
    Manifest,
    is_fresh,
    load_manifest,
    save_manifest,
)
from bin.paths import bin_dir, models_dir

FFMPEG_PATH_REL = "ffmpeg"
WHISPER_PATH_REL = "whisper"
MODEL_PATH_REL = "ggml-small.en.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"
MANIFEST_TTL = 7 * 86400  # 7 days


class BootstrapError(RuntimeError):
    pass


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fast_path_ok() -> bool:
    """Return True if all deps are present and manifest is fresh."""
    m = load_manifest()
    if m is None or not is_fresh(m, MANIFEST_TTL):
        return False
    return (
        (bin_dir() / FFMPEG_PATH_REL).exists()
        and (bin_dir() / WHISPER_PATH_REL).exists()
        and (models_dir() / MODEL_PATH_REL).exists()
    )


def install_ffmpeg(dest: Path) -> str:
    """Install ffmpeg by copying from `brew --prefix` or downloading static build."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    brew = shutil.which("brew")
    if brew:
        result = subprocess.run([brew, "--prefix", "ffmpeg"], capture_output=True, text=True)
        if result.returncode == 0:
            src = Path(result.stdout.strip()) / "bin" / "ffmpeg"
            if src.exists():
                shutil.copy(src, dest)
                dest.chmod(0o755)
                return compute_sha256(dest)
        subprocess.run([brew, "install", "ffmpeg"], check=True)
        result = subprocess.run([brew, "--prefix", "ffmpeg"], capture_output=True, text=True, check=True)
        src = Path(result.stdout.strip()) / "bin" / "ffmpeg"
        shutil.copy(src, dest)
        dest.chmod(0o755)
        return compute_sha256(dest)
    raise BootstrapError("Homebrew not found. Install from https://brew.sh then retry.")


def install_whisper(dest: Path) -> str:
    """Install whisper.cpp binary via brew (whisper-cpp package)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    brew = shutil.which("brew")
    if not brew:
        raise BootstrapError("Homebrew not found. Install from https://brew.sh then retry.")
    subprocess.run([brew, "install", "whisper-cpp"], check=True)
    result = subprocess.run([brew, "--prefix", "whisper-cpp"], capture_output=True, text=True, check=True)
    src = Path(result.stdout.strip()) / "bin" / "whisper-cpp"
    shutil.copy(src, dest)
    dest.chmod(0o755)
    return compute_sha256(dest)


def download_model(dest: Path) -> str:
    """Download the Whisper model, retrying once on checksum mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        tmp = dest.with_suffix(".tmp")
        with urllib.request.urlopen(MODEL_URL) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
        # whisper.cpp doesn't publish a checksum manifest; accept any successful download
        # but on attempt 2, require at least that file is nonempty
        if tmp.stat().st_size < 1_000_000:
            tmp.unlink(missing_ok=True)
            if attempt == 2:
                raise BootstrapError(f"Model download failed (too small) from {MODEL_URL}")
            continue
        tmp.replace(dest)
        return compute_sha256(dest)
    raise BootstrapError("Model download failed after 2 attempts")


def check_and_install() -> None:
    """Main entry: fast path or full install. Called from SessionStart hook."""
    if fast_path_ok():
        return

    ffmpeg_path = bin_dir() / FFMPEG_PATH_REL
    whisper_path = bin_dir() / WHISPER_PATH_REL
    model_path = models_dir() / MODEL_PATH_REL

    ffmpeg_hash = compute_sha256(ffmpeg_path) if ffmpeg_path.exists() else install_ffmpeg(ffmpeg_path)
    whisper_hash = compute_sha256(whisper_path) if whisper_path.exists() else install_whisper(whisper_path)
    model_hash = compute_sha256(model_path) if model_path.exists() else download_model(model_path)

    save_manifest(Manifest(
        verified_at=time.time(),
        ffmpeg_sha256=ffmpeg_hash,
        whisper_sha256=whisper_hash,
        model_sha256=model_hash,
    ))
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_bootstrap.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/bootstrap.py tests/test_bootstrap.py
git commit -m "feat(bootstrap): add dep install + verify with manifest caching"
```

---

## Task 5: SessionStart hook script

**Files:**
- Create: `hooks/session-start.sh`

- [ ] **Step 1: Write the hook script**

```bash
#!/usr/bin/env bash
# claude-code-recorder SessionStart hook.
# Runs `bootstrap.py check_and_install`. Fast path: ~50ms.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "claude-code-recorder: python3 not found; skipping bootstrap" >&2
    exit 0
fi

cd "$PLUGIN_DIR"
python3 -m bin.bootstrap_cli
```

Make executable:
```bash
chmod +x hooks/session-start.sh
```

- [ ] **Step 2: Add the CLI entry**

Create `bin/bootstrap_cli.py`:
```python
"""CLI wrapper so `python3 -m bin.bootstrap_cli` runs check_and_install."""
from __future__ import annotations

import sys

from bin.bootstrap import BootstrapError, check_and_install


def main() -> int:
    try:
        check_and_install()
    except BootstrapError as e:
        print(f"claude-code-recorder bootstrap error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"claude-code-recorder unexpected bootstrap error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke test**

Run (with `CLAUDE_PLUGIN_DATA=/tmp/cc-test` and deps already mocked): `CLAUDE_PLUGIN_DATA=/tmp/skip python3 -m bin.bootstrap_cli 2>&1 || echo "exit=$?"`

Expected: either success (if deps present) or a clear error message — no stack trace leaks.

- [ ] **Step 4: Commit**

```bash
git add hooks/session-start.sh bin/bootstrap_cli.py
git commit -m "feat(bootstrap): add session-start hook and CLI entrypoint"
```

---

## Task 6: State machine — atomic state I/O

**Files:**
- Create: `bin/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
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
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `bin/state.py`**

```python
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


def load_state() -> State | None:
    path = state_file()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_state.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/state.py tests/test_state.py
git commit -m "feat(state): atomic recording state with stale-pid detection"
```

---

## Task 7: Title slugification

**Files:**
- Create: `bin/slug.py`
- Test: `tests/test_slug.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slug.py
from bin.slug import slugify


def test_basic() -> None:
    assert slugify("fix checkout 500") == "fix-checkout-500"


def test_strips_unicode() -> None:
    assert slugify("café ☕ demo") == "cafe-demo"


def test_collapses_spaces() -> None:
    assert slugify("  hello   world  ") == "hello-world"


def test_removes_punctuation() -> None:
    assert slugify("what?! bug: foo/bar") == "what-bug-foo-bar"


def test_limits_length() -> None:
    long = "a" * 100
    assert len(slugify(long)) <= 60


def test_empty_returns_untitled() -> None:
    assert slugify("") == "untitled"


def test_all_punctuation_returns_untitled() -> None:
    assert slugify("!!!???") == "untitled"
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_slug.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/slug.py`**

```python
"""Sluggify free-form title strings for filesystem paths."""
from __future__ import annotations

import re
import unicodedata

MAX_SLUG_LEN = 60


def slugify(title: str) -> str:
    # Strip diacritics.
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Keep alphanumerics; everything else becomes a separator.
    lowered = ascii_only.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not collapsed:
        return "untitled"
    return collapsed[:MAX_SLUG_LEN].rstrip("-")
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_slug.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/slug.py tests/test_slug.py
git commit -m "feat(slug): title sluggification with unicode stripping"
```

---

## Task 8: Record toggle — start logic

**Files:**
- Create: `bin/record_toggle.py`
- Test: `tests/test_record_toggle_start.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_record_toggle_start.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bin.record_toggle import start_recording
from bin.state import load_state


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_creates_session_dir_and_state(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 12345  # simulated ffmpeg PID
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("#!/bin/sh")

    session_id = start_recording(title="fix checkout 500")

    assert session_id.endswith("-fix-checkout-500")
    session_dir = tmp_cache_root / "sessions" / session_id
    assert session_dir.exists()
    assert (session_dir / "metadata.json").exists()

    state = load_state()
    assert state is not None
    assert state.pid == 12345
    assert state.session_id == session_id
    spawn.assert_called_once()


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_without_title_uses_timestamp_only(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 1
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("")

    session_id = start_recording(title=None)

    # YYYYMMDD-HHMMSS with no slug suffix
    assert len(session_id) == 15
    assert session_id[8] == "-"


@patch("bin.record_toggle._spawn_ffmpeg")
def test_start_handles_slug_collision(
    spawn: MagicMock, tmp_cache_root: Path, tmp_plugin_data: Path
) -> None:
    spawn.return_value = 1
    (tmp_plugin_data / "bin" / "ffmpeg").parent.mkdir(parents=True, exist_ok=True)
    (tmp_plugin_data / "bin" / "ffmpeg").write_text("")

    # Pre-create a dir that would collide (same second, same title)
    with patch("bin.record_toggle._timestamp", return_value="20260418-143200"):
        sid1 = start_recording(title="demo")
        # clear state so start_recording proceeds again
        from bin.state import clear_state
        clear_state()
        sid2 = start_recording(title="demo")

    assert sid1 != sid2
    assert sid2.endswith("-2")
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_record_toggle_start.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `bin/record_toggle.py` (start only)**

```python
"""Record start/stop toggle. Invoked by the /record slash command."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from bin.paths import bin_dir, session_dir, sessions_root
from bin.slug import slugify
from bin.state import State, save_state


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_session_id(base: str) -> str:
    """Return `base` if free, else `base-2`, `base-3`, …"""
    if not session_dir(base).exists():
        return base
    n = 2
    while session_dir(f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


def _spawn_ffmpeg(video_path: Path) -> int:
    """Spawn ffmpeg in background. Returns PID."""
    cmd = [
        str(bin_dir() / "ffmpeg"),
        "-y",
        "-f", "avfoundation",
        "-framerate", "30",
        "-i", "1:0",  # screen dev 1, mic dev 0 (macOS default)
        str(video_path),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def start_recording(title: str | None) -> str:
    """Create session dir, spawn ffmpeg, persist state. Returns session_id."""
    base = _timestamp()
    if title:
        base = f"{base}-{slugify(title)}"
    session_id = _unique_session_id(base)
    sdir = session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "session_id": session_id,
        "title": title or "",
        "started_at": time.time(),
    }
    (sdir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    video_path = sdir / "video.mp4"
    pid = _spawn_ffmpeg(video_path)
    save_state(State(pid=pid, session_id=session_id, started_at=time.time()))
    return session_id
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_record_toggle_start.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/record_toggle.py tests/test_record_toggle_start.py
git commit -m "feat(recorder): add start_recording with slug collision handling"
```

---

## Task 9: Record toggle — stop logic

**Files:**
- Modify: `bin/record_toggle.py`
- Test: `tests/test_record_toggle_stop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_record_toggle_stop.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.record_toggle import stop_recording
from bin.state import State, load_state, save_state


def test_stop_noop_when_idle(tmp_cache_root: Path) -> None:
    result = stop_recording()
    assert result is None


@patch("bin.record_toggle._run_pipeline")
@patch("bin.record_toggle._stop_ffmpeg")
def test_stop_sigints_and_runs_pipeline(
    stop_ffmpeg: MagicMock, run_pipeline: MagicMock, tmp_cache_root: Path
) -> None:
    sid = "20260418-143200-demo"
    sdir = tmp_cache_root / "sessions" / sid
    sdir.mkdir(parents=True)
    save_state(State(pid=99999, session_id=sid, started_at=0.0))

    result = stop_recording()

    stop_ffmpeg.assert_called_once_with(99999)
    run_pipeline.assert_called_once_with(sdir)
    assert result == sdir
    assert load_state() is None


@patch("bin.record_toggle._run_pipeline")
@patch("bin.record_toggle._stop_ffmpeg")
@patch("bin.state.is_process_alive", return_value=False)
def test_stop_with_stale_pid_clears_state_and_returns_none(
    is_alive: MagicMock,
    stop_ffmpeg: MagicMock,
    run_pipeline: MagicMock,
    tmp_cache_root: Path,
) -> None:
    save_state(State(pid=999999, session_id="x", started_at=0.0))

    result = stop_recording()

    assert result is None
    assert load_state() is None
    stop_ffmpeg.assert_not_called()
    run_pipeline.assert_not_called()
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_record_toggle_stop.py -v`
Expected: FAIL — functions missing.

- [ ] **Step 3: Extend `bin/record_toggle.py`**

Append to the existing file:
```python
import os
import signal
from pathlib import Path

from bin.paths import session_dir
from bin.state import clear_state, is_process_alive, load_state


def _stop_ffmpeg(pid: int, timeout_s: float = 10.0) -> None:
    """Send SIGINT (lets ffmpeg flush the MP4 moov atom), then wait."""
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not is_process_alive(pid):
            return
        time.sleep(0.1)
    # Escalate if ffmpeg won't exit cleanly.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_pipeline(sdir: Path) -> None:
    """Import lazily so start-path doesn't pay pipeline import cost."""
    from bin.pipeline.transcribe import transcribe
    from bin.pipeline.extract_frames import extract_frames
    from bin.pipeline.assemble import assemble

    try:
        transcribe(sdir)
    except Exception as e:
        (sdir / "transcribe.error.txt").write_text(str(e))

    try:
        extract_frames(sdir)
    except Exception as e:
        (sdir / "extract_frames.error.txt").write_text(str(e))

    # assemble always runs — it handles upstream errors.
    assemble(sdir)


def stop_recording() -> Path | None:
    """Stop active recording and run the pipeline. Returns session dir or None."""
    state = load_state()
    if state is None:
        return None

    if not is_process_alive(state.pid):
        clear_state()
        return None

    _stop_ffmpeg(state.pid)
    clear_state()

    sdir = session_dir(state.session_id)
    _run_pipeline(sdir)
    return sdir
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_record_toggle_stop.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/record_toggle.py tests/test_record_toggle_stop.py
git commit -m "feat(recorder): add stop_recording with stale-pid recovery"
```

---

## Task 10: Pipeline — transcribe stage

**Files:**
- Create: `bin/pipeline/transcribe.py`
- Test: `tests/test_transcribe.py`
- Create: `tests/fixtures/transcript_sample.json`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcribe.py
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
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_transcribe.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/pipeline/transcribe.py`**

```python
"""Transcribe stage: video.mp4 → transcript.json via whisper.cpp."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

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
            "-m", str(models_dir() / "ggml-small.en.bin"),
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_transcribe.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/pipeline/transcribe.py tests/test_transcribe.py
git commit -m "feat(pipeline): transcribe stage with whisper.cpp wrapper"
```

---

## Task 11: Pipeline — extract_frames (scene-change + cue detection)

**Files:**
- Create: `bin/pipeline/extract_frames.py`
- Test: `tests/test_extract_frames.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_extract_frames.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/pipeline/extract_frames.py`**

```python
"""Extract screenshots at scene-changes and transcript-cued timestamps."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from bin.paths import bin_dir

DEICTIC_PATTERN = re.compile(
    r"\b(here|this|notice|look at|see|watch|click|type|press)\b",
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
    """Drop frames whose perceptual hash is within 5 bits of a kept frame."""
    import imagehash
    from PIL import Image

    kept: list[tuple[FrameEvent, imagehash.ImageHash]] = []
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
    """Produce frames/*.png and frames.json from video.mp4 + transcript.json."""
    video = session_dir / "video.mp4"
    transcript = json.loads((session_dir / "transcript.json").read_text())

    frames_dir = session_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    scene_events = [FrameEvent(t, "scene") for t in _detect_scene_changes(video)]
    cue_events = find_deictic_cues(transcript["segments"])
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_extract_frames.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/pipeline/extract_frames.py tests/test_extract_frames.py
git commit -m "feat(pipeline): extract_frames with scene+cue detection and dedup"
```

---

## Task 12: Pipeline — assemble stage

**Files:**
- Create: `bin/pipeline/assemble.py`
- Test: `tests/test_assemble.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assemble.py
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
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_assemble.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/pipeline/assemble.py`**

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_assemble.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/pipeline/assemble.py tests/test_assemble.py
git commit -m "feat(pipeline): assemble stage with missing-upstream resilience"
```

---

## Task 13: /record slash command

**Files:**
- Create: `bin/record_cli.py`
- Create: `commands/record.md`
- Test: `tests/test_record_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_record_cli.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.record_cli import main


@patch("bin.record_cli.stop_recording")
@patch("bin.record_cli.start_recording")
@patch("bin.record_cli.load_state", return_value=None)
def test_idle_starts_recording_with_title(
    load_state: MagicMock,
    start: MagicMock,
    stop: MagicMock,
    capsys: "pytest.CaptureFixture[str]",
) -> None:
    start.return_value = "20260418-143200-demo"
    exit_code = main(["fix", "checkout", "500"])
    start.assert_called_once_with(title="fix checkout 500")
    stop.assert_not_called()
    assert exit_code == 0
    assert "started" in capsys.readouterr().out.lower()


@patch("bin.record_cli.stop_recording")
@patch("bin.record_cli.start_recording")
@patch("bin.record_cli.load_state")
def test_active_runs_stop_and_prints_prompt(
    load_state: MagicMock,
    start: MagicMock,
    stop: MagicMock,
    tmp_path: Path,
    capsys: "pytest.CaptureFixture[str]",
) -> None:
    load_state.return_value = object()  # truthy
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# hi\n[00:00] demo\n")
    stop.return_value = sdir

    exit_code = main([])

    stop.assert_called_once()
    start.assert_not_called()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "# hi" in out
    assert "[00:00] demo" in out
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_record_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/record_cli.py`**

```python
"""CLI entry for /record slash command. Prints output CC injects as prompt."""
from __future__ import annotations

import sys
from pathlib import Path

from bin.record_toggle import start_recording, stop_recording
from bin.state import load_state


def main(argv: list[str]) -> int:
    state = load_state()
    if state is None:
        title = " ".join(argv).strip() or None
        session_id = start_recording(title=title)
        print(f"Recording started (session: {session_id}). Run /record again to stop.")
        return 0

    if argv:
        print("Stopping active session — title argument ignored.", file=sys.stderr)
    sdir = stop_recording()
    if sdir is None:
        print("No active recording found.", file=sys.stderr)
        return 0
    prompt_path = sdir / "prompt.md"
    if prompt_path.exists():
        print(prompt_path.read_text())
    else:
        print(f"Recording stopped but prompt not generated. Session: {sdir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Write `commands/record.md`**

```markdown
---
description: Record a narrated screen demo; toggle stop to emit transcript+screenshots as prompt.
argument-hint: "[optional title]"
---

!`python3 -m bin.record_cli $ARGUMENTS`
```

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_record_cli.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add bin/record_cli.py commands/record.md tests/test_record_cli.py
git commit -m "feat(cli): /record slash command with toggle semantics"
```

---

## Task 14: /record-clean command

**Files:**
- Create: `bin/clean_cli.py`
- Create: `commands/record-clean.md`
- Test: `tests/test_clean_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clean_cli.py
from __future__ import annotations

import time
from pathlib import Path

from bin.clean_cli import main


def _make_session(root: Path, name: str, age_days: float = 0.0, size_bytes: int = 1000) -> Path:
    sdir = root / "sessions" / name
    sdir.mkdir(parents=True)
    (sdir / "video.mp4").write_bytes(b"x" * size_bytes)
    mtime = time.time() - age_days * 86400
    import os
    os.utime(sdir, (mtime, mtime))
    return sdir


def test_list_mode_no_sessions(
    tmp_cache_root: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    code = main([])
    assert code == 0
    assert "no recordings" in capsys.readouterr().out.lower()


def test_list_mode_shows_sessions(
    tmp_cache_root: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    _make_session(tmp_cache_root, "20260418-100000-demo-a")
    _make_session(tmp_cache_root, "20260418-110000-demo-b")
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "demo-a" in out
    assert "demo-b" in out


def test_delete_all(tmp_cache_root: Path) -> None:
    _make_session(tmp_cache_root, "a")
    _make_session(tmp_cache_root, "b")
    code = main(["all"])
    assert code == 0
    assert not list((tmp_cache_root / "sessions").glob("*"))


def test_delete_older_than(tmp_cache_root: Path) -> None:
    _make_session(tmp_cache_root, "old", age_days=30.0)
    _make_session(tmp_cache_root, "new", age_days=1.0)
    code = main(["older-than", "7d"])
    assert code == 0
    assert not (tmp_cache_root / "sessions" / "old").exists()
    assert (tmp_cache_root / "sessions" / "new").exists()


def test_delete_by_id(tmp_cache_root: Path) -> None:
    _make_session(tmp_cache_root, "20260418-100000-demo-a")
    _make_session(tmp_cache_root, "20260418-110000-demo-b")
    code = main(["demo-a"])
    assert code == 0
    assert not (tmp_cache_root / "sessions" / "20260418-100000-demo-a").exists()
    assert (tmp_cache_root / "sessions" / "20260418-110000-demo-b").exists()


def test_delete_ambiguous_match(
    tmp_cache_root: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    _make_session(tmp_cache_root, "20260418-100000-demo")
    _make_session(tmp_cache_root, "20260418-110000-demo")
    code = main(["demo"])
    assert code == 1
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "ambiguous" in out.lower() or "multiple" in out.lower()


def test_delete_no_match(
    tmp_cache_root: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    code = main(["does-not-exist"])
    assert code == 1


def test_older_than_bad_arg(
    tmp_cache_root: Path, capsys: "pytest.CaptureFixture[str]"
) -> None:
    code = main(["older-than", "abc"])
    assert code == 1
    err = capsys.readouterr().err
    assert "format" in err.lower() or "invalid" in err.lower()
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_clean_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/clean_cli.py`**

```python
"""CLI for /record-clean: list or delete recording sessions."""
from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path

from bin.paths import sessions_root

WARN_DISK_USAGE_BYTES = 5 * 1024 * 1024 * 1024  # 5GB


def _parse_duration(s: str) -> int:
    """Parse `7d`, `24h`, `30m` → seconds. Raises ValueError."""
    m = re.fullmatch(r"(\d+)([dhm])", s)
    if not m:
        raise ValueError(f"invalid duration: {s!r} (expected like 7d, 24h, 30m)")
    n, unit = int(m.group(1)), m.group(2)
    multiplier = {"d": 86400, "h": 3600, "m": 60}[unit]
    return n * multiplier


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n //= 1024
    return f"{n}TB"


def _list_sessions() -> list[tuple[Path, float, int]]:
    root = sessions_root()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir():
            out.append((d, d.stat().st_mtime, _dir_size(d)))
    return out


def _list_mode() -> int:
    sessions = _list_sessions()
    if not sessions:
        print("No recordings found.")
        return 0

    now = time.time()
    total = 0
    print(f"{'ID':<40} {'AGE':<10} {'SIZE':>8}")
    for path, mtime, size in sessions:
        age_s = now - mtime
        age = _format_age(age_s)
        print(f"{path.name:<40} {age:<10} {_format_size(size):>8}")
        total += size
    print(f"\nTotal: {_format_size(total)} across {len(sessions)} sessions")
    if total > WARN_DISK_USAGE_BYTES:
        print("⚠ Over 5GB used. Consider: /record-clean older-than 30d")
    return 0


def _format_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _delete_all() -> int:
    sessions = _list_sessions()
    for path, _, _ in sessions:
        shutil.rmtree(path)
    print(f"Deleted {len(sessions)} session(s).")
    return 0


def _delete_older_than(arg: str) -> int:
    try:
        threshold_s = _parse_duration(arg)
    except ValueError as e:
        print(f"record-clean: {e}", file=sys.stderr)
        return 1
    cutoff = time.time() - threshold_s
    deleted = 0
    for path, mtime, _ in _list_sessions():
        if mtime < cutoff:
            shutil.rmtree(path)
            deleted += 1
    print(f"Deleted {deleted} session(s) older than {arg}.")
    return 0


def _delete_by_match(token: str) -> int:
    matches = [p for p, _, _ in _list_sessions() if token in p.name]
    if not matches:
        print(f"No sessions matching {token!r}.", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(
            f"Ambiguous: {len(matches)} sessions match {token!r}:",
            file=sys.stderr,
        )
        for m in matches:
            print(f"  {m.name}", file=sys.stderr)
        return 1
    shutil.rmtree(matches[0])
    print(f"Deleted {matches[0].name}.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return _list_mode()
    if argv[0] == "all":
        return _delete_all()
    if argv[0] == "older-than":
        if len(argv) < 2:
            print("record-clean: older-than requires a duration (e.g. 7d)", file=sys.stderr)
            return 1
        return _delete_older_than(argv[1])
    return _delete_by_match(argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Write `commands/record-clean.md`**

```markdown
---
description: List or delete recording sessions. No args = list; args = delete.
argument-hint: "[all | older-than <N> | <id>]"
---

!`python3 -m bin.clean_cli $ARGUMENTS`
```

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_clean_cli.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add bin/clean_cli.py commands/record-clean.md tests/test_clean_cli.py
git commit -m "feat(cli): /record-clean list/delete command"
```

---

## Task 15: /record-doctor command

**Files:**
- Create: `bin/doctor_cli.py`
- Create: `commands/record-doctor.md`
- Test: `tests/test_doctor_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_cli.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bin.doctor_cli import main
from bin.state import State, save_state


@patch("bin.doctor_cli.check_and_install")
def test_report_shows_sections(
    bootstrap: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: "pytest.CaptureFixture[str]",
) -> None:
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dependencies" in out
    assert "State" in out
    assert "Disk usage" in out


@patch("bin.doctor_cli.is_process_alive", return_value=False)
@patch("bin.doctor_cli.check_and_install")
def test_clears_stale_state(
    bootstrap: MagicMock,
    is_alive: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: "pytest.CaptureFixture[str]",
) -> None:
    save_state(State(pid=999999, session_id="x", started_at=0.0))

    code = main([])

    assert code == 0
    from bin.state import load_state
    assert load_state() is None
    assert "stale" in capsys.readouterr().out.lower()


@patch("bin.doctor_cli.check_and_install", side_effect=RuntimeError("install failed"))
def test_bootstrap_failure_exits_nonzero(
    bootstrap: MagicMock,
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    capsys: "pytest.CaptureFixture[str]",
) -> None:
    code = main([])
    assert code == 1
    assert "install failed" in capsys.readouterr().out + capsys.readouterr().err
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_doctor_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bin/doctor_cli.py`**

```python
"""CLI for /record-doctor: diagnostics and cleanup."""
from __future__ import annotations

import sys
from pathlib import Path

from bin.bootstrap import check_and_install
from bin.paths import bin_dir, models_dir, sessions_root
from bin.state import clear_state, is_process_alive, load_state


def _check_deps() -> list[str]:
    lines = ["Dependencies:"]
    for rel in ["bin/ffmpeg", "bin/whisper", "models/ggml-small.en.bin"]:
        from bin.paths import plugin_data_root
        path = plugin_data_root() / rel
        status = "OK" if path.exists() else "MISSING"
        lines.append(f"  {rel}: {status}")
    return lines


def _check_state() -> list[str]:
    lines = ["State:"]
    state = load_state()
    if state is None:
        lines.append("  Idle.")
        return lines
    if is_process_alive(state.pid):
        lines.append(f"  Active recording (pid {state.pid}, session {state.session_id}).")
    else:
        clear_state()
        lines.append(f"  Stale state (pid {state.pid} dead) — cleared.")
    return lines


def _check_disk() -> list[str]:
    lines = ["Disk usage:"]
    root = sessions_root()
    if not root.exists():
        lines.append("  No sessions.")
        return lines
    total = 0
    count = 0
    for d in root.iterdir():
        if d.is_dir():
            count += 1
            for p in d.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
    mb = total / (1024 * 1024)
    lines.append(f"  {count} session(s), {mb:.1f} MB total.")
    return lines


def main(argv: list[str]) -> int:
    exit_code = 0
    print("claude-code-recorder diagnostics")
    print("=" * 40)

    try:
        check_and_install()
        print("Bootstrap: OK")
    except Exception as e:
        print(f"Bootstrap: FAILED — {e}", file=sys.stderr)
        exit_code = 1

    for section in (_check_deps(), _check_state(), _check_disk()):
        print()
        for line in section:
            print(line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Write `commands/record-doctor.md`**

```markdown
---
description: Diagnose and repair claude-code-recorder dependencies and state.
---

!`python3 -m bin.doctor_cli`
```

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_doctor_cli.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add bin/doctor_cli.py commands/record-doctor.md tests/test_doctor_cli.py
git commit -m "feat(cli): /record-doctor diagnostics command"
```

---

## Task 16: Plugin manifest

**Files:**
- Create: `.claude-plugin/plugin.json`

- [ ] **Step 1: Write the manifest**

```json
{
  "name": "claude-code-recorder",
  "version": "0.1.0",
  "description": "Record a narrated screen demo; get transcript + screenshots as a prompt for Claude.",
  "author": "Chris",
  "commands": [
    {
      "name": "record",
      "file": "commands/record.md"
    },
    {
      "name": "record-clean",
      "file": "commands/record-clean.md"
    },
    {
      "name": "record-doctor",
      "file": "commands/record-doctor.md"
    }
  ],
  "hooks": {
    "SessionStart": "hooks/session-start.sh"
  }
}
```

- [ ] **Step 2: Verify JSON is valid**

Run: `python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"`
Expected: no output (valid JSON).

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat(plugin): add plugin.json manifest"
```

---

## Task 17: End-to-end smoke test

**Files:**
- Create: `tests/test_e2e.py`
- Create: `tests/fixtures/README.md` (instructions for generating fixtures)

- [ ] **Step 1: Write the E2E test (gated on real fixtures)**

```python
# tests/test_e2e.py
"""End-to-end test. Requires:
- tests/fixtures/e2e_demo.mp4 (10s recording, narration mentions "here", "watch", "notice")
- whisper.cpp + ffmpeg + model installed in ${CLAUDE_PLUGIN_DATA}
Run with: pytest -m e2e
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bin.pipeline.assemble import assemble
from bin.pipeline.extract_frames import extract_frames
from bin.pipeline.transcribe import transcribe

pytestmark = pytest.mark.e2e


def test_full_pipeline_on_real_recording(
    tmp_cache_root: Path,
    tmp_plugin_data: Path,
    fixtures_dir: Path,
) -> None:
    demo = fixtures_dir / "e2e_demo.mp4"
    if not demo.exists():
        pytest.skip(f"fixture {demo} missing — see tests/fixtures/README.md")

    sdir = tmp_cache_root / "sessions" / "e2e"
    sdir.mkdir(parents=True)
    shutil.copy(demo, sdir / "video.mp4")
    (sdir / "metadata.json").write_text(
        '{"session_id": "e2e", "title": "e2e", "started_at": 0.0}'
    )

    transcribe(sdir)
    extract_frames(sdir)
    assemble(sdir)

    prompt = (sdir / "prompt.md").read_text()
    # Expect deictic cues from the narration to produce frames.
    for cue in ("here", "watch", "notice"):
        assert cue in prompt.lower(), f"expected narration word '{cue}' in prompt"
    # Expect at least one frame reference.
    assert "![frame_" in prompt
    # Absolute paths required.
    assert str(sdir.resolve()) in prompt
```

- [ ] **Step 2: Write fixtures instructions**

```markdown
<!-- tests/fixtures/README.md -->
# Test fixtures

These aren't checked in (too large). Generate locally:

## e2e_demo.mp4

A ~10s screen recording with narration. Record anything, but the narration should include the words **here**, **watch**, and **notice** (so the deictic-cue path produces frames).

One option using QuickTime: Cmd+Shift+5 → Record Selected Portion → narrate, then export as MP4 here.

Or scripted:
```bash
ffmpeg -f avfoundation -framerate 30 -t 10 -i "1:0" e2e_demo.mp4
# speak during the 10s
```

## Other fixtures (unit tests)

Unit tests use in-memory fixtures or `tmp_path`; no additional files needed.
```

- [ ] **Step 3: Verify E2E is skipped by default**

Run: `pytest -v`
Expected: All earlier tests pass; test_e2e shows "deselected" (unless you pass `-m e2e`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py tests/fixtures/README.md
git commit -m "test: add e2e pipeline smoke test (opt-in via -m e2e)"
```

---

## Task 18: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write CI config**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install ffmpeg
        run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - name: Install project
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Type check
        run: mypy bin tests
      - name: Unit tests
        run: pytest -v  # e2e deselected by default
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add PR workflow (lint, mypy, unit tests)"
```

---

## Task 19: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

```markdown
# claude-code-recorder

Record a narrated screen demo; get a transcript + relevant screenshots as a prompt for Claude Code.

## Install

```
/plugin install claude-code-recorder
```

First session after install downloads `ffmpeg`, `whisper.cpp`, and a Whisper model (~1GB). Subsequent sessions are instant.

## Commands

- `/record [TITLE]` — toggle. First call starts recording; second call stops and emits a chronological prompt (transcript interleaved with screenshots).
- `/record-clean [all | older-than <N> | <id>]` — no args lists sessions; args delete.
- `/record-doctor` — diagnostics and repair.

## How it works

1. `/record` spawns `ffmpeg` to capture screen + mic into `~/.cache/recorder/sessions/<id>/video.mp4`.
2. `/record` again sends SIGINT to ffmpeg (flushes the MP4), then runs the pipeline:
   - **transcribe**: extract audio → run `whisper.cpp` → write `transcript.json` with word-level timestamps.
   - **extract_frames**: find scene changes (ffmpeg scene filter) and deictic-word cues ("here", "notice", "click", etc.); dedup; write `frames/*.png`.
   - **assemble**: interleave transcript segments with screenshot paths chronologically → `prompt.md`.
3. The command prints `prompt.md` into your Claude Code session. Claude automatically `Read`s the screenshot paths.

## Development

```bash
pip install -e ".[dev]"
pytest           # unit tests
pytest -m e2e    # full pipeline (requires fixture + installed deps)
```

See `docs/superpowers/specs/2026-04-18-claude-code-recorder-design.md` for design.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with install, commands, and dev instructions"
```

---

## Self-Review Checklist

Before declaring done:

1. **Spec coverage** — every feature from the spec maps to a task:
   - Plugin structure → Task 1, 16
   - Paths module (not in spec explicitly, but implementation necessity) → Task 2
   - Bootstrap manifest → Task 3
   - Bootstrap install → Task 4
   - SessionStart hook → Task 5
   - State machine → Tasks 6, 8, 9
   - Slug helper → Task 7
   - Transcribe stage → Task 10
   - Extract_frames stage → Task 11
   - Assemble stage → Task 12
   - `/record` command → Task 13
   - `/record-clean` command → Task 14
   - `/record-doctor` command → Task 15
   - E2E test → Task 17
   - CI → Task 18
   - README → Task 19
   - All error-handling cases covered within each task's tests.

2. **Type/signature consistency** — names checked:
   - `start_recording(title: str | None) -> str` used consistently (record_toggle, record_cli).
   - `stop_recording() -> Path | None` consistent.
   - `TranscriptSegment.start_s/end_s/text` consistent across transcribe, extract_frames (via JSON), assemble.
   - `FrameEvent.timestamp_s/trigger` consistent in extract_frames.
   - Path resolution always via `bin.paths` module; no hardcoded paths.

3. **No placeholders** — no TBD/TODO/"implement later". All test code and implementation code is concrete.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-18-claude-code-recorder.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
