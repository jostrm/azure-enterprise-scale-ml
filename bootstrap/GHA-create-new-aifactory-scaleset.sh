#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
aif_scaleset_main "$AIF_SCALESET_ROUTE" "${BASH_SOURCE[0]}" "$@"
