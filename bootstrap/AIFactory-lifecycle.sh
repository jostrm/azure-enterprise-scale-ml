#!/usr/bin/env bash
# AIFACTORY_LIFECYCLE_CONTRACT=1
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${AIFACTORY_PYTHON:-}" ]]; then
  exec "$AIFACTORY_PYTHON" -B "$root/lib/factory_lifecycle.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 -B "$root/lib/factory_lifecycle.py" "$@"
elif command -v python >/dev/null 2>&1; then
  exec python -B "$root/lib/factory_lifecycle.py" "$@"
else
  printf '%s\n' '{"status":"blocked","error_code":"python-unavailable"}' >&2
  exit 2
fi
