#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./run-foundry-usage-report.sh \
    --subscription-id <subscription-id> \
    --resource-group <resource-group> \
    [--workspace-id <log-analytics-workspace-customer-id>] \
    [--as-of-date YYYY-MM-DD] \
    [--time-zone Europe/Berlin] \
    [--output ./foundry-usage.pdf]

The script uses the current Azure CLI login. Install the Python dependencies
from requirements.txt before running it.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI (az) is required." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi
if ! az account show --only-show-errors >/dev/null 2>&1; then
  echo "Sign in first with 'az login' or use an Azure managed identity." >&2
  exit 1
fi

exec python3 "$SCRIPT_DIRECTORY/foundry_usage_report.py" "$@"
