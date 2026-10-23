#!/usr/bin/env bash
# =============================================================================
# ensure-encryption-at-host.sh - make sure Microsoft.Compute/EncryptionAtHost is Registered
# before a deployment creates a VM or AKS node pool with encryption at host.
# =============================================================================
# Defender for Cloud baseline: every new AI Factory VM and AKS node pool sets
# encryptionAtHost (enableEncryptionAtHost, default true). ARM rejects that property while the
# subscription feature is not Registered. The scale-set bootstrap registers it in Dev; this check
# covers Stage/Prod and factories upgraded without re-running the bootstrap. Idempotent: a
# Registered feature costs one read. Does nothing when encryption at host is off or when none of
# the given resource flags (enableAdminVM, enableProjectVM, enableAKS, enableAksForAzureML) is true.
#
# Usage: ensure-encryption-at-host.sh <enableEncryptionAtHost> <subscription> <resource flag>...
# =============================================================================
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <enableEncryptionAtHost> <subscription> <resource flag>..." >&2
  exit 2
fi
enabled="${1,,}"
subscription="$2"
shift 2
[[ "$enabled" == "true" ]] || exit 0
needed=false
for flag in "$@"; do
  [[ "${flag,,}" == "true" ]] && needed=true
done
[[ "$needed" == "true" ]] || exit 0

feature_state() {
  local state
  state="$(az feature show --subscription "$subscription" --namespace Microsoft.Compute \
    --name EncryptionAtHost --query properties.state --output tsv --only-show-errors)" || return 1
  printf '%s' "${state//$'\r'/}"
}

state="$(feature_state)" || { echo "Cannot read Microsoft.Compute/EncryptionAtHost in $subscription." >&2; exit 1; }
[[ "$state" != "Registered" ]] || exit 0

echo "Registering Microsoft.Compute/EncryptionAtHost in $subscription (encryption at host for VMs and AKS nodes)."
if ! az feature register --subscription "$subscription" --namespace Microsoft.Compute \
  --name EncryptionAtHost --output none --only-show-errors; then
  echo "Microsoft.Compute/EncryptionAtHost is '$state' in $subscription and this identity cannot register it." >&2
  echo "Ask a subscription owner to run: az feature register --namespace Microsoft.Compute --name EncryptionAtHost," >&2
  echo "or set ENABLE_ENCRYPTION_AT_HOST / enableEncryptionAtHost to false." >&2
  exit 1
fi
for _ in $(seq 1 60); do
  state="$(feature_state)" || state=""
  [[ "$state" == "Registered" ]] && break
  sleep 10
done
if [[ "$state" != "Registered" ]]; then
  echo "Microsoft.Compute/EncryptionAtHost is still '$state' in $subscription; rerun later or set ENABLE_ENCRYPTION_AT_HOST to false." >&2
  exit 1
fi
# A registered feature reaches the resource provider only after the provider is registered again.
az provider register --subscription "$subscription" --namespace Microsoft.Compute --output none --only-show-errors
