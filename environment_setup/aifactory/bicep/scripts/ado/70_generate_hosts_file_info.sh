#!/usr/bin/env bash
# Compatibility entry point; new ADO/GitHub tasks invoke the Python exporter directly.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$(command -v python || command -v python3 || true)"
if [ -z "$python_bin" ]; then
  echo "ERROR: Python is required to generate the AI Factory hosts inventory." >&2
  exit 1
fi
helper="$script_dir/../generate_hosts_file_info.py"
if command -v cygpath >/dev/null 2>&1; then
  if ! helper="$(cygpath -m "$helper")"; then
    echo "ERROR: Hosts inventory helper path could not be converted for Python." >&2
    exit 1
  fi
fi
exec "$python_bin" -X utf8 "$helper" "$@"
