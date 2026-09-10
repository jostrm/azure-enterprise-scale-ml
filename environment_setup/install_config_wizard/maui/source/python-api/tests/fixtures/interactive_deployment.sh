#!/usr/bin/env bash
set -euo pipefail
[[ -t 0 && -t 1 ]] || { printf 'NO_TTY\n'; exit 3; }
if [[ "${SYNTHETIC_CHILD:-}" == "yes" ]]; then
  python -c 'import os,time; print("SYNTHETIC_CHILD_PID:%s" % os.getpid(), flush=True); time.sleep(60)' &
fi
printf '\033[32mSYNTHETIC_PTY_READY\033[0m\r\n'
read -r -p 'Synthetic input: ' value
printf '\r\nRECEIVED:%s\r\n' "$value"
read -r -s -n 1 -p 'Single key: ' key
printf '\r\nKEY:%s\r\n' "$key"
exit 0
