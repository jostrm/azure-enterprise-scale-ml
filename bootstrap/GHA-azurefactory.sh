#!/usr/bin/env bash
# AZUREFACTORY_SCOPED_LAUNCHER_CONTRACT=1
# The catalog UI/API initializes register storage and prepares protected manifests.
# This launcher never creates a legacy root or supplies default target identities.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
enroll)
  source "$root/lib/layout_router.sh"
  aif_route_enrollment gha "$root" "$@"
  ;;
inspect|execute)
  exec bash "$root/AIFactory-lifecycle.sh" "$@" --expected-orchestrator gha
  ;;
capabilities)
  exec bash "$root/AIFactory-lifecycle.sh" capabilities
  ;;
legacy-create|legacy-update)
  exec bash "$root/AIFactory-lifecycle.sh" "$@" --orchestrator gha
  ;;
--help|-h|"")
  printf '%s\n' 'Usage: GHA-azurefactory.sh inspect|execute --protected-manifest <reviewed.dpapi> [execution options]' \
    '       GHA-azurefactory.sh enroll plan|ensure --consumer-root <repo> --factory-id <uuid> --scale-set-id <uuid> --environment dev|stage|prod --options <nonsecret.json> [--acknowledge-exclusive-writer-governance]' \
    '       enroll ensure additionally requires --expected-plan <plan_hash> --yes. See enroll plan --help.' \
    '       GHA-azurefactory.sh legacy-create|legacy-update [legacy launcher options]' \
    'Use the authenticated catalog UI/API to create/register configuration and prepare the exact-target manifest.' \
    'inspect is read-only; execute additionally requires --source-root, --execution-root and --receipt.' \
    'The protected manifest freezes the AI Factory source version; --aifactory-version is a legacy option only.' >&2
  [[ -n "${1:-}" ]] && exit 0
  exit 2
  ;;
*)
  printf 'ERROR: Unsupported GHA Azure Factory action: %s\n' "$1" >&2
  exit 2
  ;;
esac
