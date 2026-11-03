"""PreToolUse hook: block idle waiting (long sleeps / timers) in Bash and PowerShell commands."""
import json
import re
import sys

PATTERNS = [
    r"\bsleep\s+(\d{3,}|[4-9]\d)\b",                      # sleep 40 / sleep 300
    r"Start-Sleep\b[^;|\n]*?\b(\d{3,}|[4-9]\d)\b",          # Start-Sleep -Seconds 60 / -s 120
    r"\btimeout\s+/t\b",                                    # cmd.exe timeout /t 60
    r"\bping\s+-n\s+\d+\s+127\.0\.0\.1",                   # ping-based sleep
]


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if any(re.search(pattern, command, re.IGNORECASE) for pattern in PATTERNS):
        print("Blocked: idle wait. Poll a real status (az/gh/API) with a bounded loop, "
              "or stop and report what you are waiting for.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
