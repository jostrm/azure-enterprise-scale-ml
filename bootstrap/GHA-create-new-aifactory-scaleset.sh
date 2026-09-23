#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for ROUTER in \
  "$SCRIPT_DIR/lib/layout_router.sh" \
  "$SCRIPT_DIR/azure-enterprise-scale-ml/bootstrap/lib/layout_router.sh"; do
  [[ ! -f "$ROUTER" ]] || break
done
[[ -f "$ROUTER" ]] || { printf 'ERROR: AI Factory layout router is missing.\n' >&2; exit 1; }
# shellcheck source=lib/layout_router.sh
source "$ROUTER"
aif_route_runner gha "$SCRIPT_DIR" "$@"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  aif_enrollment_usage "GHA-create-new-aifactory-scaleset.sh"
fi
aif_route_enrollment gha "$SCRIPT_DIR" "$@"
aif_route_registered_layout gha "${AIFACTORY_REPO_ROOT:-$SCRIPT_DIR}" "$SCRIPT_DIR" "$@"
aif_route_modern_creation gha "$SCRIPT_DIR" "$@"
for LIBRARY in \
  "$SCRIPT_DIR/lib/create-new-aifactory-scaleset.sh" \
  "$SCRIPT_DIR/azure-enterprise-scale-ml/bootstrap/lib/create-new-aifactory-scaleset.sh"; do
  [[ ! -f "$LIBRARY" ]] || break
done
if [[ ! -f "$LIBRARY" ]]; then
  printf 'ERROR: AI Factory scale-set bootstrap library is missing.\n' >&2
  exit 1
fi

# shellcheck source=lib/create-new-aifactory-scaleset.sh
source "$LIBRARY"
readonly AIF_SCALESET_ROUTE="gha"
readonly AIF_CREATE_DEFAULT_VERSION="124"
aif_scaleset_main "$AIF_SCALESET_ROUTE" "${BASH_SOURCE[0]}" "$@"
