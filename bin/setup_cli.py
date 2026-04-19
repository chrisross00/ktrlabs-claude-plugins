"""CLI for /record-setup: first-run install + permission request + probe."""
from __future__ import annotations

import sys

from bin.bootstrap import BootstrapError, check_and_install
from bin.probe import (
    permission_remediation_lines,
    request_microphone_access,
    request_screen_access,
    run_probe,
)


def _describe(result: bool | None) -> str:
    if result is True:
        return "granted"
    if result is False:
        return "denied (or dismissed)"
    return "could not request — swift not available; grant manually in System Settings"


def main(argv: list[str]) -> int:
    print("claude-code-recorder setup")
    print("=" * 40)

    # 1. Bootstrap: install/verify ffmpeg, whisper-cli, model.
    print()
    print("Step 1/3: installing dependencies...")
    try:
        check_and_install()
    except BootstrapError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED (unexpected): {e}", file=sys.stderr)
        return 2
    print("  Done.")

    # 2. Explicitly call macOS permission APIs. These trigger the system
    #    prompts on first run (or return the cached decision silently).
    print()
    print("Step 2/3: requesting macOS permissions (accept any dialogs that appear)...")
    screen = request_screen_access()
    mic = request_microphone_access()
    print(f"  Screen Recording request: {_describe(screen)}")
    print(f"  Microphone request:       {_describe(mic)}")

    # 3. Probe avfoundation to verify the grant actually works end-to-end.
    print()
    print("Step 3/3: verifying capture works...")
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
