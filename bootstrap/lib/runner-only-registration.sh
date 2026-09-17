#!/usr/bin/env bash
# Only invoked after runner_bootstrap.py has verified the exact VM and Azure target.
set -euo pipefail
set +x
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$root/create-new-aifactory-scaleset.sh"
AIF_PYTHON=("$AIF_RUNNER_PYTHON")
aif_info() { printf '%s\n' "$*" >&2; }
aif_section() { aif_info "$@"; }
aif_success() { aif_info "$@"; }
aif_error() { aif_info "$@"; }
aif_prepare_runner_vm() { :; }
aif_resolve_azure_cli
case "$AIF_ROUTE" in
  ado) aif_ensure_ado_self_hosted_agent ;;
  gha) aif_ensure_github_self_hosted_agent ;;
  *) exit 2 ;;
esac
