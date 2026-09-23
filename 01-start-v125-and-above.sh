#!/usr/bin/env bash
# Registered-layout onboarding only. No download, version switch or deployment.
set -euo pipefail
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${AIFACTORY_PYTHON:-}" ]]; then
  python_command=("$AIFACTORY_PYTHON")
elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
  python_command=(python3)
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
  python_command=(python)
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
  python_command=(py -3)
else
  printf 'ERROR: Python 3 is required for registered-layout onboarding.\n' >&2
  exit 2
fi
exec "${python_command[@]}" -B "$source_root/bootstrap/lib/registered_setup.py" \
  --source "$source_root" --consumer-root "$PWD" "$@"
