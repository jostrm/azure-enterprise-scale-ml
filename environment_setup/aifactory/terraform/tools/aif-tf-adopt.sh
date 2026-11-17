#!/usr/bin/env bash
# Adopt-then-apply for infra-common-terraform.yml: one implementation for the Dev, Stage and Prod jobs.
# Source it (after aif-retry.sh): it only defines functions.
#
#   aif_tf_adopt --root DIR --subscription ID --resource-group NAME [--resource-group NAME ...] -- command [args...]
#   aif_tf_check_plan DIR PLANFILE
#   aif_tf_common_resource_group ENVIRONMENT
#
# Bicep parity: infra-common.yml PUTs (create-or-update) resources the Registered Full bootstrap already created
# (the common resource group, VNet, subnets, NSGs, own hub, seeding Key Vault). Terraform refuses to create them:
# "already exists - to be managed via Terraform this resource needs to be imported into the State".
# aif_tf_adopt runs the command (plan and apply). When it fails with such diagnostics, tf_adopt.py writes an import
# block for each into DIR/aif_adopted_imports.tf and the command runs again, which plans the import with any in-place
# update and applies both. At most AIF_TF_ADOPT_ROUNDS rounds (default 10). Ids outside the subscription and
# resource groups given are refused (nothing is adopted); empty --resource-group values are ignored.
#
# An adopted round's stderr is logged on stdout; only the final round's stderr goes to stderr, so aif_retry judges
# "transient" on the last failure alone. Any failure without something new to adopt returns at once with the
# command's own exit code.
#
# aif_tf_check_plan stops a saved plan that would delete or replace an adopted resource (exit 2): call it between
# plan and apply. aif_tf_common_resource_group prints the common resource group of the run (the Bicep name and the
# Terraform state key): commonResourceGroup_param, else prefix + vnetResourceGroupBase + location + env + suffix.

AIF_TF_ADOPT_HELPER="${AIF_TF_ADOPT_HELPER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tf_adopt.py}"
AIF_TF_ADOPT_IMPORTS="aif_adopted_imports.tf"

aif_tf_adopt() {
  local root="" subscription="" rounds="${AIF_TF_ADOPT_ROUNDS:-10}" round=1 status adopt_status error_file plan_json
  local -a groups=()
  local usage='usage: aif_tf_adopt --root DIR --subscription ID --resource-group NAME [...] -- command [args...]'
  while [ $# -gt 0 ]; do
    case "$1" in
      --root)           root="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --subscription)   subscription="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --resource-group) groups+=(--resource-group "${2:-}"); shift 2 || { echo "$usage" >&2; return 2; } ;;
      --)               shift; break ;;
      *)                echo "aif_tf_adopt: '--' must come before the command. $usage" >&2; return 2 ;;
    esac
  done
  if [ $# -eq 0 ] || [ -z "$root" ] || [ -z "$subscription" ] || [ ${#groups[@]} -eq 0 ] \
      || ! [[ "$rounds" =~ ^[1-9][0-9]*$ ]]; then
    echo "aif_tf_adopt: a root, a subscription, a resource group, a command and 1 or more rounds are required. $usage" >&2
    return 2
  fi
  error_file="$(mktemp 2>/dev/null || printf '%s' "${TMPDIR:-/tmp}/aif_tf_adopt.$$.$RANDOM")"

  while :; do
    # `if` keeps a failing command from ending the script under `set -e`; stdout passes through.
    if "$@" 2>"$error_file"; then status=0; else status=$?; fi
    if [ "$status" -eq 0 ]; then
      cat "$error_file" >&2; rm -f "$error_file"; return 0
    fi
    if [ "$round" -ge "$rounds" ]; then
      cat "$error_file" >&2; rm -f "$error_file"
      echo "aif_tf_adopt: plan and apply still failed after $round rounds of adopting existing resources (exit $status)." >&2
      return "$status"
    fi
    # The failed round's saved plan names each azapi resource's API version (only piped: it holds sensitive values).
    plan_json=""
    if [ -f "$root/tfplan" ]; then plan_json="$(terraform -chdir="$root" show -json tfplan 2>/dev/null || true)"; fi
    if printf '%s' "$plan_json" | "${AIF_PYTHON:-python3}" "$AIF_TF_ADOPT_HELPER" adopt --errors "$error_file" \
        --imports "$root/$AIF_TF_ADOPT_IMPORTS" --subscription "$subscription" "${groups[@]}" --plan-json - \
        2>>"$error_file.adopt"; then
      echo "aif_tf_adopt: round $round failed on resources that already exist; adopted them (log below), planning again."
      cat "$error_file" "$error_file.adopt"
      rm -f "$error_file.adopt"
      round=$(( round + 1 ))
      continue
    else
      adopt_status=$?
    fi
    cat "$error_file" "$error_file.adopt" >&2
    rm -f "$error_file" "$error_file.adopt"
    [ "$adopt_status" -eq 3 ] || echo "aif_tf_adopt: not adopted (tf_adopt exit $adopt_status); the failure stands." >&2
    return "$status"
  done
}

aif_tf_check_plan() {
  local root="$1" plan="${2:-tfplan}"
  # The plan JSON (it holds sensitive values) is only piped, never written.
  terraform -chdir="$root" show -json "$plan" \
    | "${AIF_PYTHON:-python3}" "$AIF_TF_ADOPT_HELPER" check-plan --imports "$root/$AIF_TF_ADOPT_IMPORTS"
}

aif_tf_common_resource_group() {
  local environment="$1"
  if [ -n "${commonResourceGroup_param:-}" ]; then
    printf '%s\n' "$commonResourceGroup_param"
  else
    printf '%s\n' "${admin_aifactoryPrefixRG:-}${vnetResourceGroupBase:-esml-common}-${admin_locationSuffix:-}-${environment}${admin_aifactorySuffixRG:-}"
  fi
}
