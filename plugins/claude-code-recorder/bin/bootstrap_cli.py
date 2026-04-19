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
