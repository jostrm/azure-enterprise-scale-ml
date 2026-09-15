#!/usr/bin/env bash
# AIFACTORY_LIFECYCLE_CONTRACT=1
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "legacy-create" || "${1:-}" == "legacy-update" ]]; then
  action="$1"
  shift
  orchestrator=""
  forwarded=()
  while (( $# )); do
    case "$1" in
      --orchestrator)
        [[ $# -ge 2 ]] || { printf 'ERROR: --orchestrator requires ado or gha.\n' >&2; exit 2; }
        orchestrator="$2"
        shift 2
        ;;
      --orchestrator=*)
        orchestrator="${1#*=}"
        shift
        ;;
      *)
        forwarded+=("$1")
        shift
        ;;
    esac
  done
  case "$orchestrator:$action" in
    ado:legacy-create) launcher="ADO-create-new-aifactory-scaleset.sh" ;;
    gha:legacy-create) launcher="GHA-create-new-aifactory-scaleset.sh" ;;
    ado:legacy-update) launcher="ADO-update-aifactory-and-run-project.sh" ;;
    gha:legacy-update) launcher="GH-update-aifactory-and-run-project.sh" ;;
    *) printf 'ERROR: Legacy compatibility requires --orchestrator ado|gha.\n' >&2; exit 2 ;;
  esac
  for candidate in "$root/$launcher" "$root/azure-enterprise-scale-ml/bootstrap/$launcher"; do
    [[ ! -f "$candidate" ]] || { exec bash "$candidate" "${forwarded[@]}"; }
  done
  printf 'ERROR: Legacy launcher is not installed: %s\n' "$launcher" >&2
  exit 2
fi
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
