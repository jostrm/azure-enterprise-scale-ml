#!/usr/bin/env bash
# Run a command in a clean, CI-like environment: none of the sandbox's proxy variables or injected tokens,
# a neutral git configuration (no commit signing), the pinned Bicep, PowerShell 7 and an offline Azure CLI on PATH.
# Usage: cienv.sh [EXTRA_PATH_DIR ...] -- command [args...]
set -euo pipefail
extra=""
while [[ $# -gt 0 && "$1" != "--" ]]; do extra="$extra$1:"; shift; done
[[ "${1:-}" == "--" ]] && shift
exec env -i \
  HOME=/root USER=root LOGNAME=root SHELL=/bin/bash TERM=dumb LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  PATH="${extra}/home/user/tools/bicep:/home/user/tools/pwsh:/home/user/venvs/azcli/bin:/opt/node22/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  LIVE_AZURE=0 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
  GIT_CONFIG_GLOBAL=/home/user/tools/gitconfig-tests \
  AZURE_BICEP_USE_BINARY_FROM_PATH=true AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CONFIG_DIR=/home/user/results/az-config \
  AZURE_CORE_ONLY_SHOW_ERRORS=true DOTNET_CLI_TELEMETRY_OPTOUT=1 POWERSHELL_TELEMETRY_OPTOUT=1 \
  "$@"
