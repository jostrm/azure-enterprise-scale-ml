#!/usr/bin/env bash
# Use the same SDK/CLI as other API clients; never write a catalog in Bash.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$root/.azurefactory-tools/azurefactory" ]]; then
  cli_root="$root/.azurefactory-tools"
elif [[ -d "$root/../environment_setup/azurefactory-cli/src/azurefactory" ]]; then
  cli_root="$(cd "$root/../environment_setup/azurefactory-cli/src" && pwd)"
else
  printf 'ERROR: CLI missing. Refresh using the approved source 01-start-v125-and-above.sh.\n' >&2
  exit 2
fi
if [[ -n "${AIFACTORY_PYTHON:-}" ]]; then
  python_command=("$AIFACTORY_PYTHON")
elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
  python_command=(python3)
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
  python_command=(python)
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
  python_command=(py -3)
else
  printf 'ERROR: Python 3 is required.\n' >&2
  exit 2
fi
# Python on Windows expects native paths and semicolon-separated PYTHONPATH.
if command -v cygpath >/dev/null 2>&1; then
  cli_root="$(cygpath -w "$cli_root")"
fi
export PYTHONPATH="$cli_root"
exec "${python_command[@]}" -B -m azurefactory "$@"
