#!/usr/bin/env bash
# Reporting is local and best-effort; it must not replace the deployment result.
helper="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/region_report.py"
python_bin="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -z "$python_bin" ] || [ ! -f "$helper" ]; then
  echo "WARNING: AI Factory region report requires Python and region_report.py." >&2
  exit 0
fi
"$python_bin" "$helper" pipeline "$@" ||
  echo "WARNING: AI Factory region report could not be generated." >&2
exit 0
