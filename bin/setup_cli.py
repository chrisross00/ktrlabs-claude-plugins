"""CLI for /record-setup: first-run install + permission check."""
from __future__ import annotations

import sys

from bin.bootstrap import BootstrapError, check_and_install
from bin.probe import permission_remediation_lines, run_probe


def main(argv: list[str]) -> int:
    print("claude-code-recorder setup")
    print("=" * 40)

    # 1. Bootstrap: install/verify ffmpeg, whisper-cli, model.
    print()
    print("Step 1/2: installing dependencies...")
    try:
        check_and_install()
    except BootstrapError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED (unexpected): {e}", file=sys.stderr)
        return 2
    print("  Done.")

    # 2. Probe avfoundation so the macOS permission dialog fires now
    #    rather than on the user's first /record.
    print()
    print("Step 2/2: verifying macOS permissions (Screen Recording + Microphone)...")
    result = run_probe()

    screen = "OK" if result.screen_ok else "DENIED"
    mic = "OK" if result.mic_ok else "DENIED"
    print(f"  Screen Recording: {screen}")
    print(f"  Microphone:       {mic}")
    print(f"  (probe output: {result.bytes_seen} bytes)")

    if result.captured:
        print()
        print("Setup complete. Start a demo with /claude-code-recorder:record [title].")
        return 0

    if result.stderr_tail:
        print()
        print("  Last ffmpeg output:")
        for line in result.stderr_tail:
            print(f"    {line}")
    print()
    for line in permission_remediation_lines():
        print(f"  {line}")
    print()
    print("After granting access, rerun /claude-code-recorder:record-setup.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
