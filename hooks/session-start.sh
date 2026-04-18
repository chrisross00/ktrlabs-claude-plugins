#!/usr/bin/env bash
# claude-code-recorder SessionStart hook.
# Runs `bootstrap.py check_and_install`. Fast path: ~50ms.
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "claude-code-recorder: python3 not found; skipping bootstrap" >&2
    exit 0
fi

cd "$PLUGIN_ROOT"
python3 -m bin.bootstrap_cli
