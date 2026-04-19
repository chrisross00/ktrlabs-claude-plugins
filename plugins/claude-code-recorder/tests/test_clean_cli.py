from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bin.clean_cli import auto_prune, main


def _make_session(root: Path, name: str, age_days: float = 0.0, size_bytes: int = 1000) -> Path:
    sdir = root / "sessions" / name
    sdir.mkdir(parents=True)
    (sdir / "video.mp4").write_bytes(b"x" * size_bytes)
    mtime = time.time() - age_days * 86400
    os.utime(sdir, (mtime, mtime))
    return sdir


def test_list_mode_no_sessions(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([])
    assert code == 0
    assert "no recordings" in capsys.readouterr().out.lower()


def test_list_mode_shows_sessions(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
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
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_session(tmp_cache_root, "20260418-100000-demo")
    _make_session(tmp_cache_root, "20260418-110000-demo")
    code = main(["demo"])
    assert code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "ambiguous" in combined.lower() or "multiple" in combined.lower()


def test_delete_no_match(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["does-not-exist"])
    assert code == 1


def test_older_than_bad_arg(
    tmp_cache_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["older-than", "abc"])
    assert code == 1
    err = capsys.readouterr().err
    assert "format" in err.lower() or "invalid" in err.lower()


def test_auto_prune_removes_only_old(tmp_cache_root: Path) -> None:
    _make_session(tmp_cache_root, "old-1", age_days=60.0)
    _make_session(tmp_cache_root, "old-2", age_days=45.0)
    _make_session(tmp_cache_root, "fresh", age_days=2.0)

    removed = auto_prune(max_age_days=30)

    assert removed == 2
    assert not (tmp_cache_root / "sessions" / "old-1").exists()
    assert not (tmp_cache_root / "sessions" / "old-2").exists()
    assert (tmp_cache_root / "sessions" / "fresh").exists()


def test_auto_prune_noop_when_no_sessions(tmp_cache_root: Path) -> None:
    assert auto_prune() == 0
