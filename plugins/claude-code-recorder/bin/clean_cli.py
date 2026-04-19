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


AUTO_PRUNE_DAYS = 30  # sessions older than this are removed by auto_prune()


def auto_prune(max_age_days: int = AUTO_PRUNE_DAYS) -> int:
    """Remove session directories older than `max_age_days`.

    Called from the SessionStart hook so housekeeping happens without user
    intervention. Returns the number of sessions removed (0 if none).
    """
    root = sessions_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for d in root.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def _list_sessions() -> list[tuple[Path, float, int]]:
    root = sessions_root()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir():
            out.append((d, d.stat().st_mtime, _dir_size(d)))
    return out


def _format_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


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
