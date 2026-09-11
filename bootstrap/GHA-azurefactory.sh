#!/usr/bin/env bash
# AZUREFACTORY_SCOPED_LAUNCHER_CONTRACT=1
# The catalog UI/API initializes register storage and prepares protected manifests.
# This launcher never creates a legacy root or supplies default target identities.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != "inspect" && "${1:-}" != "execute" ]]; then
  printf '%s\n' 'Usage: GHA-azurefactory.sh inspect|execute --protected-manifest <reviewed.dpapi> [execution options]' \
    'Use the authenticated catalog UI/API to create/register configuration and prepare the exact-target manifest.' \
    'inspect is read-only; execute additionally requires --source-root, --execution-root and --receipt.' >&2
  [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]] && exit 0
  exit 2
fi
exec bash "$root/AIFactory-lifecycle.sh" "$@" --expected-orchestrator gha
