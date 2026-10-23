#!/usr/bin/env bash
# =============================================================================
# admin-vm-exists.sh - prints "true" when the common admin VM already exists, else "false".
# =============================================================================
# The common pipelines (ADO job-1-aif-cmn.yaml, GHA infra-common.yml) pass the result to
# esml-common/main/13-rgLevel.bicep as adminVmExists. An existing admin VM is never PUT again:
# a Gen1 Data Science VM cannot switch image, Trusted Launch or encryption at host in place, the
# VM is often the self-hosted ADO agent running this very deployment, and its Key Vault password
# must not be rotated by a redeploy. Read-only: one `az vm list`. Fails (no output) when Azure
# cannot be read, so a deployment never guesses.
#
# Names mirror 13-rgLevel.bicep (commonResourceGroupName and the vmPrivate module's vmName):
#   rg = commonResourceGroup_param, else <prefix><commonResourceName>-<locationSuffix>-<env><aifactorySuffixRG>
#   vm = dsvm-cmn-<locationSuffix>-<env><commonResourceSuffix>
#
# Usage: admin-vm-exists.sh <enableAdminVM> <subscription> <commonResourceGroup_param> <commonRGNamePrefix>
#          <commonResourceName> <locationSuffix> <env> <aifactorySuffixRG> <commonResourceSuffix>
# =============================================================================
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "usage: $0 <enableAdminVM> <subscription> <commonResourceGroup_param> <commonRGNamePrefix> <commonResourceName> <locationSuffix> <env> <aifactorySuffixRG> <commonResourceSuffix>" >&2
  exit 2
fi

enable_admin_vm="${1,,}"
subscription="$2"
resource_group="$3"
if [[ "$enable_admin_vm" != "true" ]]; then
  echo false
  exit 0
fi
if [[ -z "$resource_group" ]]; then
  resource_group="${4}${5}-${6}-${7}${8}"
fi
vm_name="dsvm-cmn-${6}-${7}${9}"

count="$(az vm list --subscription "$subscription" --resource-group "$resource_group" \
  --query "length([?name=='${vm_name}'])" --output tsv --only-show-errors)"
count="${count//$'\r'/}"
case "$count" in
  0) echo false ;;
  1) echo true ;;
  *) echo "Unexpected admin VM count for ${vm_name} in ${resource_group}: '${count}'" >&2; exit 1 ;;
esac
