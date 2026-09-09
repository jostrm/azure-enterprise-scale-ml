#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR="${AIF_ORCHESTRATOR:-}"
FORWARD_ARGS=()

usage() {
  cat <<'EOF'
Usage: ALL-create-new-aifactory-scaleset.sh [--orchestrator ado|gha] [launcher options]

Selects one existing AI Factory scale-set launcher:
  ado  Azure DevOps: ADO-create-new-aifactory-scaleset.sh
  gha  GitHub Actions: GHA-create-new-aifactory-scaleset.sh

Set AIF_ORCHESTRATOR=ado|gha for non-interactive use. All other arguments are
forwarded unchanged to the selected launcher.
EOF
}

while (( $# )); do
  case "$1" in
    --orchestrator)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      ORCHESTRATOR="$2"
      shift 2
      ;;
    --orchestrator=*)
      ORCHESTRATOR="${1#*=}"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$ORCHESTRATOR" ]]; then
  if printf '%s\n' "${FORWARD_ARGS[@]}" | grep -qx -- '--non-interactive'; then
    printf 'ERROR: Set AIF_ORCHESTRATOR or pass --orchestrator in non-interactive mode.\n' >&2
    exit 2
  fi
  printf 'Choose orchestrator: Azure DevOps (a) or GitHub Actions (g) [a]: '
  read -r ORCHESTRATOR
  ORCHESTRATOR="${ORCHESTRATOR:-a}"
fi

case "${ORCHESTRATOR,,}" in
  a|ado|azure-devops|azuredevops)
    LAUNCHER="$SCRIPT_DIR/ADO-create-new-aifactory-scaleset.sh"
    ;;
  g|gh|gha|github|github-actions)
    LAUNCHER="$SCRIPT_DIR/GHA-create-new-aifactory-scaleset.sh"
    ;;
  *)
    printf "ERROR: Unsupported orchestrator '%s'. Choose ado or gha.\n" "$ORCHESTRATOR" >&2
    exit 2
    ;;
esac

if [[ ! -f "$LAUNCHER" ]]; then
  printf "ERROR: Selected launcher is missing: %s\n" "$LAUNCHER" >&2
  exit 1
fi

exec bash "$LAUNCHER" "${FORWARD_ARGS[@]}"
